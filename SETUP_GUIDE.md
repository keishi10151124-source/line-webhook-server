# LINE Webhook サーバー設定ガイド

## 概要

このWebhookサーバーは、LINE公式アカウントにメッセージを送信したユーザーのIDを自動的に記録します。
記録されたユーザーIDを使用して、特定のユーザーに個別メッセージを送信できるようになります。

## Webhook URL

```
https://5000-ir6bdlp8z9l05uaq7o45l-432e3ffd.sg1.manus.computer/webhook
```

---

## LINE Developersでの設定手順

### Step 1: LINE Developersコンソールにアクセス

1. [LINE Developers Console](https://developers.line.biz/console/) にアクセス
2. LINEアカウントでログイン

### Step 2: チャネル設定を開く

1. 対象のプロバイダーを選択
2. 対象の **Messaging API チャネル** を選択

### Step 3: Webhook URLを設定

1. 「Messaging API設定」タブを開く
2. 「Webhook設定」セクションを見つける
3. 「Webhook URL」に以下のURLを入力：

```
https://5000-ir6bdlp8z9l05uaq7o45l-432e3ffd.sg1.manus.computer/webhook
```

4. 「更新」ボタンをクリック
5. 「検証」ボタンをクリックして接続を確認（「成功」と表示されればOK）

### Step 4: Webhookの使用を有効化

1. 「Webhookの利用」を **オン** に切り替え

### Step 5: 応答設定（推奨）

1. 「LINE Official Account Manager」リンクをクリック
2. 「応答設定」を開く
3. 以下の設定を推奨：
   - 応答メッセージ: オフ（または必要に応じてオン）
   - Webhook: オン

---

## 動作確認

### 1. ユーザーからメッセージを受信

Yuriko Joさん（または他のユーザー）に、LINE公式アカウントにメッセージを送ってもらいます。

### 2. 登録されたユーザーを確認

以下のURLにアクセスして、記録されたユーザーを確認：

```
https://5000-ir6bdlp8z9l05uaq7o45l-432e3ffd.sg1.manus.computer/users
```

### 3. ユーザーIDを取得

表示されたユーザー一覧から、対象ユーザーの `user_id` をコピーします。

---

## APIエンドポイント

| エンドポイント | メソッド | 説明 |
|--------------|---------|------|
| `/` | GET | サーバー状態確認 |
| `/webhook` | POST | LINE Webhookエンドポイント |
| `/users` | GET | 全ユーザー一覧 |
| `/users/<user_id>` | GET | 特定ユーザー情報 |
| `/search?name=xxx` | GET | 名前でユーザー検索 |

---

## 注意事項

- このサーバーは一時的な公開URLを使用しています
- サンドボックス環境が停止すると、URLは無効になります
- 本番環境では、永続的なサーバーでの運用を推奨します
