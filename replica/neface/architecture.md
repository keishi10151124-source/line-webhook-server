# Architecture: face-swap（仮名）— NeFace の中核機能（動画の顔入れ替え）の作り直し

元にした資料：`replica/neface/recon.md`、`replica/neface/features.csv`（2026-11-27。書面同意の仕組みを削除した版）
対象：腹黒メガネさん1人が仕事で使う。入れ替えに使える顔は本人の顔1つだけ。

## Stack

music-agent（Tunee の作り直し）と同じ構成にそろえます。

| layer | choice | why |
| --- | --- | --- |
| web | Flask 3 + Jinja + 少量の素の JavaScript | music-agent と同じ。カメラ撮影は、ブラウザのカメラ機能（getUserMedia）で行う |
| 生体確認（ブラウザ側） | MediaPipe Face Landmarker（Apache 2.0、ブラウザで動く） | 顔の向きとまばたきをその場で判定する。顔の映像はこの段階では外に出さない |
| database | Postgres（Render Postgres か Neon）+ SQLAlchemy 2 + Alembic | music-agent と同じ。同じDBの別スキーマにもできる |
| auth | 自分専用のログイン1つ（パスワードのハッシュ + 署名付き http-only Cookie） | 1人用 |
| payments / email | なし | 自分の仕事用 |
| 顔入れ替え | 外部の動画顔入れ替えAPI。アダプター経由で差し替えられるようにする。候補は Facemint、WaveSpeed、VModel | Render にはGPUがない。**商用利用の規約と顔データの保存期間を、契約前に公式ページで確認すること**（下の「顔入れ替えAPIの比較」） |
| 顔の検出（どの人を入れ替えるか選ぶ画面） | ワーカーで ffmpeg を使って数コマ取り出し、MediaPipe Face Detector（Apache 2.0、CPUで動く）にかける | GPU不要。安い |
| 安全チェック | Claude API（`claude-opus-5-5`、画像入力 + 構造化出力）で、動画から取り出したコマと登録写真を判定する | 性的な内容、18歳未満に見える人、実在の有名人の映像かどうかを判定する。判定はすべて入れ替えより前に行う |
| AI表示 | ffmpeg で透かしを焼き込む + `c2pa-python` で C2PA の Content Credentials を付ける | 透かしは常に入れる。証明書は自分用の自己署名で始める |
| jobs | Postgres のジョブキュー + Render Background Worker（ffmpeg入り） | music-agent と同じ作り |
| files | Cloudflare R2 | 動画、顔写真、書き出し。署名付きURLで配信する |
| hosting | Render（Web + Worker + Postgres） | 使い慣れている |

置き場所：このリポジトリの `face_swap/` に作ります。Render のサービスは music-agent とは別にします。

### 顔入れ替えAPIの比較（2026-11-27時点の業者ページと比較記事の要約。未確認）

| API | 料金（記事による） | 商用利用 | 注意 |
| --- | --- | --- | --- |
| Facemint | 動画 1秒 $0.0045〜（顔の数、解像度、補正で倍率がかかる） | 要確認 | 透かし、NSFW検出、完了通知が無料でついているとされる |
| WaveSpeed AI Video Face Swap | 1秒 $0.01（最低3秒） | 「商用利用の前に規約を確認するように」とFAQに書かれている | REST API |
| VModel Video Face Swap Pro | 1秒 $0.03（$0.008 という記載もあり、食い違う） | 出力は商用利用可、と記載あり | |
| HeyGen | 1秒 $0.05 | 元の素材と顔の権利を持っていれば、広告やクライアントワークに使える | 高め |
| Magic Hour | 1分 $1.38 | 要確認 | |

出典：[Facemint](https://facemint.io/face-swap-api/pricing)、[WaveSpeed](https://wavespeed.ai/models/wavespeed-ai/video-face-swap)、[VModel](https://vmodel.ai/models/vmodel/video-face-swap-pro/)、[HeyGen](https://www.heygen.com/tool/face-swap-video)、[dev.to 比較記事](https://dev.to/magichourai/best-video-face-swap-apis-for-production-setup-cost-per-finished-clip-and-failure-handling-4bnf)、[wavespeed.ai 比較記事](https://wavespeed.ai/blog/posts/best-video-face-swap-tools-online/)

**オープンソースのモデルを自分で動かす方法について：** よく使われる顔入れ替えモデルには、「研究用のみ・商用不可」のライセンスのものがあります（InsightFace の配布モデルなど。ライセンスは配布元で確認してください）。仕事で使うなら、商用利用が許可されたAPIを使うほうが安全です。

**API を選ぶときに確認すること：**
1. 商用利用の可否
2. 送った顔写真と動画をいつ消すか（顔は生体情報です）
3. 学習に使われないか
4. データを処理する国

アダプターの形：`FaceSwapProvider.submit(source_video_url, face_image_url, target_face_index|bbox) -> task_id`, `.poll(task_id) -> status, result_url`, `.terms_note`。

## Schema

テーブル数：7。アクセス制御：データ層で確認します（すべての読み書きを `owned_by(user)` を通す）。

本体は `replica/neface/schema.sql` を見てください。DBの制約で守るルール：
- **顔は1人1つ**：`faces (user_id)` に一意制約。
- **顔はカメラ撮影と生体確認を通ったものだけ**：`faces.source = 'camera'` と `liveness_passed_at is not null` を check 制約にする。
- **入れ替えは本人の顔だけ**：`swap_jobs.face_id` は `faces` への外部キー。`faces` にはカメラ撮影の顔しか入らない。
- **安全チェックに通らないと処理されない**：`swap_jobs` は `safety_status = 'passed'` でないと `submitted` 以降の状態になれない（check 制約）。
- **書き出しには必ずAI表示**：`outputs.watermarked` と `outputs.c2pa_signed` は `true` だけを許す（check 制約）。
- **顔の削除で関連データも消える**：顔を消すと、R2 の写真を消すジョブを積み、DBの行も消える。過去の書き出しは残る（`swap_jobs.face_id` は `on delete set null`）。

## API

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| GET /login, POST /login, POST /logout | ログイン | 誰でも / owner | password | Cookie | — |
| GET / | ホーム（テンプレート、最近の作品） | owner | aspect, category | HTML S01 | F01 |
| GET /templates/:id | テンプレートの詳細 | owner | — | HTML S02 | F01 |
| GET /face | 自分の顔の登録画面 | owner | — | HTML S05 | F03 |
| POST /api/face/challenge | 生体確認の指示を出す（順番はランダム。1回だけ使えるトークンつき） | owner | — | challenge_id, steps[] | F03 |
| POST /api/face | 顔を登録する（指示に合わせた複数のコマと、ブラウザ側の判定結果） | owner | challenge_id, frames[], liveness_result | face | F03 |
| DELETE /api/face | 顔を削除する | owner | — | 204 | F04 |
| POST /api/videos | 動画のアップロード用の署名付きURLを発行する | owner | filename, bytes, rights_confirmed=true | upload_url, video_id | F02 |
| POST /api/videos/:id/complete | アップロード完了。顔の検出と安全チェックのジョブを積む | owner | — | job | F02 |
| GET /api/videos/:id | 検出された顔の一覧と安全チェックの結果 | owner | — | faces[], safety | F01 F02 |
| POST /api/swaps | 入れ替えを始める | owner | video_id, target_face_index, aspect, idempotency_key | swap_job | F01 F02 |
| GET /api/swaps/:id | 状態（2〜3秒ごとにポーリング） | owner | — | status, output | F01 |
| POST /api/swaps/:id/cancel | キャンセル（could） | owner | — | swap_job | — |
| GET /api/outputs/:id/download | ダウンロード（R2の署名付きURLへ302） | owner | — | 302 | F01 |
| GET /library, DELETE /api/outputs/:id | 作品一覧と削除 | owner | — | HTML S08 / 204 | — |
| GET /usage | 今月の費用 | owner | — | HTML | — |
| GET /healthz | 死活確認 | 誰でも | — | 200 | — |

外から届く Webhook：顔入れ替えAPIの完了通知（使うAPIが対応していれば）。署名を検証し、`provider_task_id` の一意制約で重複を除きます。
外へ送る Webhook：なし。

ジョブ（Worker の中）：
- `analyze_video`：ffmpeg で長さを確認し、1秒ごとに1コマ取り出す。MediaPipe で顔を検出して、人ごとにまとめる。代表のコマを Claude で安全チェックする。
- `run_swap`：API に送る → ポーリング → 結果を受け取る → ffmpeg で透かしを焼き込み、縦横に合わせる → c2pa で署名 → R2 に保存 → `outputs` に記録する。
- `purge_face`：顔の削除のあと、R2 の顔写真とコマを消す。
- `cleanup`：1日1回。24時間以上の処理中ジョブを失敗にし、使っていないアップロードを消す。
- `spend_guard`：1日の費用上限（`DAILY_SPEND_LIMIT_USD`）を超えたら、新しいジョブを止める。

## 安全チェックの中身（入れ替えより前）

| いつ | 何を | どうやって | 引っかかったら |
| --- | --- | --- | --- |
| 顔の登録 | 生体確認 | ブラウザ：ランダムな順番の指示（左、右、まばたき）を MediaPipe で判定。サーバー：送られたコマの顔の向きが指示の順番どおりかを再確認 | 登録しない |
| 顔の登録 | 顔が1つか、18歳未満に見えないか | MediaPipe（顔の数）+ Claude（年齢の見た目） | 登録しない |
| 動画のアップロード | 性的な内容、18歳未満に見える人、実在の有名人やニュース映像に見えるか | 1秒1コマから最大12コマを Claude に送り、構造化出力（`sexual`, `minor_present`, `public_figure_or_news`, `reason`）で判定 | `safety_status = 'blocked'`。入れ替えはできない |
| 書き出し | 透かしと C2PA | Worker が必ず付ける | 付けられなければ失敗にする（付けずに出すことはしない） |

Claude API の設定：`model="claude-opus-5-5"`、`output_config={"effort": "low", "format": ...}`（構造化出力）、フォールバックは `fallbacks="default"`。`stop_reason == "refusal"` が返ったら、安全のため `blocked` として扱います。

**限界：** ブラウザ側の生体確認は、技術のある人なら回避できます。サーバー側でも確認しますが、完全ではありません。他人の顔を使わないことの最終的な責任は、使う人（腹黒メガネさん）にあります。

## The parts that bite

- **生体情報**：顔写真と顔の特徴データは、R2 で暗号化したまま保存する。外部APIには、処理に必要な間だけ有効な署名付きURLで渡す。APIの保存期間も確認する。
- **ファイルサイズと長さ**：動画は60秒、200MBまで（APIの上限と費用に合わせて調整する）。ブラウザから R2 に直接アップロードする。
- **冪等性**：入れ替えボタンの二度押しは `idempotency_key` で防ぐ。Webhook とポーリングの重複は `provider_task_id` の一意制約で防ぐ。
- **費用**：1秒単位で課金されるので、実行前に「この動画は○秒、約$○」と表示する。1日の上限も設ける。
- **時刻**：DBはすべて UTC、画面では Asia/Tokyo。
- **品質**：横顔、暗い場面、顔が手で隠れる場面は崩れやすい。APIの比較は、自分の顔と自分で撮った短い動画で行う。
- **素材の権利**：テンプレートは、自分で撮った動画か、モデルリリースのあるストック素材だけにする。アップロード時の権利確認のチェックは必須にする。

## Build order

1. **最小の通し（vertical slice）**：S09 ログイン → S05 カメラで顔登録（生体確認つき）→ S03 自分の動画をアップロード → `analyze_video` → S04 1人を選ぶ → `run_swap`（透かしつき）→ S07 ダウンロード。
   - tables：users, faces, source_videos, swap_jobs, outputs
   - 見た目は気にしない。
2. **必須機能（must）**：安全チェックをすべて入れる、C2PA、テンプレート（S01, S02）、進行状況とやり直し、9:16 と 16:9 の書き出し。
3. **推奨機能（should）**：前後の比較、作品一覧と削除、顔データの完全削除、費用ページ。
   **任意機能（could）**：カテゴリ分け、キャンセル。
4. **replica-entrepreneur で見つかった改善点**：まだ実行していない。
