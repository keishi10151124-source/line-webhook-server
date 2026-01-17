"""
LINE Webhook Server
ユーザーからのメッセージを受信し、ユーザーIDと表示名を記録するサーバー
"""

from flask import Flask, request, jsonify
import json
import os
from datetime import datetime
import hashlib
import hmac
import base64

app = Flask(__name__)

# ユーザー情報を保存するJSONファイル
USERS_FILE = '/home/ubuntu/line-webhook-server/users.json'

def load_users():
    """保存されているユーザー情報を読み込む"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(users):
    """ユーザー情報を保存する"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def add_or_update_user(user_id, display_name=None, message=None):
    """ユーザー情報を追加または更新する"""
    users = load_users()
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if user_id in users:
        # 既存ユーザーの更新
        users[user_id]['last_message_at'] = now
        users[user_id]['message_count'] = users[user_id].get('message_count', 0) + 1
        if display_name:
            users[user_id]['display_name'] = display_name
        if message:
            users[user_id]['last_message'] = message
    else:
        # 新規ユーザーの追加
        users[user_id] = {
            'user_id': user_id,
            'display_name': display_name or 'Unknown',
            'first_message_at': now,
            'last_message_at': now,
            'message_count': 1,
            'last_message': message or ''
        }
    
    save_users(users)
    return users[user_id]

@app.route('/', methods=['GET'])
def index():
    """ヘルスチェック用エンドポイント"""
    return jsonify({
        'status': 'ok',
        'message': 'LINE Webhook Server is running',
        'endpoints': {
            '/webhook': 'POST - LINE Webhook endpoint',
            '/users': 'GET - List all registered users',
            '/users/<user_id>': 'GET - Get specific user info'
        }
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """LINE Webhookエンドポイント"""
    try:
        # リクエストボディを取得
        body = request.get_data(as_text=True)
        
        # JSONとしてパース
        events = json.loads(body)
        
        print(f"[{datetime.now()}] Received webhook: {body[:500]}")
        
        # eventsがリストの場合とオブジェクトの場合に対応
        if isinstance(events, dict) and 'events' in events:
            event_list = events['events']
        elif isinstance(events, list):
            event_list = events
        else:
            event_list = [events]
        
        for event in event_list:
            event_type = event.get('type', '')
            
            # ユーザーIDを取得
            source = event.get('source', {})
            user_id = source.get('userId', '')
            
            if not user_id:
                continue
            
            # メッセージイベントの処理
            if event_type == 'message':
                message = event.get('message', {})
                message_type = message.get('type', '')
                message_text = message.get('text', '') if message_type == 'text' else f'[{message_type}]'
                
                # ユーザー情報を記録
                user_info = add_or_update_user(
                    user_id=user_id,
                    display_name=None,  # プロフィールAPIで別途取得が必要
                    message=message_text
                )
                
                print(f"[{datetime.now()}] User registered/updated: {user_id}")
                print(f"  Message: {message_text}")
            
            # フォローイベントの処理
            elif event_type == 'follow':
                user_info = add_or_update_user(
                    user_id=user_id,
                    message='[Followed]'
                )
                print(f"[{datetime.now()}] New follower: {user_id}")
            
            # その他のイベント
            else:
                add_or_update_user(
                    user_id=user_id,
                    message=f'[{event_type}]'
                )
                print(f"[{datetime.now()}] Event {event_type} from: {user_id}")
        
        return jsonify({'status': 'ok'})
    
    except Exception as e:
        print(f"[{datetime.now()}] Error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/users', methods=['GET'])
def list_users():
    """登録されている全ユーザーを一覧表示"""
    users = load_users()
    return jsonify({
        'total_users': len(users),
        'users': list(users.values())
    })

@app.route('/users/<user_id>', methods=['GET'])
def get_user(user_id):
    """特定のユーザー情報を取得"""
    users = load_users()
    if user_id in users:
        return jsonify(users[user_id])
    return jsonify({'error': 'User not found'}), 404

@app.route('/search', methods=['GET'])
def search_users():
    """ユーザーを名前で検索"""
    query = request.args.get('name', '').lower()
    if not query:
        return jsonify({'error': 'Please provide a name parameter'}), 400
    
    users = load_users()
    results = []
    for user in users.values():
        display_name = user.get('display_name', '').lower()
        if query in display_name:
            results.append(user)
    
    return jsonify({
        'query': query,
        'results': results,
        'count': len(results)
    })

if __name__ == '__main__':
    # 初期ユーザーファイルを作成
    if not os.path.exists(USERS_FILE):
        save_users({})
    
    print("=" * 50)
    print("LINE Webhook Server Starting...")
    print("=" * 50)
    print(f"Users file: {USERS_FILE}")
    print("Endpoints:")
    print("  GET  /         - Health check")
    print("  POST /webhook  - LINE Webhook")
    print("  GET  /users    - List all users")
    print("  GET  /search?name=xxx - Search users by name")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
