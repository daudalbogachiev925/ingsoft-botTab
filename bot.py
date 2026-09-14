import os
import telebot
from flask import Flask, request, jsonify

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
PORT = int(os.environ.get('PORT', 5000))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/check-sub', methods=['GET'])
def check_sub():
    try:
        user_id = int(request.args.get('user_id', 0))
        channel = request.args.get('channel', '')
        if not user_id or not channel:
            return jsonify({"error": "user_id or channel missing"}), 400
        chat_member = bot.get_chat_member('@' + channel, user_id)
        status = chat_member.status
        is_subscribed = status in ['creator', 'administrator', 'member']
        return jsonify({
            "subscribed": is_subscribed,
            "status": status,
            "user_id": user_id,
            "channel": channel
        })
    except telebot.apihelper.ApiTelegramException as e:
        if 'user not found' in str(e).lower() or 'participant' in str(e).lower():
            return jsonify({"subscribed": False, "status": "left"})
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    return jsonify({"status": "ok", "bot": "IngSoft Check Bot"})

@app.route('/ping')
def ping():
    return "pong"

if __name__ == '__main__':
    print(f"Starting server on port {PORT}...")
    app.run(host='0.0.0.0', port=PORT)
