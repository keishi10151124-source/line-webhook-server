# Architecture: music-agent（仮名）— Tunee の中核機能（チャット作曲）の作り直し

元にした資料：`replica/recon.md`、`replica/features.csv`（2026-11-21）
対象：腹黒メガネさん1人が仕事で使う。一般には公開しない。

## Stack

腹黒メガネさんが普段使っている Python + Flask + Render に合わせます。

| layer | choice | why |
| --- | --- | --- |
| web | Flask 3 + Jinja テンプレート + 少量の素の JavaScript | 既存の line-webhook-server と同じ道具。2ペイン画面とポーリングくらいなら、フレームワークなしで足りる |
| database | Postgres（Render Postgres か Neon）+ SQLAlchemy 2 + Alembic | Render のディスクは再起動で消える。今の `users.json` 方式だと曲と会話が消えるので、DBに置く |
| auth | 自分専用のログイン1つ（パスワードのハッシュを環境変数に置く + Flask の署名付き http-only Cookie） | 使うのは1人だけ。外部の認証サービスは不要 |
| payments | なし | 自分の仕事用。代わりに生成APIの使用量と費用を記録する |
| email | なし | 必要な場面がない |
| agent | Claude API（Anthropic 公式 Python SDK `anthropic`）、モデル `claude-opus-5-5` | 会話、聞き返し、歌詞とスタイル指示を書く部分。下の「エージェント層」で詳しく書く |
| music | 音楽生成API。候補は Mureka API（第一候補）と ElevenLabs Music API（予備）。アダプター経由で差し替えられるようにする | どれも腹黒メガネさん自身のアカウントとキーで使う。**料金と商用規約は契約前に公式ページで確認すること**（下の「音楽APIの比較」） |
| jobs | Postgres のテーブルを使ったジョブキュー + Render の Background Worker 1つ | 生成は数十秒から数分かかるので、Webリクエストの中ではやらない。Redis は不要 |
| files | Cloudflare R2（S3互換、boto3） | 音声ファイルの保存と配信。ダウンロードの転送料がかからない |
| hosting | Render（Web Service 1つ + Background Worker 1つ + Postgres） | すでに使っている。Background Worker と Postgres の料金は Render の現在の料金表で確認すること |

置き場所：このリポジトリの `music_agent/` に作り、Render のサービスは line-webhook-server とは別にします。後から独立したリポジトリに移せる構成にします。

### エージェント層：決めてほしいこと

Claude のエージェントを作る方法は2つあります。

- **A. Managed Agents（Anthropic の標準のおすすめ、ベータ）**
  会話の進行（エージェントループ）を Anthropic 側が動かします。音楽生成のようなこちらのツールは、Flask 側で実行して結果を返します。
  - ベータ版です。
  - トークン料金に加えて、セッションの実行時間にも料金がかかります。
  - 会話の履歴は削除するまで Anthropic 側に残ります。
- **B. Messages API + 自分で書くツールループ（この設計の初期値）**
  `client.messages.create` を Flask から呼び、ツールの呼び出しを自分で回します。
  - 会話はもともと自分の Postgres（`messages` テーブル）に保存するので、状態を二重に持たずに済みます。
  - ツールは3つ（聞き返す、指示を書く、生成する）しかなく、ループが短いです。

**B を初期値にしました。** 理由は、会話の保存先を自分のDB1か所にまとめられることと、Web画面の1往復で処理が終わることです。A がよければ言ってください。ツールの定義はどちらでも同じなので、後から切り替えるのも難しくありません。

B のときの Claude API の設定：
- `model="claude-opus-5-5"`
- `output_config={"effort": "low"}`（チャットなので low から始めて、質が足りなければ上げる）
- `max_tokens` は 16000
- 安全フィルターで断られたときに別モデルで続ける設定（`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`）を初期状態で入れます。不要なら外します。
- システムプロンプトとツール定義は毎回同じ内容にして、プロンプトキャッシュを効かせます。
- ツールは `strict: true` にして、`tool_choice` は `auto` にします。このモデルでは `any` / `tool` を指定すると 400 エラーになります。

ツール：

| tool | 入力 | やること |
| --- | --- | --- |
| `ask_user` | `question`, `options[]`, `multi` | 選択肢つきで聞き返す。画面にボタンとして出し、ループはそこで止める |
| `write_spec` | `title`, `lyrics`, `style_prompt`, `genre`, `mood`, `bpm`, `vocal`, `duration_s` | `song_specs` に新しい版を保存し、右のワークベンチに出す |
| `generate` | `spec_id` | `generation_jobs` に積む。結果はポーリングで受け取る |

システムプロンプトに入れるルール：
- 実在のアーティストの声や曲をそのまま真似する依頼には、雰囲気の言葉（ジャンル、楽器、テンポ）に言い換えて対応する
- 歌詞の著作物（既存曲の歌詞）は使わない

### 音楽APIの比較（2026-11-21時点の第三者ブログの要約。未確認）

| API | 料金（記事による） | 商用利用 | 注意 |
| --- | --- | --- | --- |
| Mureka API | 1曲 $0.03〜$0.15（モデルによる） | 有料APIの出力は商用許諾つき、とする記事あり | 公式APIがある。Tunee も Mureka のモデルを使っている |
| ElevenLabs Music | 生成1分あたり $0.15 | 有料プランで商用可。映画・テレビ・ラジオ・大手ゲームは Enterprise のみ | 規約の線引きがはっきりしている |
| MiniMax Music | 1曲（5分まで）$0.15 | 規約が不明確 | **2026年8月から新規ユーザーには提供していない**という報告あり。対象外にする |
| Google Lyria | 1曲 $0.08 とする記事あり | 要確認 | |
| ACE-Step（オープンソース） | 無料（GPUは自前） | MITライセンス | 自前でGPUを用意する必要がある。ここでは扱わない |

出典：[apiframe.ai](https://apiframe.ai/blog/ai-music-api-pricing-2026)、[invideo.io](https://invideo.io/blog/ai-music-copyright-comparison/)、[aireiter.com](https://aireiter.com/blog/music-generation-api-comparison)、[teamday.ai](https://www.teamday.ai/blog/best-ai-music-models-2026)

アダプターの形：`MusicProvider.submit(spec) -> provider_task_id`, `.poll(task_id) -> status, audio_bytes|url`, `.terms_note -> str`。結果をすぐ返すAPIは、submit の中で完了させて `done` を返す扱いにします。

## Schema

テーブル数：9。アクセス制御：データ層で確認します（RLSは使いません）。すべての読み書きを `owned_by(user)` を通して行い、2人目のユーザーには何も返らないことをテストします。

本体は `replica/schema.sql` を見てください。主な制約：
- `generation_jobs (spec_id, idempotency_key)` に一意制約を付けます。生成ボタンを2回押しても、生成（とその費用）が2回走らないようにするためです。
- `tracks.plan_at_generation` は使ったAPI名とその規約のメモです。その曲を商用で使ってよいかを後から確認できるようにします（Tunee は、生成した時点のプランで権利が決まります）。
- 金額は `cost_micro_usd bigint`（100万分の1ドル単位）で持ちます。1曲 $0.03 のような小さい金額を整数で正確に扱うためです。

## API

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| GET /login, POST /login | ログイン | 誰でも | password | Cookie | — |
| POST /logout | ログアウト | owner | — | — | — |
| GET / | ホーム（新規作成と最近のプロジェクト） | owner | — | HTML S01 | F01 |
| POST /projects | プロジェクトを作り、最初の依頼を送る | owner | text, files[] | redirect → /projects/:id | F01 F04 |
| GET /projects | 一覧 | owner | q | HTML S05 | F06 |
| GET /projects/:id | 作曲セッション画面 | owner | — | HTML S02 | F01 F02 F06 |
| DELETE /projects/:id | 削除（R2のファイルも消す） | owner | — | 204 | — |
| POST /api/projects/:id/messages | ユーザーの発言を送り、エージェントを1周回す | owner | text, choice_ids[], files[] | 新しいメッセージ、spec、job | F01 F02 F03 |
| PATCH /api/specs/:id | 歌詞とスタイル指示を手で直す（新しい版として保存） | owner | lyrics, style_prompt ... | spec | F03 |
| POST /api/specs/:id/generate | 手で生成を始める | owner | idempotency_key | job | F01 |
| GET /api/jobs/:id | 生成の状態（2〜3秒ごとにポーリング） | owner | — | status, track | F01 F02 |
| GET /api/tracks/:id/audio | 再生用の一時URL（R2の署名付きURLへ302） | owner | format=mp3 | 302 | F05 |
| GET /api/tracks/:id/download | ダウンロード | owner | format=mp3, wav | 302 | F05 |
| POST /api/tracks/:id/stems | ステム分離のジョブ（could） | owner | — | job | F05 |
| GET /usage | 今月の使用量と費用 | owner | — | HTML | — |
| GET /healthz | 死活確認 | 誰でも | — | 200 | — |

外から届く Webhook：使う音楽APIが完了通知に対応していれば受け取ります（署名を検証し、`provider_task_id` で重複を除く）。なければポーリングだけにします。
外へ送る Webhook：なし。

ジョブ：
- `worker`：常に動かす。`generation_jobs` から `select ... for update skip locked` で1件ずつ取り、submit と poll を繰り返す。結果は R2 に保存し、`tracks` に記録する。
- `cleanup`：1日1回。24時間以上 `generating` のままのジョブを `failed` にし、孤立した R2 のファイルを消す。
- `spend_guard`：ジョブを取るたびに確認。今日の費用が `DAILY_SPEND_LIMIT_USD` を超えていたら新しいジョブを止める。

## The parts that bite

- **時刻**：DBはすべて UTC の `timestamptz`。画面では Asia/Tokyo で表示する。
- **冪等性**：生成ボタンの二度押し、ジョブの二重取得、Webhook の重複。それぞれ `idempotency_key`、`skip locked`、`provider_task_id` の一意制約で防ぐ。
- **競合**：エージェントが1周回っている途中に次の発言が来た場合。プロジェクト単位でロックし（`select ... for update` を `projects` に）、終わるまで画面の送信ボタンを無効にする。
- **レート制限と費用**：Claude API と音楽APIの 429 は SDK とワーカーがバックオフしてやり直す。同時に生成できるのは2件まで。1日の費用上限も設ける。
- **ファイルサイズ**：添付は音声 20MB、画像 10MB、動画 50MB まで。WAV は大きいので、R2 に直接書き込み、配信は署名付きURLで行う。
- **長い会話**：会話全体を毎回送る。長くなったらサーバー側の圧縮（compaction、ベータ）を使うか、古い発言を要約する。初期版では、1プロジェクト50往復を上限にする。
- **安全フィルターで断られる場合**：`stop_reason == "refusal"` を確認し、画面に「この依頼は作れませんでした」と出す。フォールバック設定も入れる。
- **権利**：曲ごとに、使ったAPIとその規約のメモを残す。商用で使う前に、その規約を自分で確認すること。
- **既存アプリの問題（今回の範囲外）**：line-webhook-server の `USERS_FILE` が `/home/ubuntu/...` を指していて、Render では存在しないか、再起動で消えるディレクトリになっている。

## Build order

1. **最小の通し（vertical slice）**：S07 ログイン → S01 依頼 → S02 エージェントが `write_spec` → `generate` → ワーカー → R2 → 画面で再生。
   - tables：users, projects, messages, song_specs, generation_jobs, tracks, usage_events
   - routes：/login, POST /projects, GET /projects/:id, POST /api/projects/:id/messages, GET /api/jobs/:id, GET /api/tracks/:id/audio
   - 見た目は気にしない。
2. **必須機能（must）**：`ask_user` の選択肢ボタン、言葉での修正とバージョン切り替え、MP3ダウンロード、S05 一覧と会話の再開、生成失敗時のやり直し。
3. **推奨機能（should）**：自分の歌詞を貼る、歌詞とスタイル指示の手直し、WAV、インスト指定、長さとテンポ、波形の表示、費用ページ、権利メモ。
   **任意機能（could）**：添付、ステム分離、マスタリング、複数モデルの切り替え、検索。
4. **replica-entrepreneur で見つかった改善点**：まだ実行していない。
