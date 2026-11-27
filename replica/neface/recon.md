# Recon map: Face Swap Video & AIVideo-NeFace（Web で作り直し）

Scope: 動画の顔入れ替えだけ。自分の顔写真を登録 → テンプレート動画か自分の動画を選ぶ → 顔を入れ替える → AIで作ったという表示つきで書き出す。写真の入れ替え、AI動画生成、AI音楽、課金の仕組みは範囲外。
For: 腹黒メガネさん自身の仕事用（自分のコンテンツ）。一般公開も販売もしない。
Date: 2026-11-27

## 守るルール（この作り直しの前提）

元のアプリより厳しくします。

1. **入れ替えに使える顔は、登録した顔だけ。** 登録できるのは次の2つです。
   - 自分の顔（`consent_type = self`）
   - 本人から書面で同意をもらった人の顔（`consent_type = written`）。同意書のファイル、相手の名前、日付、使ってよい範囲、期限を記録します。
   - 有名人、公人、子ども（18歳未満）の顔は登録できません。
2. **元にする動画も、権利のあるものだけ。** 自分で撮った動画か、写っている人の同意（モデルリリース）がある素材だけにします。他人の動画から顔だけを差し替えるのも、映っている人の権利に関わるためです。
3. **性的な内容、なりすまし、だます目的のものは作らない。** 入力の動画と顔写真を自動で検査し、該当すれば止めます。
4. **書き出す動画には必ず「AIで作った」表示を入れる。** 画面に見える透かしと、ファイルのメタデータ（C2PA の Content Credentials）の両方です。透かしを外す設定は作りません。
5. **同意は取り消せる。** 同意を取り消された顔は、それ以降は使えなくし、その顔で作った動画は一覧で分かるようにします。

背景：
- 米国では TAKE IT DOWN Act により、本人の同意がない性的なディープフェイクの公開が犯罪になっています。プラットフォーム側の削除義務も2026年5月から始まっています。
- EU AI Act の第50条（ディープフェイクの開示義務）は2026年8月から適用されています。
- 2026年7月には、サンフランシスコ市検事が Apple と Google に顔入れ替えアプリ13本の削除を求め、実際に削除された例があります。
- 日本でも、他人の顔を無断で使えば、肖像権やパブリシティ権の侵害、名誉毀損になり得ます。

この節の法律の情報は二次情報（下の sources 9〜12）です。法的な助言ではありません。仕事で公開する前に、専門家に確認してください。

## 調査の限界

- App Store と Google Play のページは、この環境のネットワーク設定で遮断されていて読めませんでした。内容はすべて Web検索の要約から取っています。
- 「AI Generation 01」はアプリの名前ではありません。App Store の**アプリ内課金の項目名**です（「AI Generation」という名前の項目が価格違いで複数ある）。アプリ名は、iOS では「AI video&face swap-NeFace」、Android では「Face Swap Video&AIVideo-NeFace」です。
- Android 版のパッケージ名は `faceswap.deepfake.aivideo` です。
- 画面の構成は、同じ種類のアプリによくある形からの推測です。確度は低めです。
- スクリーンショットはありません。腹黒メガネさんが自分の端末で操作して `replica/neface/screens/` に保存してくれれば、画面の一覧を直します。ただし、そのときも他人の顔は使わないでください。

## Sources

| # | source | URL | notes |
| --- | --- | --- | --- |
| 1 | Google Play | https://play.google.com/store/apps/details?id=faceswap.deepfake.aivideo | 遮断で読めず。検索の要約のみ。評価3.8（約570〜614件）、5万DL以上 |
| 2 | Google Play（別言語） | https://play.google.com/store/apps/details?id=faceswap.deepfake.aivideo&hl=en_IE | 2〜4人の同時入れ替え、テンプレート、9:16 と 16:9、HD書き出し |
| 3 | App Store | https://apps.apple.com/us/app/-/id6751527986 | 遮断で読めず。アプリ内課金に「AI Generation」の項目が複数ある |
| 4 | 開発元の他のアプリ | https://play.google.com/store/apps/dev?id=8817616707006284594&hl=en_IE | 開発元の名前は「AI faceswap video&AI video&AI music」 |
| 5 | AppBrain | https://www.appbrain.com/app/face-swap-video-aivideo-neface/faceswap.deepfake.aivideo | インストール数の数字が他と食い違う |
| 6 | SourceForge | https://sourceforge.net/app/face-swap-videoaivideo-neface/android/ | |
| 7 | SourceForge | https://sourceforge.net/app/face-swap-videoaivideo-neface/ | 週額か年額のサブスク、動画にはコイン（クレジット）が必要という口コミ |
| 8 | 同じ種類の機能の例 | https://www.mage.space/video-face-swap | 入力は「動画」と「顔写真1枚」の2つ |
| 9 | 法律と規制（二次情報） | https://nation.ai/ai-face-swap-free/ | TAKE IT DOWN Act、EU AI Act 第50条 |
| 10 | 法律と規制（二次情報） | https://www.morphing.net/blog/face-morph-vs-face-swap-vs-deepfake | 2026年のルール |
| 11 | 同意のチェックリスト | https://deepswapai.com/guides/face-swap-privacy | |
| 12 | 経緯 | https://en.wikipedia.org/wiki/Grok_sexual_deepfake_scandal | 性的ディープフェイクの問題 |

## Core loop

自分の顔写真を1枚登録しておき、テンプレート動画か自分の動画を選ぶと、動画の中の顔が自分の顔に入れ替わる。それを縦（9:16）か横（16:9）のHDで書き出す。

## Screens

| ID | screen | route / how to reach | purpose | key components | states seen |
| --- | --- | --- | --- | --- | --- |
| S01 | ホーム | `/` | テンプレートを選ぶか、自分の動画をアップロードする | テンプレートのグリッド（カテゴリのタブ、縦／横）、アップロードボタン、最近の作品 | 空、読み込み中、一覧あり |
| S02 | テンプレートの詳細 | S01のカード | 元にする動画を確認する | 動画プレビュー、映っている顔の数、「この動画を使う」ボタン、素材の権利の表示 | 再生中 |
| S03 | 動画のアップロード | S01 | 自分の動画を使う | ドロップ領域、長さとサイズの上限、権利の確認チェックボックス | アップロード中、形式が未対応、長すぎる、顔が見つからない |
| S04 | 顔の対応づけ | S02かS03の次 | 動画のどの顔を、どの登録済みの顔にするか決める | 検出された顔の一覧（2〜4人）、登録済みの顔の選択 | 顔が0人、1人、複数 |
| S05 | 顔の登録（顔ライブラリ） | ナビ、S04から | 入れ替えに使える顔を登録する | 写真のアップロード、同意の種類（自分／書面同意）、同意書の添付、名前、期限、範囲 | 写真が不適切（顔が写っていない、複数写っている）、同意書なし、期限切れ、取り消し済み |
| S06 | 処理中 | S04で実行 | 完了を待つ | 進行状況、キャンセル | 待機中、処理中、失敗、安全チェックで停止 |
| S07 | 結果 | S06の完了 | 確認して書き出す | 前後の比較プレビュー、AI表示の確認、ダウンロード（9:16 / 16:9、HD） | 完了、書き出し中 |
| S08 | 作品一覧 | ナビ | 過去の結果 | グリッド、使った顔、削除 | 空、一覧あり、同意が取り消された顔を使った作品 |
| S09 | ログイン | 未ログイン時 | 自分専用 | パスワード | エラー |

元のアプリにある課金画面（週額、年額、コイン）は作りません。

## Flows

```
F01 テンプレート動画で顔を入れ替える（中核）
    S01 テンプレートを選ぶ -> S02 確認 -> S04 顔を割り当てる -> S06 処理中 -> S07 書き出す
    happy path clicks: 5（選ぶ、使う、顔を選ぶ、実行、ダウンロード）
    edge: 登録済みの顔がない（S05へ）、テンプレートの顔の数と合わない、処理の失敗、
          安全チェックで停止、処理中に画面を閉じる

F02 自分の動画で入れ替える
    S01 -> S03 アップロードと権利の確認 -> S04 -> S06 -> S07
    edge: 顔が見つからない、横顔や暗い場面で顔を見失う、長すぎる、大きすぎる

F03 顔を登録する
    S05 写真をアップロード -> 同意の種類を選ぶ -> （書面同意なら）同意書、名前、期限、範囲 -> 保存
    edge: 写真に顔が写っていない、複数の顔が写っている、未成年に見える（登録させない）、
          有名人に似ている（登録させない）、期限切れ

F04 複数の顔を同時に入れ替える（2〜4人）
    S04 で顔ごとに割り当てる。割り当てる顔それぞれに有効な同意が必要。

F05 同意を取り消す
    S05 取り消す -> その顔は以後使えない -> S08 でその顔を使った作品に印がつく
```

## Components

| component | variants | states | used on |
| --- | --- | --- | --- |
| Button | primary, secondary, ghost, danger | default, hover, focus, disabled, loading | all |
| Template card | 縦、横 | 読み込み中、ホバーで再生、選択中 | S01 |
| Video player | プレビュー、前後の比較 | 読み込み中、再生、一時停止、エラー | S02, S07 |
| Upload drop zone | 動画、顔写真、同意書 | ドラッグ中、アップロード中、エラー | S03, S05 |
| Face chip | 検出された顔、登録済みの顔 | 割り当て済み、未割り当て、同意が無効 | S04, S05, S08 |
| Consent form | 自分、書面同意 | 入力中、不備あり、保存済み、期限切れ、取り消し済み | S05 |
| Progress bar | 確定した進行度、不確定 | 処理中、失敗、停止 | S06 |
| AI label badge | 透かしのプレビュー | — | S07 |
| Aspect toggle | 9:16、16:9 | 選択 | S01, S07 |
| Toast | 成功、エラー | — | all |

## Inferred data model

```
User           id, email, password_hash
               confidence: high（自分専用）

Face           id, user_id, display_name, image_key, embedding (vector),
               consent_type (self | written), consent_doc_key, consent_scope, consent_expires_at,
               revoked_at, created_at
               evidence: 元のアプリは「自分の写真をアップロード」（source 2）。同意の欄はこの作り直しで追加
               confidence: high（同意の欄は必須にする）

SourceVideo    id, user_id, kind (template | upload), video_key, duration_s, aspect (9:16 | 16:9),
               detected_faces (json), rights_note, created_at
               evidence: テンプレート、自分の動画、縦横（source 2）
               confidence: medium

Template       id, title, category, source_video_id, license_note
               evidence: テンプレート（source 2）
               confidence: medium（テンプレートは自分で用意する。下の Out of scope）

SwapJob        id, user_id, source_video_id, status (queued | processing | done | failed | blocked),
               safety_result (json), provider, cost, created_at
               confidence: medium

SwapMapping    id, job_id, detected_face_index, face_id
               evidence: 2〜4人の同時入れ替え（source 2）
               confidence: medium

Output         id, job_id, video_key, aspect, resolution, watermark (bool, 常に true), c2pa_manifest_key
               evidence: HD書き出し（source 2）。AI表示はこの作り直しで追加
               confidence: medium
```

Relationships: User 1-n Face, User 1-n SourceVideo, Template 1-1 SourceVideo, SwapJob n-1 SourceVideo, SwapJob 1-n SwapMapping n-1 Face, SwapJob 1-n Output

## Feature matrix

See `features.csv`. Must: 13, should: 6, could: 3, skip: 6.

## Out of scope（作り直せない、または作り直すべきでない）

- **元のアプリのテンプレート動画。** NeFace の素材であり、映っている人の権利も関わります。テンプレートは、自分で撮った動画か、モデルリリースつきのストック素材で自分で用意します。
- **他人の顔を自由に使う機能。** 元のアプリでは使えますが、この作り直しでは作りません。
- **透かしを消す機能。** 元のアプリではおそらく有料で外せますが、作りません。
- **写真の入れ替え、AI動画生成、AI音楽。** 今回は選ばなかった範囲です。AI音楽は Tunee の作り直しのほうで作ります。
- **週額・年額のサブスク、コイン課金。** 自分の仕事用なので不要です。
- **元のアプリの顔入れ替えモデル。** 外部のAPIか、ライセンスを確認したオープンソースのモデルで代わりにします。

## Size

Screens 9、flows 5、entities 7。

難しい部分：
1. **入れ替えの品質と処理方法。** 動画のすべてのフレームで顔を追いかけて、横顔、暗い場面、隠れた顔でも崩れないようにする必要があります。方法は2つです。
   - 外部の顔入れ替えAPIを使う。費用がかかり、顔写真を外部に送ることになります。
   - オープンソースのモデルを自分のGPUで動かす。**よく使われるモデルの中には「研究用のみ・商用不可」のライセンスがあるので、使う前に必ず確認が必要です。**
2. **同意と安全チェックの仕組み。** 同意の記録と取り消し、未成年・有名人・性的な内容の検出、AI表示（透かしと C2PA）を、入れ替えより前の段階で確実に止める設計にします。
3. **動画の扱い。** 大きいファイルのアップロード、GPUの処理待ち、書き出し（ffmpeg）、保存の費用。

Size: **M（数週間）**。外部APIを使い、1人用にすれば、F01・F03だけの最小版は1〜2週間ほど。
