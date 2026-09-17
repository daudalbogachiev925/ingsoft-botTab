import os
import time
import json
import sqlite3
import random
import string
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS

# ============================================================
#  INGSOFT TAP — BACKEND
# ============================================================

app = Flask(__name__)
CORS(app)

# --- Путь к БД (Bothost хранит в /app/data) ---
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
DB_PATH = os.path.join(DATA_DIR, 'ingsoft.db')

# --- Параметры ---
SUB_REWARD = 50
SUB_PENALTY = 500
ONLINE_WINDOW_MS = 5 * 60 * 1000  # 5 минут = онлайн


# ============================================================
#  ИНИЦИАЛИЗАЦИЯ БД
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            token TEXT UNIQUE,
            nickname TEXT,
            gender TEXT DEFAULT 'male',
            phone TEXT,
            region TEXT,
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
            avatar_data TEXT,
            referrer_nickname TEXT,
            referrer_id INTEGER,
            last_seen INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)

    # Добавляем столбцы если их нет (миграция)
    for col, ddl in [
        ('last_seen', 'INTEGER DEFAULT 0'),
        ('avatar_data', 'TEXT'),
        ('referrer_nickname', 'TEXT'),
        ('referrer_id', 'INTEGER'),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            print(f"[MIGRATION] добавлен столбец {col}")
        except Exception:
            pass

    conn.commit()
    conn.close()
    print("[DB] Инициализация завершена")


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def generate_token():
    return secrets.token_urlsafe(32)


# ============================================================
#  АВТОРИЗАЦИЯ
# ============================================================
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    login = (data.get('login') or '').strip()
    password = data.get('password') or ''
    nickname = (data.get('nickname') or '').strip()
    gender = data.get('gender') or 'male'
    phone = data.get('phone') or ''
    region = data.get('region') or ''
    full_name = data.get('full_name') or ''
    telegram_id = data.get('telegram_id')
    ref_nick = data.get('referrer_nickname')
    ref_id = data.get('referrer_id')

    if len(login) < 3:
        return jsonify({'error': 'Логин минимум 3 символа'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Пароль минимум 6 символов'}), 400
    if len(nickname) < 2:
        return jsonify({'error': 'Ник минимум 2 символа'}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO users
              (login, password, nickname, gender, phone, region, full_name,
               telegram_id, referrer_nickname, referrer_id,
               energy, max_energy, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 500, 500, ?, ?)
        """, (
            login, hash_password(password), nickname, gender, phone, region, full_name,
            telegram_id, ref_nick, ref_id,
            int(time.time() * 1000), int(time.time() * 1000)
        ))
        conn.commit()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Логин уже занят'}), 400
    finally:
        conn.close()


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    login = (data.get('login') or '').strip()
    password = data.get('password') or ''

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE login = ?", (login,))
    row = c.fetchone()

    if not row or row['password'] != hash_password(password):
        conn.close()
        return jsonify({'error': 'Неверный логин или пароль'}), 401

    token = generate_token()
    c.execute("UPDATE users SET token = ?, last_seen = ? WHERE id = ?",
              (token, int(time.time() * 1000), row['id']))
    conn.commit()

    c.execute("SELECT * FROM users WHERE id = ?", (row['id'],))
    user = dict(c.fetchone())
    conn.close()
    user.pop('password', None)
    return jsonify({'ok': True, 'user': user})


@app.route('/get-progress', methods=['GET'])
def get_progress():
    token = request.args.get('token')
    if not token:
        return jsonify({'found': False})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({'found': False})

    user = dict(row)
    user.pop('password', None)

    # Парсим JSON-поля
    for field in ['is_tasks_done', 'claimed_quests', 'claimed_promos', 'upgrades', 'earned_promocodes']:
        try:
            user[field] = json.loads(user.get(field) or '[]')
        except Exception:
            user[field] = [] if field != 'upgrades' else {}

    return jsonify({'found': True, 'user': user})


# ============================================================
#  СОХРАНЕНИЕ ПРОГРЕССА
# ============================================================
@app.route('/save-progress', methods=['POST'])
def save_progress():
    data = request.get_json() or {}
    token = data.get('token')
    if not token:
        return jsonify({'error': 'no token'}), 400

    conn = get_db()
    c = conn.cursor()

    now_ms = int(time.time() * 1000)

    c.execute("""
        UPDATE users SET
            score = ?,
            energy = ?,
            max_energy = ?,
            multiplier = ?,
            level = ?,
            total_taps = ?,
            is_balance = ?,
            daily_tap_limit = ?,
            taps_today = ?,
            last_tap_date = ?,
            sub_was_subscribed = ?,
            sub_was_punished = ?,
            is_tasks_done = ?,
            claimed_quests = ?,
            claimed_promos = ?,
            upgrades = ?,
            unlimited_until = ?,
            is_boost_mult_until = ?,
            is_auto_tap_until = ?,
            autotap_level = ?,
            passive_income = ?,
            wallet_balance = ?,
            wallet_total = ?,
            earned_promocodes = ?,
            last_seen = ?
        WHERE token = ?
    """, (
        data.get('score', 0),
        data.get('energy', 500),
        data.get('max_energy', 500),
        data.get('multiplier', 1),
        data.get('level', 1),
        data.get('total_taps', 0),
        data.get('is_balance', 0),
        data.get('daily_tap_limit', 20000),
        data.get('taps_today', 0),
        data.get('last_tap_date'),
        int(data.get('sub_was_subscribed', False)),
        int(data.get('sub_was_punished', False)),
        json.dumps(data.get('is_tasks_done', [])),
        json.dumps(data.get('claimed_quests', [])),
        json.dumps(data.get('claimed_promos', [])),
        json.dumps(data.get('upgrades', {})),
        data.get('unlimited_until', 0),
        data.get('is_boost_mult_until', 0),
        data.get('is_auto_tap_until', 0),
        data.get('autotap_level', 0),
        data.get('passive_income', 0),
        data.get('wallet_balance', 0),
        data.get('wallet_total', 0),
        json.dumps(data.get('earned_promocodes', [])),
        now_ms,
        token
    ))

    conn.commit()
    changes = c.rowcount
    conn.close()

    if changes == 0:
        return jsonify({'error': 'user not found'}), 401
    return jsonify({'ok': True})


# ============================================================
#  HEARTBEAT — обновляет last_seen (кто онлайн)
# ============================================================
@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    data = request.get_json() or {}
    token = data.get('token')
    score = data.get('score', 0)
    if not token:
        return jsonify({'error': 'no token'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET last_seen = ?, score = ? WHERE token = ?",
              (int(time.time() * 1000), score, token))
    conn.commit()
    changes = c.rowcount
    conn.close()

    if changes == 0:
        return jsonify({'error': 'user not found'}), 401
    return jsonify({'ok': True})


# ============================================================
#  ТОП ИГРОКОВ
# ============================================================
@app.route('/top', methods=['GET'])
def get_top():
    limit = int(request.args.get('limit', 100))
    limit = max(1, min(limit, 100))
    now_ms = int(time.time() * 1000)

    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT nickname, score, last_seen, avatar_data
        FROM users
        WHERE nickname IS NOT NULL AND nickname != ''
        ORDER BY score DESC, last_seen ASC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()

    c.execute("SELECT COUNT(*) FROM users WHERE nickname IS NOT NULL AND nickname != ''")
    total = c.fetchone()[0]

    c.execute("""SELECT COUNT(*) FROM users
                 WHERE nickname IS NOT NULL AND nickname != ''
                 AND last_seen > ?""",
              (now_ms - ONLINE_WINDOW_MS,))
    online = c.fetchone()[0]
    offline = total - online

    players = [{
        'nickname': r['nickname'],
        'score': r['score'] or 0,
        'last_seen': r['last_seen'] or 0,
        'avatar_data': r['avatar_data']
    } for r in rows]

    conn.close()
    return jsonify({
        'success': True,
        'players': players,
        'total': total,
        'online': online,
        'offline': offline
    })


# ============================================================
#  РЕФЕРАЛЫ
# ============================================================
@app.route('/my-referrals', methods=['GET'])
def my_referrals():
    token = request.args.get('token')
    if not token:
        return jsonify({'success': False, 'referrals': []})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT nickname FROM users WHERE token = ?", (token,))
    me = c.fetchone()
    if not me:
        conn.close()
        return jsonify({'success': False, 'referrals': []})

    my_nick = me['nickname']
    c.execute("SELECT nickname FROM users WHERE referrer_nickname = ?", (my_nick,))
    refs = [{'nickname': r['nickname']} for r in c.fetchall()]
    conn.close()
    return jsonify({'success': True, 'referrals': refs})


@app.route('/claim-referral', methods=['POST'])
def claim_referral():
    data = request.get_json() or {}
    token = data.get('token')
    amount = int(data.get('amount', 0))
    if not token or amount <= 0:
        return jsonify({'success': False, 'error': 'bad params'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET is_balance = is_balance + ? WHERE token = ?",
              (amount, token))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
#  ПОДПИСКА НА КАНАЛ
# ============================================================
@app.route('/check-sub', methods=['GET'])
def check_sub():
    # Заглушка — здесь должна быть проверка через Telegram Bot API
    return jsonify({'subscribed': True})


# ============================================================
#  ЗАПУСК
# ============================================================
init_db()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
