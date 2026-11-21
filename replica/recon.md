# Recon map: Tunee（AI音楽エージェント）（Web）

Scope: チャットで作曲する中核ループ。会話 → 歌詞とスタイルを決める → 曲を生成 → 試聴して修正を頼む → ダウンロード。MV動画、音声クローン、リップシンク、AIキャラクター、コミュニティ機能は範囲外。
For: 腹黒メガネさん自身の仕事用（自分のコンテンツ用のBGMや曲を作る）。一般販売はしない。
Date: 2026-11-21

## 調査の限界（最初に読んでください）

- tunee.ai はこのクラウド環境のネットワーク設定で遮断されています（プロキシが 403 で拒否）。許可ホストの追加は見送られたので、**Tunee本体のページは一度も直接読めていません**。
- 以下は Web検索の結果（Tunee公式のFAQ、フォーラム、顧客事例ページの検索要約と、第三者のレビュー記事）だけをもとにしています。
- `replica/screens/` に参照用スクリーンショットはありません。画面の構成は推測が多く、確度は低めです。
- **確度を上げる一番の方法**：腹黒メガネさんが自分のアカウントで Tunee を一通り操作して、各画面のスクリーンショットを `replica/screens/S01.png` のように保存すること。
- 利用規約の本文は読めていません。事業者のアカウントを使って競合サービスを作ることを禁じる条項があるかは未確認です。確認できるまでは、公開情報だけで進めます。

## Sources

| # | source | URL | notes |
| --- | --- | --- | --- |
| 1 | marketing site（ユーザー指定） | https://www.tunee.ai/ja/home/ai-music-agent | 403で読めず |
| 2 | marketing site（ユーザー指定） | https://www.tunee.ai/ja/home/ai-music | 403で読めず |
| 3 | 公式 music agent ページ | https://www.tunee.ai/music-agent | 検索要約のみ。会話を覚えていて同じ下書きを直せる、と紹介 |
| 4 | 公式 FAQ | https://tunee.ai/faq | 検索要約のみ。有料プランは商用利用可、無料プランは非商用でクレジット表記が必要 |
| 5 | 公式 コンテンツ利用規約 | https://tunee.ai/user-content-compliance | 検索要約のみ。有料プラン加入中に作った曲だけが所有権の対象 |
| 6 | 公式フォーラム（著作権FAQ） | https://forum.tunee.ai/t/tunee-copyright-commercial-use-copyright-certificate-faq/3396 | 生成した時点のプランで権利が決まる |
| 7 | 公式 顧客事例 | https://www.tunee.ai/customer-stories/how-to-create-music-without-knowing-music-theory | 左のチャットがプロンプトを書き、右のワークベンチに渡す画面構成 |
| 8 | 公式 顧客事例 | https://tunee.ai/customer-stories/ai-music-agent-revolute-music-production | 検索結果に出ただけで、内容は未確認 |
| 9 | レビュー（料金とクレジット） | https://www.musicseed.ai/reviews/tunee-ai-reviews | Free / Basic $18 / Plus $38 / Pro $89 |
| 10 | レビュー | https://enkiomv.ai/en/discover/tunee-ai-music-generator-review.html | 会話で聞き返して内容を詰める流れ |
| 11 | レビュー | https://www.neura.market/ai-tools-directory/music-generators/tunee-ai | 無料プランはクレジットカード不要 |
| 12 | レビュー | https://tuneradarai.com/tunee_ai_review_2026/ | |
| 13 | 日本語の紹介記事 | https://www.techno-edge.net/article/2025/08/24/4545.html | 2025年8月のベータ版時点。マスタリングとMVまで自動で作る |
| 14 | 日本語の紹介記事 | https://www.gamebusiness.jp/article/2025/08/25/24921.html | 上と同じ記事の転載 |
| 15 | 紹介ページ | https://tad.ai/ja/tunee-ai | MP3/WAV書き出し、ステム、商用は有料 |

## Core loop

チャットで「こんな曲がほしい」と伝えると、エージェントが聞き返しながら歌詞とスタイルの指示を自分で書き、音楽生成モデルに渡して曲を作る。ユーザーは言葉で修正を頼み（例：「パッドを温かく」「サビを短調に」）、同じ下書きが直っていく。気に入ったら商用利用できる形でダウンロードする。

## Screens

（確度：顧客事例の「左にチャット、右にワークベンチ」という記述からの推測。自分のアカウントで確認が必要）

| ID | screen | route / how to reach | purpose | key components | states seen |
| --- | --- | --- | --- | --- | --- |
| S01 | ホーム／新規作成 | `/` ログイン後 | 最初の依頼を入力する | 大きな入力欄、例の候補、ファイル添付、最近のプロジェクト | 空、入力中、添付あり（推測） |
| S02 | 作曲セッション（2ペイン） | S01で送信 | 会話しながら曲を作る中心画面 | 左：チャット（ユーザーとエージェントのメッセージ、選択肢ボタン）／右：ワークベンチ（歌詞、スタイル指示、生成中の曲カード、バージョン） | 生成待ち、生成中、完了、失敗、クレジット不足 |
| S03 | 曲の詳細／プレイヤー | S02の曲カード | 試聴とバージョンの比較 | 波形、再生・停止、シーク、歌詞の表示、バージョン切り替え、ダウンロード | 再生中、読み込み中、エラー |
| S04 | ダウンロード／書き出し | S03 | 形式を選んで保存する | MP3 / WAV の選択、ステムの選択、ライセンスの表示 | 無料プラン（制限あり）、有料プラン |
| S05 | ライブラリ（プロジェクト一覧） | ナビ | 過去のセッションと曲を開く | 一覧またはグリッド、検索、削除 | 空、一覧あり |
| S06 | 料金プラン／クレジット | ナビ、クレジット不足時 | プランを選び、残りクレジットを確認 | プラン表、クレジット残高、毎日の補充 | — |
| S07 | ログイン／新規登録 | 未ログイン時 | アカウント | メール、Googleログイン | エラー |
| S08 | アカウント設定 | ナビ | プラン、請求、退会 | — | — |

## Flows

```
F01 会話から1曲作る（中核）
    S01 依頼を入力 -> S02 エージェントが聞き返す（ジャンル、雰囲気、歌あり／なし、長さ、用途）
        -> エージェントが歌詞とスタイル指示を書いてワークベンチに出す -> 生成 -> 曲カード
    happy path clicks: 送信1回 + 聞き返しへの回答2〜3回 + 確定1回 = 約5回（推測）
    edge: 依頼が曖昧すぎる、生成の失敗やタイムアウト、クレジット不足、
          生成中にページを閉じる、不適切な歌詞や実在アーティストの真似を頼まれる

F02 言葉で修正する
    S02 「サビを短調に」「テンポを上げて」 -> エージェントが指示を書き換えて再生成 -> 新しいバージョン
    happy path clicks: 2（入力、送信）
    edge: 前のバージョンに戻したい、修正の意味が曖昧

F03 自分の歌詞で作る
    S02 歌詞を貼り付け -> エージェントがスタイルだけ提案 -> 生成
    edge: 歌詞が長すぎる、構成タグ（Verse/Chorus）がない

F04 参考を渡して作る
    S01 音声・動画・画像を添付 -> エージェントが雰囲気を読み取る -> 生成
    edge: ファイルが大きすぎる、形式が未対応、他人の著作物をそのまま複製しようとする

F05 書き出す
    S03 -> S04 形式を選ぶ -> ダウンロード
    edge: 無料プランは非商用のみ、ステムは処理に時間がかかる

F06 過去の曲を開く
    S05 -> S02（会話の続きから再開）
```

## Components

| component | variants | states | used on |
| --- | --- | --- | --- |
| Button | primary, secondary, ghost, danger | default, hover, focus, disabled, loading | all |
| Prompt input | 大（ホーム）、小（チャット欄） | 空、入力中、添付あり、送信中、無効 | S01, S02 |
| Chat message | ユーザー、エージェント、システム（エラー、クレジット） | 送信中、ストリーミング中、完了 | S02 |
| Quick reply chips | 単一選択、複数選択 | 選択、無効 | S02 |
| Track card | 生成中、完了、失敗 | 再生中、選択中 | S02, S05 |
| Audio player | ミニ、フル（波形つき） | 読み込み中、再生、一時停止、エラー | S02, S03 |
| Lyrics / style panel | 表示、編集 | 編集中、保存済み | S02 |
| Version switcher | v1, v2 ... | 現在、比較中 | S02, S03 |
| File drop zone | 音声、動画、画像 | ドラッグ中、アップロード中、エラー | S01, S02 |
| Credit badge | 残高、不足 | 通常、警告 | 全画面のヘッダー |
| Modal | ダウンロード、プラン変更、確認 | 開く、閉じる | S04, S06 |
| Toast | 成功、エラー | — | all |

## Inferred data model

```
User         id, email, plan (free | paid), credits, daily_refresh_at
             evidence: 料金プランとクレジットの説明（sources 9, 11）
             confidence: medium

Project      id, user_id, title, created_at, updated_at
             （1つの会話セッション = 1プロジェクト）
             evidence: 「会話を覚えていて同じ下書きを直す」（source 3）
             confidence: medium

Message      id, project_id, role (user | agent | system), content, attachments (json), created_at
             evidence: チャットUI（sources 7, 10）
             confidence: high

SongSpec     id, project_id, lyrics, style_prompt, genre, mood, bpm, vocal (bool), duration_s, model
             （エージェントが書いて生成モデルに渡す指示）
             evidence: 「左のチャットがプロンプトを書き、右のワークベンチに渡す」（source 7）
             confidence: medium

Track        id, project_id, spec_id, version, status (queued | generating | done | failed),
             audio_url, duration_s, plan_at_generation, created_at
             evidence: バージョンでの修正、権利は生成時のプランで決まる（sources 3, 6）
             confidence: medium（plan_at_generation は権利の記録に必要）

Stem         id, track_id, kind (vocals | drums | bass | other), audio_url
             evidence: ステム分離（sources 1, 15）
             confidence: medium

Attachment   id, message_id, kind (audio | video | image), url
             evidence: 参考ファイルのアップロード（sources 10, 13）
             confidence: medium

CreditLedger id, user_id, delta, reason (generate | stems | refresh | purchase), created_at
             confidence: guess
```

Relationships: User 1-n Project, Project 1-n Message, Project 1-n SongSpec, SongSpec 1-n Track, Track 1-n Stem, Message 1-n Attachment, User 1-n CreditLedger

## Feature matrix

See `features.csv`. Must: 12, should: 8, could: 5, skip: 7.

## Out of scope（作り直せない、または作り直すべきでない）

- **音楽生成モデルそのもの。** Tunee は Mureka、MiniMax、自社モデル TemPolor などのモデルを使っています。自作版では、商用利用できる規約の音楽生成APIを、腹黒メガネさん自身のキーで呼び出します。モデルを作るわけではありません。
- **Tunee の自社モデル TemPolor**：Tunee が持っているものです。
- **MV動画生成、AIキャラクター、リップシンク、モーションコントロール**：今回の範囲外です。
- **音声クローン**：範囲外です。本人以外の声を使うと法的なリスクが大きいです。
- **コミュニティ、フォーラム、公開ギャラリー**：これは Tunee のユーザーの集まりで、機能ではありません。
- **料金プランと課金**：自分の仕事用なので不要です。生成APIの使用量を記録するだけにします。
- **「著作権証明書」の発行**：Tunee 独自の仕組みです。

## Size

Screens 8（課金をやめるので実際に作るのは6）、flows 6、entities 8。

難しい部分：
1. **音楽生成APIの選定と非同期処理**：生成に数十秒から数分かかります。キュー、状態の確認、失敗時のやり直し、費用の管理が必要です。商用利用の規約もAPIごとに違うので、選ぶ前に確認が必要です。
2. **エージェントの会話設計**：聞き返し → 歌詞とスタイル指示の作成 → 修正の反映を、LLM（Claude API）のツール呼び出しで組み立てます。これが Tunee の一番の価値です。
3. **音声ファイルの扱い**：保存、配信、波形の表示、WAV書き出し、ステム分離（別のAPIか、オープンソースのモデル）。

Size: **M（数週間）**。課金をなくし、単一ユーザーにすれば、F01・F02・F05だけの最小版は週末から1週間ほど。
