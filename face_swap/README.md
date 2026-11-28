# face-swap

自分の顔を、自分の動画（または権利のある動画）に入れ替える、自分専用のWebアプリです。
NeFace の中核機能を、元のアプリより厳しいルールで作り直したものです（設計：`../replica/neface/`）。

## 守るルール

コードとデータベースの制約で強制しています。

- 使える顔は本人の顔だけです。最初の登録はカメラ撮影と生体確認で行います。あとから追加する写真は、その顔と同じ人だと確認できたものだけ保存します。
- 動画と写真は、入れ替えの前に安全チェックを通します（性的な内容、18歳未満に見える人、有名人やニュースの映像）。チェックが失敗したり、エラーになったりした場合も「止める」扱いです。
- 書き出す動画には、必ず「AI-GENERATED」の透かしと C2PA の Content Credentials が入ります。外す設定はありません。

## 手元で動かす（開発モード）

```bash
cd face_swap
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash scripts/fetch_models.sh              # 顔のモデル（YuNet: MIT, SFace: Apache 2.0）
.venv/bin/python scripts/make_c2pa_cert.py # 自分用の C2PA 証明書を secrets/ に作る
.venv/bin/python scripts/hash_password.py  # 出てきた値を OWNER_PASSWORD_HASH に
export SECRET_KEY=dev OWNER_EMAIL=you@example.com OWNER_PASSWORD_HASH='...' \
       SAFETY=dev_allow FACESWAP_PROVIDER=dev_passthrough RUN_JOBS_INLINE=1
.venv/bin/flask --app wsgi run
```

開発モードでは、顔は実際には入れ替わりません。安全チェックも省略します。画面の上に、そのことが表示されます。
`APP_ENV=production` では、この2つの設定では起動しません。

## テスト

```bash
.venv/bin/python -m pytest -q
TEST_DATABASE_URL=postgresql://... .venv/bin/python -m pytest -q   # Postgres でも確認する
```

## 本番（Render）

`render.yaml` に、Web、Worker、Postgres の3つを定義しています。値はダッシュボードで入れてください。

| 変数 | 中身 |
| --- | --- |
| `OWNER_EMAIL` / `OWNER_PASSWORD_HASH` | ログインに使うメールアドレスとパスワード（パスワードは `scripts/hash_password.py` で作ったハッシュ） |
| `ANTHROPIC_API_KEY` | 安全チェックに使う Claude API のキー |
| `FACESWAP_PROVIDER` / `FACESWAP_PRICE_PER_SECOND_USD` | 顔入れ替えAPI（アダプターはまだ作っていません）と、1秒あたりの料金 |
| `R2_*` | Cloudflare R2 の接続情報 |
| Secret Files | `c2pa_chain.pem` と `c2pa_key.pem` |

## まだできていないこと

- 本物の顔入れ替えAPIのアダプター（どのAPIを使うかが未決定）
- 本物の顔モデル、本物の Claude API、ブラウザ側の生体確認を使った動作確認
