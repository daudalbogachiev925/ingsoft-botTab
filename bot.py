import os
import json
import hashlib
import secrets
import sqlite3
from datetime import datetime
import telebot
from flask import Flask, request, jsonify
from flask_cors import CORS

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
PORT = int(os.environ.get('PORT', 5000))
DB_PATH = 'ingsoft.db'

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


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
        referrer_id INTEGER,
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

    # === МИГРАЦИЯ: добавляем referrer_id, если база была создана раньше ===
    c.execute("PRAGMA table_info(users)")
    cols = [row[1] for row in c.fetchall()]
    if 'referrer_id' not in cols:
        c.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
        conn.commit()
        print("✅ Добавлена колонка referrer_id")

    conn.close()


init_db()


def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()


def generate_token():
    return secrets.token_hex(32)


# === СПИСОК ВСЕХ КОЛОНОК ТАБЛИЦЫ (в правильном порядке) ===
USER_COLUMNS = ['id','login','password_hash','token','nickname','gender','region','phone',
                'full_name','telegram_id','referrer_id','score','energy','max_energy',
                'multiplier','level','total_taps','is_balance','daily_tap_limit','taps_today',
                'last_tap_date','sub_was_subscribed','sub_was_punished','is_tasks_done',
                'claimed_quests','claimed_promos','upgrades','unlimited_until',
                'is_boost_mult_until','is_auto_tap_until','autotap_level','passive_income',
                'wallet_balance','wallet_total','earned_promocodes','created_at','last_updated']


def row_to_user(row):
    """Преобразует строку БД в словарь пользователя."""
    u = dict(zip(USER_COLUMNS, row))
    u.pop('password_hash', None)
    u['is_tasks_done'] = json.loads(u.get('is_tasks_done') or '[]')
    u['claimed_quests'] = json.loads(u.get('claimed_quests') or '[]')
    u['claimed_promos'] = json.loads(u.get('claimed_promos') or '[]')
    u['upgrades'] = json.loads(u.get('upgrades') or '{}')
    u['earned_promocodes'] = json.loads(u.get('earned_promocodes') or '[]')
    u['sub_was_subscribed'] = bool(u.get('sub_was_subscribed'))
    u['sub_was_punished'] = bool(u.get('sub_was_punished'))
    return u


def get_referral_reward(friend_number):
    """
    Награда за N-го друга:
    1-й друг → 100 IS
    2-й друг → 200 IS
    3-й друг → 250 IS
    4-100 → 300 IS за каждого
    100+ → 100 IS за каждого
    """
    if friend_number <= 0:
        return 0
    if friend_number == 1:
        return 100
    if friend_number == 2:
        return 200
    if friend_number == 3:
        return 250
    if friend_number > 100:
        return 100
    return 300


# ============================================================
# РЕГИСТРАЦИЯ
# ============================================================
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
        telegram_id = data.get('telegram_id')
        referrer_nickname = (data.get('referrer_nickname') or '').strip()
        referrer_telegram_id = data.get('referrer_id')

        # === ВАЛИДАЦИЯ ===
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

        # Проверка логина
        c.execute('SELECT id FROM users WHERE login = ?', (login,))
        if c.fetchone():
            conn.close()
            return jsonify({"error": "Такой логин уже занят"}), 400

        # Проверка никнейма
        c.execute('SELECT id FROM users WHERE LOWER(nickname) = LOWER(?)', (nickname,))
        if c.fetchone():
            conn.close()
            return jsonify({"error": "Такой никнейм уже занят"}), 400

        # === ИЩЕМ РЕФЕРЕРА ===
        referrer_user_id = None
        referrer_found_by = None

        # 1) Сначала по никнейму
        if referrer_nickname and referrer_nickname.lower() != nickname.lower():
            c.execute('SELECT id FROM users WHERE LOWER(nickname) = LOWER(?)', (referrer_nickname,))
            ref_row = c.fetchone()
            if ref_row:
                referrer_user_id = ref_row[0]
                referrer_found_by = 'nickname'
                print(f"✅ Реферер найден по нику: {referrer_nickname} (id={referrer_user_id})")

        # 2) Если по нику не нашли — пробуем по telegram_id
        if not referrer_user_id and referrer_telegram_id and referrer_telegram_id != telegram_id:
            c.execute('SELECT id FROM users WHERE telegram_id = ?', (referrer_telegram_id,))
            ref_row = c.fetchone()
            if ref_row:
                referrer_user_id = ref_row[0]
                referrer_found_by = 'telegram_id'
                print(f"✅ Реферер найден по telegram_id: {referrer_telegram_id} (id={referrer_user_id})")

        password_hash = hash_password(password)
        token = generate_token()
        now = datetime.now().isoformat()

        c.execute('''INSERT INTO users 
            (login, password_hash, token, nickname, gender, region, phone, full_name,
             telegram_id, referrer_id, created_at, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (login, password_hash, token, nickname, gender, region, phone, full_name,
             telegram_id, referrer_user_id, now, now))
        conn.commit()
        user_id = c.lastrowid

        # === НАЧИСЛЯЕМ НАГРАДУ РЕФЕРЕРУ ===
        referral_reward = 0
        friend_number = 0
        if referrer_user_id:
            # Считаем сколько друзей у реферера УЖЕ было
            c.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (referrer_user_id,))
            existing_friends = c.fetchone()[0]
            friend_number = existing_friends + 1
            referral_reward = get_referral_reward(friend_number)

            c.execute('UPDATE users SET is_balance = is_balance + ? WHERE id = ?',
                      (referral_reward, referrer_user_id))
            conn.commit()
            print(f"💰 Рефереру id={referrer_user_id} начислено +{referral_reward} IS за {friend_number}-го друга")

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
            "full_name": full_name,
            "referrer_id": referrer_user_id,
            "referrer_found_by": referrer_found_by,
            "referral_reward": referral_reward,
            "friend_number": friend_number
        })
    except Exception as e:
        print(f"❌ Ошибка регистрации: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# ВХОД
# ============================================================
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

        user_data = row_to_user(row)
        user_data['token'] = new_token

        return jsonify({"success": True, "user": user_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# ПОЛУЧЕНИЕ ПРОГРЕССА
# ============================================================
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

        return jsonify({"found": True, "user": row_to_user(row)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# СОХРАНЕНИЕ ПРОГРЕССА
# ============================================================
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


# ============================================================
# 🆕 СПИСОК ДРУЗЕЙ (РЕФЕРАЛОВ)
# ============================================================
@app.route('/referrals', methods=['GET'])
def referrals():
    try:
        token = request.args.get('token', '')
        if not token:
            return jsonify({"error": "token missing"}), 400

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE token = ?', (token,))
        me = c.fetchone()
        if not me:
            conn.close()
            return jsonify({"error": "Неверный токен"}), 401
        my_id = me[0]

        c.execute('''SELECT nickname, created_at, is_balance 
                     FROM users WHERE referrer_id = ? 
                     ORDER BY created_at ASC''', (my_id,))
        rows = c.fetchall()
        conn.close()

        refs = []
        for r in rows:
            refs.append({
                "nickname": r[0] or 'Игрок',
                "created_at": r[1] or '',
                "is_balance": r[2] or 0
            })

        return jsonify({"ok": True, "referrals": refs, "count": len(refs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# 🆕 СТАТИСТИКА ПО РЕФЕРАЛАМ (для вкладки "Бонус")
# ============================================================
@app.route('/referral-stats', methods=['GET'])
def referral_stats():
    try:
        token = request.args.get('token', '')
        if not token:
            return jsonify({"error": "token missing"}), 400

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE token = ?', (token,))
        me = c.fetchone()
        if not me:
            conn.close()
            return jsonify({"error": "Неверный токен"}), 401
        my_id = me[0]

        c.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (my_id,))
        count = c.fetchone()[0]
        conn.close()

        # Считаем общую сумму
        total = 0
        for i in range(1, count + 1):
            total += get_referral_reward(i)

        return jsonify({
            "ok": True,
            "friends_count": count,
            "total_earned": total,
            "next_reward": get_referral_reward(count + 1),
            "progress_to_100": round((count / 100) * 100, 1)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# 🆕 ВСЕ ПОЛЬЗОВАТЕЛИ (для админки)
# Открой: https://ingsofttap.bothost.tech/admin/users
# ============================================================
@app.route('/admin/users', methods=['GET'])
def admin_users():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''SELECT id, telegram_id, login, nickname, gender, region, phone,
                            full_name, referrer_id, score, is_balance, created_at
                     FROM users ORDER BY created_at DESC''')
        rows = c.fetchall()
        conn.close()

        users = []
        for r in rows:
            users.append({
                "id": r[0],
                "telegram_id": r[1],
                "login": r[2],
                "nickname": r[3],
                "gender": r[4],
                "region": r[5],
                "phone": r[6],
                "full_name": r[7],
                "referrer_id": r[8],
                "score": r[9],
                "is_balance": r[10],
                "created_at": r[11]
            })

        return jsonify({"ok": True, "count": len(users), "users": users})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# 🆕 РУЧНОЙ ПЕРЕСЧЁТ РЕФЕРАЛЬНЫХ НАГРАД
# Если что-то пошло не так и нужно пересчитать всем баланс
# Открой: https://ingsofttap.bothost.tech/admin/recalc-referrals
# ============================================================
@app.route('/admin/recalc-referrals', methods=['GET'])
def admin_recalc_referrals():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Получаем всех, у кого есть рефералы
        c.execute('''SELECT referrer_id, COUNT(*) as cnt 
                     FROM users 
                     WHERE referrer_id IS NOT NULL 
                     GROUP BY referrer_id''')
        referrers = c.fetchall()

        results = []
        for ref_id, cnt in referrers:
            total = 0
            for i in range(1, cnt + 1):
                total += get_referral_reward(i)

            c.execute('UPDATE users SET is_balance = ? WHERE id = ?', (total, ref_id))
            results.append({"user_id": ref_id, "friends": cnt, "balance_set": total})

        conn.commit()
        conn.close()
        return jsonify({"ok": True, "recalculated": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# ПРОВЕРКА ПОДПИСКИ НА TELEGRAM-КАНАЛ
# ============================================================
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
    return jsonify({"status": "ok", "bot": "IngSoft Check Bot"})


@app.route('/ping')
def ping():
    return "pong"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
