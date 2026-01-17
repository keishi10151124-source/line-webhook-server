# LINE Webhook Server

LINE公式アカウントにメッセージを送信したユーザーのIDを自動的に記録するWebhookサーバーです。

## 機能

- ユーザーからのメッセージ受信時にユーザーIDを自動記録
- 登録ユーザーの一覧表示
- ユーザー名での検索

## APIエンドポイント

| エンドポイント | メソッド | 説明 |
|--------------|---------|------|
| `/` | GET | サーバー状態確認 |
| `/webhook` | POST | LINE Webhookエンドポイント |
| `/users` | GET | 全ユーザー一覧 |
| `/users/<user_id>` | GET | 特定ユーザー情報 |
| `/search?name=xxx` | GET | 名前でユーザー検索 |

## デプロイ

### Renderへのデプロイ

1. このリポジトリをフォークまたはクローン
2. [Render](https://render.com/)でアカウント作成
3. 「New +」→「Web Service」を選択
4. GitHubリポジトリを接続
5. 自動的にデプロイされます

## LINE Developersでの設定

1. [LINE Developers Console](https://developers.line.biz/console/)にアクセス
2. Messaging APIチャネルを選択
3. Webhook URLに `https://your-app.onrender.com/webhook` を設定
4. Webhookの利用をオンに設定

## ライセンス

MIT
