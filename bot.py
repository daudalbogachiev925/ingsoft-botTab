import os
import json
import hashlib
import secrets
import sqlite3
from datetime import datetime
import telebot
from flask import Flask, request, jsonify

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
PORT = int(os.environ.get('PORT', 5000))
DB_PATH = 'ingsoft.db'

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        login TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        token TEXT,
        nickname TEXT,
        gender TEXT DEFAULT 'male',
        region TEXT,
        phone TEXT,
        full_name TEXT,
        telegram_id INTEGER,
        score INTEGER DEFAULT 0,
        energy INTEGER DEFAULT 500,
        max_energy INTEGER DEFAULT 500,
        multiplier INTEGER DEFAULT 1,
        level INTEGER DEFAULT 1,
        total_taps INTEGER DEFAULT 0,
        is_balance INTEGER DEFAULT 0,
        daily_tap_limit INTEGER DEFAULT 20000,
        taps_today INTEGER DEFAULT 0,
        last_tap_date TEXT,
        sub_was_subscribed INTEGER DEFAULT 0,
        sub_was_punished INTEGER DEFAULT 0,
        is_tasks_done TEXT DEFAULT '[]',
        claimed_quests TEXT DEFAULT '[]',
        claimed_promos TEXT DEFAULT '[]',
        upgrades TEXT DEFAULT '{}',
        unlimited_until INTEGER DEFAULT 0,
        is_boost_mult_until INTEGER DEFAULT 0,
        is_auto_tap_until INTEGER DEFAULT 0,
        autotap_level INTEGER DEFAULT 0,
        passive_income INTEGER DEFAULT 0,
        wallet_balance REAL DEFAULT 0,
        wallet_total REAL DEFAULT 0,
        earned_promocodes TEXT DEFAULT '[]',
        created_at TEXT,
        last_updated TEXT
    )''')
    conn.commit()
    conn.close()


init_db()


def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()


def generate_token():
    return secrets.token_hex(32)


@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        login = (data.get('login') or '').strip().lower()
        password = data.get('password') or ''
        nickname = (data.get('nickname') or '').strip()
        gender = data.get('gender') or 'male'
        region = (data.get('region') or '').strip()
        phone = (data.get('phone') or '').strip()
        full_name = (data.get('full_name') or '').strip()

        if len(login) < 3:
            return jsonify({"error": "Логин минимум 3 символа"}), 400
        if len(password) < 6:
            return jsonify({"error": "Пароль минимум 6 символов"}), 400
        if len(nickname) < 2:
            return jsonify({"error": "Никнейм минимум 2 символа"}), 400
        if not region:
            return jsonify({"error": "Выбери регион"}), 400
        if len(phone) < 10:
            return jsonify({"error": "Введи телефон"}), 400
        if len(full_name) < 5:
            return jsonify({"error": "Введи ФИО"}), 400
        if gender not in ['male', 'female']:
            return jsonify({"error": "Неверный пол"}), 400

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE login = ?', (login,))
        if c.fetchone():
            conn.close()
            return jsonify({"error": "Логин уже занят"}), 400

        password_hash = hash_password(password)
        token = generate_token()
        now = datetime.now().isoformat()

        c.execute('''INSERT INTO users 
            (login, password_hash, token, nickname, gender, region, phone, full_name, created_at, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (login, password_hash, token, nickname, gender, region, phone, full_name, now, now))
        conn.commit()
        user_id = c.lastrowid
        conn.close()

        return jsonify({
            "success": True,
            "token": token,
            "user_id": user_id,
            "login": login,
            "nickname": nickname,
            "gender": gender,
            "region": region,
            "phone": phone,
            "full_name": full_name
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/login', methods=['POST'])
def login_route():
    try:
        data = request.get_json()
        login = (data.get('login') or '').strip().lower()
        password = data.get('password') or ''

        if not login or not password:
            return jsonify({"error": "Введи логин и пароль"}), 400

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        password_hash = hash_password(password)
        c.execute('SELECT * FROM users WHERE login = ? AND password_hash = ?', (login, password_hash))
        row = c.fetchone()

        if not row:
            conn.close()
            return jsonify({"error": "Неверный логин или пароль"}), 401

        new_token = generate_token()
        c.execute('UPDATE users SET token = ? WHERE login = ?', (new_token, login))
        conn.commit()
        conn.close()

        columns = ['id','login','password_hash','token','nickname','gender','region','phone',
                   'full_name','telegram_id','score','energy','max_energy','multiplier','level',
                   'total_taps','is_balance','daily_tap_limit','taps_today','last_tap_date',
                   'sub_was_subscribed','sub_was_punished','is_tasks_done','claimed_quests',
                   'claimed_promos','upgrades','unlimited_until','is_boost_mult_until',
                   'is_auto_tap_until','autotap_level','passive_income','wallet_balance',
                   'wallet_total','earned_promocodes','created_at','last_updated']
        user_data = dict(zip(columns, row))
        user_data['token'] = new_token
        user_data.pop('password_hash', None)

        user_data['is_tasks_done'] = json.loads(user_data['is_tasks_done'] or '[]')
        user_data['claimed_quests'] = json.loads(user_data['claimed_quests'] or '[]')
        user_data['claimed_promos'] = json.loads(user_data['claimed_promos'] or '[]')
        user_data['upgrades'] = json.loads(user_data['upgrades'] or '{}')
        user_data['earned_promocodes'] = json.loads(user_data['earned_promocodes'] or '[]')
        user_data['sub_was_subscribed'] = bool(user_data['sub_was_subscribed'])
        user_data['sub_was_punished'] = bool(user_data['sub_was_punished'])

        return jsonify({"success": True, "user": user_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/get-progress', methods=['GET'])
def get_progress():
    try:
        token = request.args.get('token', '')
        if not token:
            return jsonify({"error": "token missing"}), 400
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE token = ?', (token,))
        row = c.fetchone()
        conn.close()

        if not row:
            return jsonify({"found": False})

        columns = ['id','login','password_hash','token','nickname','gender','region','phone',
                   'full_name','telegram_id','score','energy','max_energy','multiplier','level',
                   'total_taps','is_balance','daily_tap_limit','taps_today','last_tap_date',
                   'sub_was_subscribed','sub_was_punished','is_tasks_done','claimed_quests',
                   'claimed_promos','upgrades','unlimited_until','is_boost_mult_until',
                   'is_auto_tap_until','autotap_level','passive_income','wallet_balance',
                   'wallet_total','earned_promocodes','created_at','last_updated']
        u = dict(zip(columns, row))
        u.pop('password_hash', None)
        u['is_tasks_done'] = json.loads(u['is_tasks_done'] or '[]')
        u['claimed_quests'] = json.loads(u['claimed_quests'] or '[]')
        u['claimed_promos'] = json.loads(u['claimed_promos'] or '[]')
        u['upgrades'] = json.loads(u['upgrades'] or '{}')
        u['earned_promocodes'] = json.loads(u['earned_promocodes'] or '[]')
        u['sub_was_subscribed'] = bool(u['sub_was_subscribed'])
        u['sub_was_punished'] = bool(u['sub_was_punished'])
        return jsonify({"found": True, "user": u})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/save-progress', methods=['POST'])
def save_progress():
    try:
        data = request.get_json()
        token = data.get('token')
        if not token:
            return jsonify({"error": "token missing"}), 400

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE token = ?', (token,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Неверный токен"}), 401
        user_id = row[0]
        now = datetime.now().isoformat()

        c.execute('''UPDATE users SET
            score=?, energy=?, max_energy=?, multiplier=?, level=?, total_taps=?,
            is_balance=?, daily_tap_limit=?, taps_today=?, last_tap_date=?,
            sub_was_subscribed=?, sub_was_punished=?, is_tasks_done=?, claimed_quests=?,
            claimed_promos=?, upgrades=?, unlimited_until=?, is_boost_mult_until=?,
            is_auto_tap_until=?, autotap_level=?, passive_income=?, wallet_balance=?,
            wallet_total=?, earned_promocodes=?, last_updated=?
            WHERE id=?''',
            (data.get('score',0), data.get('energy',500), data.get('max_energy',500),
             data.get('multiplier',1), data.get('level',1), data.get('total_taps',0),
             data.get('is_balance',0), data.get('daily_tap_limit',20000),
             data.get('taps_today',0), data.get('last_tap_date',''),
             1 if data.get('sub_was_subscribed') else 0,
             1 if data.get('sub_was_punished') else 0,
             json.dumps(data.get('is_tasks_done',[])),
             json.dumps(data.get('claimed_quests',[])),
             json.dumps(data.get('claimed_promos',[])),
             json.dumps(data.get('upgrades',{})),
             data.get('unlimited_until',0), data.get('is_boost_mult_until',0),
             data.get('is_auto_tap_until',0), data.get('autotap_level',0),
             data.get('passive_income',0), data.get('wallet_balance',0),
             data.get('wallet_total',0),
             json.dumps(data.get('earned_promocodes',[])), now, user_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        return jsonify({"subscribed": is_subscribed, "status": status})
    except telebot.apihelper.ApiTelegramException as e:
        if 'user not found' in str(e).lower() or 'participant' in str(e).lower():
            return jsonify({"subscribed": False, "status": "left"})
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/')
def index():
    return jsonify({"status": "ok"})


@app.route('/ping')
def ping():
    return "pong"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
