import os
import time
import json
import sqlite3
import hashlib
import secrets
import traceback

from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_DIR = os.getenv('DATA_DIR', '/app/data')
DB_PATH = os.path.join(DATA_DIR, 'ingsoft.db')
ONLINE_WINDOW_MS = 5 * 60 * 1000


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

    for col, ddl in [
        ('last_seen', 'INTEGER DEFAULT 0'),
        ('avatar_data', 'TEXT'),
        ('referrer_nickname', 'TEXT'),
        ('referrer_id', 'INTEGER'),
        ('role', "TEXT DEFAULT 'user'"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            print(f"[MIGRATION] добавлен столбец {col}")
        except Exception:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nickname TEXT NOT NULL,
            gender TEXT NOT NULL,
            region TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    print("[DB] Таблица messages готова")

    c.execute("""
        CREATE TABLE IF NOT EXISTS group_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            invite_code TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at INTEGER NOT NULL
        )
    """)
    for col, ddl in [
        ('is_admin', 'INTEGER DEFAULT 0'),
        ('can_delete_messages', 'INTEGER DEFAULT 0'),
        ('can_kick', 'INTEGER DEFAULT 0'),
        ('can_pin', 'INTEGER DEFAULT 0'),
        ('can_edit', 'INTEGER DEFAULT 0'),
    ]:
        try:
            c.execute(f"ALTER TABLE group_members ADD COLUMN {col} {ddl}")
            print(f"[MIGRATION] group_members.{col}")
        except Exception:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nickname TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    print("[DB] Таблицы групп готовы")

    conn.commit()
    conn.close()
    print("[DB] Инициализация завершена")


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def generate_token():
    return secrets.token_urlsafe(32)


def compute_referral_reward(ref_count):
    """
    Таблица наград за рефералов (по количеству УЖЕ приглашённых, включая нового):
      1        -> 100
      2        -> 150
      3..4     -> 150
      5        -> 450
      6..100   -> 100
      >100     -> 300
    """
    if ref_count <= 0:
        return 0
    if ref_count == 1:
        return 100
    if ref_count == 2:
        return 150
    if 3 <= ref_count <= 4:
        return 150
    if ref_count == 5:
        return 450
    if 6 <= ref_count <= 100:
        return 100
    return 300


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

    if ref_id:
        try:
            ref_id = int(ref_id)
            if ref_id <= 0:
                ref_id = None
        except Exception:
            ref_id = None

    if len(login) < 3:
        return jsonify({'error': 'Логин минимум 3 символа'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Пароль минимум 6 символов'}), 400
    if len(nickname) < 2:
        return jsonify({'error': 'Ник минимум 2 символа'}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        # 1) Сначала вставляем нового пользователя
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
        new_user_id = c.lastrowid

        # 2) Ищем пригласившего — сначала по id, потом по нику
        referrer_found = None
        if ref_id:
            c.execute("SELECT id, nickname FROM users WHERE id = ?", (ref_id,))
            referrer_found = c.fetchone()
            if referrer_found:
                c.execute("UPDATE users SET referrer_nickname = ? WHERE id = ?",
                          (referrer_found['nickname'], new_user_id))
                conn.commit()

        if not referrer_found and ref_nick:
            c.execute("SELECT id, nickname FROM users WHERE nickname = ?", (ref_nick,))
            referrer_found = c.fetchone()

        # 3) Считаем награду УЖЕ с учётом нового пользователя
        reward = 0
        if referrer_found:
            c.execute("""SELECT COUNT(*) FROM users
                         WHERE referrer_id = ? OR referrer_nickname = ?""",
                      (referrer_found['id'], referrer_found['nickname']))
            ref_count = c.fetchone()[0] or 0

            reward = compute_referral_reward(ref_count)

            if reward > 0:
                c.execute("UPDATE users SET is_balance = is_balance + ? WHERE id = ?",
                          (reward, referrer_found['id']))
                conn.commit()

        return jsonify({
            'ok': True,
            'referrer': referrer_found['nickname'] if referrer_found else None,
            'referrer_id': referrer_found['id'] if referrer_found else None,
            'reward': reward
        })
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

    for field in ['is_tasks_done', 'claimed_quests', 'claimed_promos', 'upgrades', 'earned_promocodes']:
        try:
            user[field] = json.loads(user.get(field) or '[]')
        except Exception:
            user[field] = [] if field != 'upgrades' else {}

    return jsonify({'found': True, 'user': user})


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
            score = ?, energy = ?, max_energy = ?, multiplier = ?, level = ?,
            total_taps = ?, is_balance = ?, daily_tap_limit = ?, taps_today = ?,
            last_tap_date = ?, sub_was_subscribed = ?, sub_was_punished = ?,
            is_tasks_done = ?, claimed_quests = ?, claimed_promos = ?, upgrades = ?,
            unlimited_until = ?, is_boost_mult_until = ?, is_auto_tap_until = ?,
            autotap_level = ?, passive_income = ?, wallet_balance = ?, wallet_total = ?,
            earned_promocodes = ?, last_seen = ?
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


@app.route('/claim-quest', methods=['POST'])
def claim_quest():
    data = request.get_json() or {}
    token = data.get('token')
    quest_id = data.get('quest_id')
    reward = int(data.get('reward', 0))
    if not token or not quest_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT claimed_quests, score FROM users WHERE token = ?", (token,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'user not found'}), 401

    try:
        claimed = json.loads(row['claimed_quests'] or '[]')
    except Exception:
        claimed = []

    if quest_id in claimed:
        conn.close()
        return jsonify({'success': False, 'error': 'Уже забрано'}), 400

    claimed.append(quest_id)
    new_score = (row['score'] or 0) + reward

    c.execute("UPDATE users SET claimed_quests = ?, score = ? WHERE token = ?",
              (json.dumps(claimed), new_score, token))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'new_score': new_score, 'claimed': claimed})


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


@app.route('/my-id', methods=['GET'])
def my_id():
    token = request.args.get('token')
    if not token:
        return jsonify({'success': False}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, nickname FROM users WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({'success': False}), 401
    return jsonify({'success': True, 'id': row['id'], 'nickname': row['nickname']})


@app.route('/referrals/check-new', methods=['GET'])
def referrals_check_new():
    token = request.args.get('token')
    since_id = request.args.get('since_id', 0)
    try:
        since_id = int(since_id)
    except Exception:
        since_id = 0

    if not token:
        return jsonify({'success': False, 'new': [], 'count': 0})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, nickname FROM users WHERE token = ?", (token,))
    me = c.fetchone()
    if not me:
        conn.close()
        return jsonify({'success': False, 'new': [], 'count': 0})

    c.execute("""SELECT id, nickname FROM users
                 WHERE (referrer_id = ? OR referrer_nickname = ?)
                   AND id > ?
                 ORDER BY id ASC""",
              (me['id'], me['nickname'], since_id))
    rows = c.fetchall()

    c.execute("""SELECT COUNT(*) FROM users
                 WHERE referrer_id = ? OR referrer_nickname = ?""",
              (me['id'], me['nickname']))
    total = c.fetchone()[0] or 0

    conn.close()
    new_list = [{'id': r['id'], 'nickname': r['nickname']} for r in rows]
    return jsonify({
        'success': True,
        'new': new_list,
        'count': total,
        'max_id': new_list[-1]['id'] if new_list else since_id
    })


@app.route('/my-referrals', methods=['GET'])
def my_referrals():
    token = request.args.get('token')
    if not token:
        return jsonify({'success': False, 'referrals': []})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, nickname FROM users WHERE token = ?", (token,))
    me = c.fetchone()
    if not me:
        conn.close()
        return jsonify({'success': False, 'referrals': []})

    my_id = me['id']
    c.execute("""SELECT nickname FROM users
                 WHERE referrer_id = ? OR referrer_nickname = ?
                 ORDER BY id ASC""",
              (my_id, me['nickname']))
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


@app.route('/give-referral-reward', methods=['POST'])
def give_referral_reward():
    data = request.get_json() or {}
    referrer_nick = data.get('referrer_nickname')
    new_user_token = data.get('new_user_token')
    amount = int(data.get('amount', 500))

    if not referrer_nick or not new_user_token:
        return jsonify({'success': False, 'error': 'bad params'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET is_balance = is_balance + ? WHERE nickname = ?",
              (amount, referrer_nick))
    c.execute("UPDATE users SET is_balance = is_balance + ? WHERE token = ?",
              (amount, new_user_token))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/check-sub', methods=['GET'])
def check_sub():
    return jsonify({'subscribed': True})


def _get_user_by_token(token):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, nickname, gender, region FROM users WHERE token = ?", (token,))
    u = c.fetchone()
    conn.close()
    return u


def _get_user_full_by_token(token):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, nickname, gender FROM users WHERE token = ?", (token,))
    u = c.fetchone()
    conn.close()
    return u


def _is_admin(token):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()
    return row and row['role'] == 'admin'


@app.route('/send-message', methods=['POST'])
def send_message():
    try:
        data = request.get_json() or {}
        token = data.get('token')
        text = (data.get('text') or '').strip()

        if not token or not text:
            return jsonify({'success': False, 'error': 'Пустое сообщение'}), 400
        if len(text) > 500:
            return jsonify({'success': False, 'error': 'Слишком длинное (макс 500)'}), 400

        u = _get_user_by_token(token)
        if not u:
            return jsonify({'success': False, 'error': 'Пользователь не найден'}), 401

        region = (u['region'] or '').strip().lower()
        if region != 'ингушетия':
            return jsonify({'success': False, 'error': 'Чат только для Ингушетии'}), 403

        gender = (u['gender'] or 'male').strip().lower()
        if gender not in ('male', 'female'):
            gender = 'male'

        conn = get_db()
        c = conn.cursor()
        c.execute("""INSERT INTO messages (user_id, nickname, gender, region, text, created_at)
                     VALUES (?, ?, ?, ?, ?, ?)""",
                  (u['id'], u['nickname'], gender, u['region'], text, int(time.time() * 1000)))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        print("[send-message ERROR]", e)
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500


@app.route('/get-messages', methods=['GET'])
def get_messages():
    try:
        token = request.args.get('token', '')
        if not token:
            return jsonify({'success': False, 'error': 'Не авторизован', 'messages': []})

        u = _get_user_by_token(token)
        if not u:
            return jsonify({'success': False, 'error': 'Не авторизован', 'messages': []})

        region = (u['region'] or '').strip().lower()
        if region != 'ингушетия':
            return jsonify({'success': False, 'error': 'Чат только для Ингушетии', 'messages': []})

        my_gender = (u['gender'] or 'male').strip().lower()
        if my_gender not in ('male', 'female'):
            my_gender = 'male'

        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT id, nickname, gender, text, created_at
            FROM messages
            WHERE gender = ?
            ORDER BY id DESC
            LIMIT 100
        """, (my_gender,))
        rows = c.fetchall()
        conn.close()

        messages = [{
            'id': r['id'],
            'nickname': r['nickname'],
            'gender': r['gender'],
            'text': r['text'],
            'created_at': r['created_at']
        } for r in rows]

        messages.reverse()
        return jsonify({'success': True, 'messages': messages, 'chat': my_gender})
    except Exception as e:
        print("[get-messages ERROR]", e)
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Ошибка сервера', 'messages': []}), 500


@app.route('/delete-message', methods=['POST'])
def delete_message():
    data = request.get_json() or {}
    token = data.get('token')
    msg_id = data.get('message_id')
    if not token or not msg_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    if not _is_admin(token):
        return jsonify({'success': False, 'error': 'Только для админов'}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/edit-message', methods=['POST'])
def edit_message():
    data = request.get_json() or {}
    token = data.get('token')
    msg_id = data.get('message_id')
    new_text = (data.get('text') or '').strip()
    if not token or not msg_id or not new_text:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    if not _is_admin(token):
        return jsonify({'success': False, 'error': 'Только для админов'}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE messages SET text = ? WHERE id = ?", (new_text, msg_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/pin-message', methods=['POST'])
def pin_message():
    data = request.get_json() or {}
    token = data.get('token')
    msg_id = data.get('message_id')
    if not token or not msg_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    if not _is_admin(token):
        return jsonify({'success': False, 'error': 'Только для админов'}), 403
    return jsonify({'success': True})


@app.route('/chat-stats', methods=['GET'])
def chat_stats():
    token = request.args.get('token')
    if not token:
        return jsonify({'success': False}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE nickname IS NOT NULL AND nickname != ''")
    total_players = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT user_id) FROM messages")
    unique_chatters = c.fetchone()[0]
    now_ms = int(time.time() * 1000)
    c.execute("SELECT COUNT(*) FROM users WHERE last_seen > ?", (now_ms - ONLINE_WINDOW_MS,))
    online_now = c.fetchone()[0]
    c.execute("""SELECT nickname, MAX(created_at) as last_time
                 FROM messages
                 GROUP BY user_id
                 ORDER BY last_time DESC
                 LIMIT 50""")
    history = [{'nickname': r['nickname'], 'last_time': r['last_time']} for r in c.fetchall()]
    conn.close()
    return jsonify({
        'success': True,
        'total_players': total_players,
        'unique_chatters': unique_chatters,
        'online_now': online_now,
        'history': history
    })


# ============ ГРУППОВЫЕ ЧАТЫ ============

@app.route('/groups/create', methods=['POST'])
def groups_create():
    data = request.get_json() or {}
    token = data.get('token')
    name = (data.get('name') or '').strip()
    if not token or not name:
        return jsonify({'success': False, 'error': 'bad params'}), 400

    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    invite_code = secrets.token_urlsafe(8)
    now_ms = int(time.time() * 1000)

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO group_chats (name, owner_id, invite_code, created_at) VALUES (?, ?, ?, ?)",
              (name, u['id'], invite_code, now_ms))
    chat_id = c.lastrowid
    c.execute("INSERT INTO group_members (chat_id, user_id, joined_at) VALUES (?, ?, ?)",
              (chat_id, u['id'], now_ms))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'chat_id': chat_id, 'invite_code': invite_code, 'name': name})


@app.route('/groups/list', methods=['GET'])
def groups_list():
    token = request.args.get('token')
    if not token:
        return jsonify({'success': False, 'chats': []})
    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'chats': []})

    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT gc.id, gc.name, gc.invite_code, gc.owner_id, gc.created_at
                 FROM group_chats gc
                 JOIN group_members gm ON gm.chat_id = gc.id
                 WHERE gm.user_id = ?
                 ORDER BY gc.created_at DESC""", (u['id'],))
    chats = [{'id': r['id'], 'name': r['name'], 'invite_code': r['invite_code'],
              'owner_id': r['owner_id'], 'is_owner': r['owner_id'] == u['id']} for r in c.fetchall()]
    conn.close()
    return jsonify({'success': True, 'chats': chats})


@app.route('/groups/join', methods=['POST'])
def groups_join():
    data = request.get_json() or {}
    token = data.get('token')
    invite_code = (data.get('invite_code') or '').strip()
    if not token or not invite_code:
        return jsonify({'success': False, 'error': 'bad params'}), 400

    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM group_chats WHERE invite_code = ?", (invite_code,))
    chat = c.fetchone()
    if not chat:
        conn.close()
        return jsonify({'success': False, 'error': 'Чат не найден'}), 404

    c.execute("SELECT id FROM group_members WHERE chat_id = ? AND user_id = ?",
              (chat['id'], u['id']))
    if c.fetchone():
        conn.close()
        return jsonify({'success': True, 'chat_id': chat['id'], 'name': chat['name'], 'already': True})

    c.execute("INSERT INTO group_members (chat_id, user_id, joined_at) VALUES (?, ?, ?)",
              (chat['id'], u['id'], int(time.time() * 1000)))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'chat_id': chat['id'], 'name': chat['name']})


@app.route('/groups/leave', methods=['POST'])
def groups_leave():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    if not token or not chat_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM group_members WHERE chat_id = ? AND user_id = ?", (chat_id, u['id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/groups/add-member', methods=['POST'])
def groups_add_member():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    nickname = (data.get('nickname') or '').strip()
    if not token or not chat_id or not nickname:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT owner_id FROM group_chats WHERE id = ?", (chat_id,))
    chat = c.fetchone()
    if not chat:
        conn.close()
        return jsonify({'success': False, 'error': 'Чат не найден'}), 404
    if chat['owner_id'] != u['id']:
        conn.close()
        return jsonify({'success': False, 'error': 'Только владелец может добавлять'}), 403

    c.execute("SELECT id, nickname FROM users WHERE nickname = ?", (nickname,))
    target = c.fetchone()
    if not target:
        conn.close()
        return jsonify({'success': False, 'error': 'Игрок не найден'}), 404

    c.execute("SELECT id FROM group_members WHERE chat_id = ? AND user_id = ?",
              (chat_id, target['id']))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Уже в чате'}), 400

    c.execute("INSERT INTO group_members (chat_id, user_id, joined_at) VALUES (?, ?, ?)",
              (chat_id, target['id'], int(time.time() * 1000)))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'nickname': target['nickname']})


@app.route('/groups/members', methods=['GET'])
def groups_members():
    token = request.args.get('token')
    chat_id = request.args.get('chat_id')
    if not token or not chat_id:
        return jsonify({'success': False, 'members': []})
    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'members': []})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM group_members WHERE chat_id = ? AND user_id = ?",
              (chat_id, u['id']))
    if not c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Нет доступа'}), 403

    c.execute("SELECT owner_id FROM group_chats WHERE id = ?", (chat_id,))
    chat = c.fetchone()
    owner_id = chat['owner_id'] if chat else None

    c.execute("""SELECT u.id, u.nickname, u.gender, gm.joined_at,
                        gm.is_admin, gm.can_delete_messages, gm.can_kick, gm.can_pin, gm.can_edit
                 FROM group_members gm
                 JOIN users u ON u.id = gm.user_id
                 WHERE gm.chat_id = ?
                 ORDER BY gm.joined_at ASC""", (chat_id,))
    members = [{
        'id': r['id'], 'nickname': r['nickname'], 'gender': r['gender'],
        'joined_at': r['joined_at'],
        'is_owner': r['id'] == owner_id,
        'is_admin': bool(r['is_admin']),
        'can_delete_messages': bool(r['can_delete_messages']),
        'can_kick': bool(r['can_kick']),
        'can_pin': bool(r['can_pin']),
        'can_edit': bool(r['can_edit'])
    } for r in c.fetchall()]
    conn.close()
    return jsonify({'success': True, 'members': members, 'owner_id': owner_id})


@app.route('/groups/send', methods=['POST'])
def groups_send():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    text = (data.get('text') or '').strip()
    if not token or not chat_id or not text:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    if len(text) > 500:
        return jsonify({'success': False, 'error': 'Слишком длинное'}), 400

    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM group_members WHERE chat_id = ? AND user_id = ?",
              (chat_id, u['id']))
    if not c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Нет доступа'}), 403

    c.execute("""INSERT INTO group_messages (chat_id, user_id, nickname, text, created_at)
                 VALUES (?, ?, ?, ?, ?)""",
              (chat_id, u['id'], u['nickname'], text, int(time.time() * 1000)))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/groups/messages', methods=['GET'])
def groups_messages():
    token = request.args.get('token')
    chat_id = request.args.get('chat_id')
    if not token or not chat_id:
        return jsonify({'success': False, 'messages': []})
    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'messages': []})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM group_members WHERE chat_id = ? AND user_id = ?",
              (chat_id, u['id']))
    if not c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Нет доступа', 'messages': []}), 403

    c.execute("""SELECT id, user_id, nickname, text, created_at
                 FROM group_messages
                 WHERE chat_id = ?
                 ORDER BY id DESC
                 LIMIT 100""", (chat_id,))
    rows = c.fetchall()

    c.execute("SELECT owner_id FROM group_chats WHERE id = ?", (chat_id,))
    chat_row = c.fetchone()
    owner_id = chat_row['owner_id'] if chat_row else None

    c.execute("""SELECT is_admin, can_delete_messages, can_kick, can_pin, can_edit
                 FROM group_members WHERE chat_id = ? AND user_id = ?""",
              (chat_id, u['id']))
    my_perm = c.fetchone()
    conn.close()

    my_is_admin = bool(my_perm['is_admin']) if my_perm else False
    my_can_del = bool(my_perm['can_delete_messages']) if my_perm else False
    my_can_kick = bool(my_perm['can_kick']) if my_perm else False
    my_can_pin = bool(my_perm['can_pin']) if my_perm else False
    my_can_edit = bool(my_perm['can_edit']) if my_perm else False
    i_am_owner = (u['id'] == owner_id)

    msgs = [{
        'id': r['id'],
        'user_id': r['user_id'],
        'nickname': r['nickname'],
        'text': r['text'],
        'created_at': r['created_at']
    } for r in rows]
    msgs.reverse()

    return jsonify({
        'success': True,
        'messages': msgs,
        'owner_id': owner_id,
        'my_perms': {
            'is_owner': i_am_owner,
            'is_admin': my_is_admin,
            'can_delete_messages': my_can_del,
            'can_kick': my_can_kick,
            'can_pin': my_can_pin,
            'can_edit': my_can_edit
        }
    })


def _check_group_perm(token, chat_id, perm_name):
    u = _get_user_full_by_token(token)
    if not u:
        return None, False, False
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT owner_id FROM group_chats WHERE id = ?", (chat_id,))
    chat = c.fetchone()
    if not chat:
        conn.close()
        return u, False, False
    is_owner = (chat['owner_id'] == u['id'])
    if is_owner:
        conn.close()
        return u, True, True
    c.execute(f"SELECT {perm_name} FROM group_members WHERE chat_id = ? AND user_id = ?",
              (chat_id, u['id']))
    row = c.fetchone()
    conn.close()
    has_perm = bool(row and row[perm_name])
    return u, False, has_perm


@app.route('/groups/delete', methods=['POST'])
def groups_delete():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    if not token or not chat_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT owner_id FROM group_chats WHERE id = ?", (chat_id,))
    chat = c.fetchone()
    if not chat:
        conn.close()
        return jsonify({'success': False, 'error': 'Чат не найден'}), 404
    if chat['owner_id'] != u['id']:
        conn.close()
        return jsonify({'success': False, 'error': 'Только владелец может удалить'}), 403
    c.execute("DELETE FROM group_messages WHERE chat_id = ?", (chat_id,))
    c.execute("DELETE FROM group_members WHERE chat_id = ?", (chat_id,))
    c.execute("DELETE FROM group_chats WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/groups/kick', methods=['POST'])
def groups_kick():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    if not token or not chat_id or not user_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    u, is_owner, has_perm = _check_group_perm(token, chat_id, 'can_kick')
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401
    if not (is_owner or has_perm):
        return jsonify({'success': False, 'error': 'Нет прав на кик'}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT owner_id FROM group_chats WHERE id = ?", (chat_id,))
    chat = c.fetchone()
    if chat and chat['owner_id'] == user_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Нельзя кикнуть владельца'}), 403

    c.execute("DELETE FROM group_members WHERE chat_id = ? AND user_id = ?",
              (chat_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/groups/message/delete', methods=['POST'])
def groups_message_delete():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    message_id = data.get('message_id')
    if not token or not chat_id or not message_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    u, is_owner, has_perm = _check_group_perm(token, chat_id, 'can_delete_messages')
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM group_messages WHERE id = ? AND chat_id = ?",
              (message_id, chat_id))
    msg = c.fetchone()
    if not msg:
        conn.close()
        return jsonify({'success': False, 'error': 'Сообщение не найдено'}), 404

    is_own = (msg['user_id'] == u['id'])
    if not (is_owner or has_perm or is_own):
        conn.close()
        return jsonify({'success': False, 'error': 'Нет прав'}), 403

    c.execute("DELETE FROM group_messages WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/groups/message/edit', methods=['POST'])
def groups_message_edit():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    message_id = data.get('message_id')
    new_text = (data.get('text') or '').strip()
    if not token or not chat_id or not message_id or not new_text:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    if len(new_text) > 500:
        return jsonify({'success': False, 'error': 'Слишком длинное'}), 400
    u, is_owner, has_perm = _check_group_perm(token, chat_id, 'can_edit')
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM group_messages WHERE id = ? AND chat_id = ?",
              (message_id, chat_id))
    msg = c.fetchone()
    if not msg:
        conn.close()
        return jsonify({'success': False, 'error': 'Сообщение не найдено'}), 404

    is_own = (msg['user_id'] == u['id'])
    if not (is_owner or has_perm or is_own):
        conn.close()
        return jsonify({'success': False, 'error': 'Нет прав'}), 403

    c.execute("UPDATE group_messages SET text = ? WHERE id = ?", (new_text, message_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/groups/set-admin', methods=['POST'])
def groups_set_admin():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    is_admin = 1 if data.get('is_admin') else 0
    perms = data.get('perms') or {}

    if not token or not chat_id or not user_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400

    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT owner_id FROM group_chats WHERE id = ?", (chat_id,))
    chat = c.fetchone()
    if not chat:
        conn.close()
        return jsonify({'success': False, 'error': 'Чат не найден'}), 404
    if chat['owner_id'] != u['id']:
        conn.close()
        return jsonify({'success': False, 'error': 'Только владелец назначает'}), 403

    c.execute("""UPDATE group_members SET
                    is_admin = ?,
                    can_delete_messages = ?,
                    can_kick = ?,
                    can_pin = ?,
                    can_edit = ?
                 WHERE chat_id = ? AND user_id = ?""",
              (is_admin,
               1 if perms.get('can_delete_messages') else 0,
               1 if perms.get('can_kick') else 0,
               1 if perms.get('can_pin') else 0,
               1 if perms.get('can_edit') else 0,
               chat_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/groups/rename', methods=['POST'])
def groups_rename():
    data = request.get_json() or {}
    token = data.get('token')
    chat_id = data.get('chat_id')
    new_name = (data.get('name') or '').strip()
    if not token or not chat_id or not new_name:
        return jsonify({'success': False, 'error': 'bad params'}), 400

    u = _get_user_full_by_token(token)
    if not u:
        return jsonify({'success': False, 'error': 'user not found'}), 401

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT owner_id FROM group_chats WHERE id = ?", (chat_id,))
    chat = c.fetchone()
    if not chat:
        conn.close()
        return jsonify({'success': False, 'error': 'Чат не найден'}), 404
    if chat['owner_id'] != u['id']:
        conn.close()
        return jsonify({'success': False, 'error': 'Только владелец'}), 403

    c.execute("UPDATE group_chats SET name = ? WHERE id = ?", (new_name, chat_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'name': new_name})


init_db()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
