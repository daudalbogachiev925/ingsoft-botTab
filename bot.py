import os, time, json, hashlib, secrets, traceback
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
DB_CONFIG = {'host':'localhost','database':'ingsoft_db','user':'ingsoft_user','password':'IngSoft2026!'}
ONLINE_WINDOW_MS = 5*60*1000

def get_db(): return psycopg2.connect(**DB_CONFIG)
def cur(conn): return conn.cursor(cursor_factory=RealDictCursor)

def init_db():
    conn = get_db(); c = cur(conn)
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, login TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        token TEXT UNIQUE, nickname TEXT, gender TEXT DEFAULT 'male', phone TEXT,
        region TEXT, full_name TEXT, telegram_id BIGINT, score BIGINT DEFAULT 0,
        energy INTEGER DEFAULT 500, max_energy INTEGER DEFAULT 500,
        multiplier INTEGER DEFAULT 1, level INTEGER DEFAULT 1,
        total_taps BIGINT DEFAULT 0, is_balance INTEGER DEFAULT 0,
        daily_tap_limit INTEGER DEFAULT 20000, taps_today INTEGER DEFAULT 0,
        last_tap_date TEXT, sub_was_subscribed INTEGER DEFAULT 0,
        sub_was_punished INTEGER DEFAULT 0, is_tasks_done TEXT DEFAULT '[]',
        claimed_quests TEXT DEFAULT '[]', claimed_promos TEXT DEFAULT '[]',
        upgrades TEXT DEFAULT '{}', unlimited_until BIGINT DEFAULT 0,
        is_boost_mult_until BIGINT DEFAULT 0, is_auto_tap_until BIGINT DEFAULT 0,
        autotap_level INTEGER DEFAULT 0, passive_income INTEGER DEFAULT 0,
        wallet_balance REAL DEFAULT 0, wallet_total REAL DEFAULT 0,
        earned_promocodes TEXT DEFAULT '[]', avatar_data TEXT,
        referrer_nickname TEXT, referrer_id INTEGER, referral_seen_id INTEGER DEFAULT 0,
        last_seen BIGINT DEFAULT 0, role TEXT DEFAULT 'user', created_at BIGINT)""")
    for col,ddl in [('last_seen','BIGINT DEFAULT 0'),('avatar_data','TEXT'),
        ('referrer_nickname','TEXT'),('referrer_id','INTEGER'),
        ('role',"TEXT DEFAULT 'user'"),('referral_seen_id','INTEGER DEFAULT 0')]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}"); conn.commit()
        except: conn.rollback()
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, nickname TEXT NOT NULL,
        gender TEXT NOT NULL, region TEXT NOT NULL, text TEXT NOT NULL,
        created_at BIGINT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS group_chats (
        id SERIAL PRIMARY KEY, name TEXT NOT NULL, owner_id INTEGER NOT NULL,
        invite_code TEXT UNIQUE NOT NULL, created_at BIGINT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS group_members (
        id SERIAL PRIMARY KEY, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        joined_at BIGINT NOT NULL)""")
    for col,ddl in [('is_admin','INTEGER DEFAULT 0'),('can_delete_messages','INTEGER DEFAULT 0'),
        ('can_kick','INTEGER DEFAULT 0'),('can_pin','INTEGER DEFAULT 0'),('can_edit','INTEGER DEFAULT 0')]:
        try: c.execute(f"ALTER TABLE group_members ADD COLUMN {col} {ddl}"); conn.commit()
        except: conn.rollback()
    c.execute("""CREATE TABLE IF NOT EXISTS group_messages (
        id SERIAL PRIMARY KEY, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        nickname TEXT NOT NULL, text TEXT NOT NULL, created_at BIGINT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS game_bets (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, nickname TEXT NOT NULL,
        game_id TEXT NOT NULL, bet BIGINT NOT NULL, win BOOLEAN NOT NULL,
        payout BIGINT NOT NULL, multiplier REAL NOT NULL, created_at BIGINT NOT NULL)""")
    try: c.execute("CREATE INDEX IF NOT EXISTS idx_game_bets_created ON game_bets(created_at DESC)")
    except: conn.rollback()
    conn.commit(); conn.close(); print("[DB] init done")

def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()
def generate_token(): return secrets.token_urlsafe(32)

def compute_referral_reward(n):
    if n<=0: return 0
    if n==1: return 100
    if n==2: return 150
    if 3<=n<=4: return 150
    if n==5: return 450
    if 6<=n<=100: return 100
    return 300

@app.route('/register', methods=['POST'])
def register():
    d = request.get_json() or {}
    login=(d.get('login') or '').strip(); password=d.get('password') or ''
    nickname=(d.get('nickname') or '').strip(); gender=d.get('gender') or 'male'
    phone=d.get('phone') or ''; region=d.get('region') or ''
    full_name=d.get('full_name') or ''; telegram_id=d.get('telegram_id')
    ref_nick=d.get('referrer_nickname'); ref_id=d.get('referrer_id')
    if ref_id:
        try:
            ref_id=int(ref_id)
            if ref_id<=0: ref_id=None
        except: ref_id=None
    if len(login)<3: return jsonify({'error':'Логин минимум 3 символа'}),400
    if len(password)<6: return jsonify({'error':'Пароль минимум 6 символов'}),400
    if len(nickname)<2: return jsonify({'error':'Ник минимум 2 символа'}),400
    conn=get_db(); c=cur(conn)
    try:
        now_ms=int(time.time()*1000)
        c.execute("""INSERT INTO users (login,password,nickname,gender,phone,region,full_name,
            telegram_id,referrer_nickname,referrer_id,energy,max_energy,created_at,last_seen)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,500,500,%s,%s) RETURNING id""",
            (login,hash_password(password),nickname,gender,phone,region,full_name,
             telegram_id,ref_nick,ref_id,now_ms,now_ms))
        new_id=c.fetchone()['id']; conn.commit()
        ref=None
        if ref_id:
            c.execute("SELECT id,nickname FROM users WHERE id=%s",(ref_id,))
            ref=c.fetchone()
            if ref:
                c.execute("UPDATE users SET referrer_nickname=%s WHERE id=%s",(ref['nickname'],new_id))
                conn.commit()
        if not ref and ref_nick:
            c.execute("SELECT id,nickname FROM users WHERE nickname=%s",(ref_nick,))
            ref=c.fetchone()
        reward=0
        if ref:
            c.execute("SELECT COUNT(*) as cnt FROM users WHERE referrer_id=%s OR referrer_nickname=%s",
                (ref['id'],ref['nickname']))
            ref_count=c.fetchone()['cnt'] or 0
            reward=compute_referral_reward(ref_count)
            if reward>0:
                c.execute("UPDATE users SET is_balance=is_balance+%s WHERE id=%s",(reward,ref['id']))
                conn.commit()
        return jsonify({'ok':True,'referrer':ref['nickname'] if ref else None,
            'referrer_id':ref['id'] if ref else None,'reward':reward})
    except psycopg2.IntegrityError:
        conn.rollback(); return jsonify({'error':'Логин уже занят'}),400
    finally: conn.close()

@app.route('/login', methods=['POST'])
def login():
    d=request.get_json() or {}
    login=(d.get('login') or '').strip(); password=d.get('password') or ''
    conn=get_db(); c=cur(conn)
    c.execute("SELECT * FROM users WHERE login=%s",(login,))
    row=c.fetchone()
    if not row or row['password']!=hash_password(password):
        conn.close(); return jsonify({'error':'Неверный логин или пароль'}),401
    token=generate_token()
    c.execute("UPDATE users SET token=%s,last_seen=%s WHERE id=%s",
        (token,int(time.time()*1000),row['id']))
    conn.commit()
    c.execute("SELECT * FROM users WHERE id=%s",(row['id'],))
    user=dict(c.fetchone()); conn.close(); user.pop('password',None)
    return jsonify({'ok':True,'user':user})

@app.route('/get-progress', methods=['GET'])
def get_progress():
    token=request.args.get('token')
    if not token: return jsonify({'found':False})
    conn=get_db(); c=cur(conn)
    c.execute("SELECT * FROM users WHERE token=%s",(token,))
    row=c.fetchone(); conn.close()
    if not row: return jsonify({'found':False})
    user=dict(row); user.pop('password',None)
    for f in ['is_tasks_done','claimed_quests','claimed_promos','upgrades','earned_promocodes']:
        try: user[f]=json.loads(user.get(f) or '[]')
        except: user[f]=[] if f!='upgrades' else {}
    return jsonify({'found':True,'user':user})

@app.route('/save-progress', methods=['POST'])
def save_progress():
    d=request.get_json() or {}; token=d.get('token')
    if not token: return jsonify({'error':'no token'}),400
    conn=get_db(); c=cur(conn); now_ms=int(time.time()*1000)
    c.execute("""UPDATE users SET score=%s,energy=%s,max_energy=%s,multiplier=%s,level=%s,
        total_taps=%s,is_balance=%s,daily_tap_limit=%s,taps_today=%s,last_tap_date=%s,
        sub_was_subscribed=%s,sub_was_punished=%s,is_tasks_done=%s,claimed_quests=%s,
        claimed_promos=%s,upgrades=%s,unlimited_until=%s,is_boost_mult_until=%s,
        is_auto_tap_until=%s,autotap_level=%s,passive_income=%s,wallet_balance=%s,
        wallet_total=%s,earned_promocodes=%s,last_seen=%s WHERE token=%s""",
        (d.get('score',0),d.get('energy',500),d.get('max_energy',500),d.get('multiplier',1),
         d.get('level',1),d.get('total_taps',0),d.get('is_balance',0),d.get('daily_tap_limit',20000),
         d.get('taps_today',0),d.get('last_tap_date'),
         int(d.get('sub_was_subscribed',False)),int(d.get('sub_was_punished',False)),
         json.dumps(d.get('is_tasks_done',[])),json.dumps(d.get('claimed_quests',[])),
         json.dumps(d.get('claimed_promos',[])),json.dumps(d.get('upgrades',{})),
         d.get('unlimited_until',0),d.get('is_boost_mult_until',0),d.get('is_auto_tap_until',0),
         d.get('autotap_level',0),d.get('passive_income',0),d.get('wallet_balance',0),
         d.get('wallet_total',0),json.dumps(d.get('earned_promocodes',[])),now_ms,token))
    conn.commit(); ch=c.rowcount; conn.close()
    if ch==0: return jsonify({'error':'user not found'}),401
    return jsonify({'ok':True})

@app.route('/claim-quest', methods=['POST'])
def claim_quest():
    d=request.get_json() or {}; token=d.get('token'); qid=d.get('quest_id')
    reward=int(d.get('reward',0))
    if not token or not qid: return jsonify({'success':False,'error':'bad params'}),400
    conn=get_db(); c=cur(conn)
    c.execute("SELECT claimed_quests,score FROM users WHERE token=%s",(token,))
    row=c.fetchone()
    if not row: conn.close(); return jsonify({'success':False,'error':'user not found'}),401
    try: claimed=json.loads(row['claimed_quests'] or '[]')
    except: claimed=[]
    if qid in claimed: conn.close(); return jsonify({'success':False,'error':'Уже забрано'}),400
    claimed.append(qid); new_score=(row['score'] or 0)+reward
    c.execute("UPDATE users SET claimed_quests=%s,score=%s WHERE token=%s",
        (json.dumps(claimed),new_score,token))
    conn.commit(); conn.close()
    return jsonify({'success':True,'new_score':new_score,'claimed':claimed})

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    d=request.get_json() or {}; token=d.get('token'); score=d.get('score',0)
    if not token: return jsonify({'error':'no token'}),400
    conn=get_db(); c=cur(conn)
    c.execute("UPDATE users SET last_seen=%s,score=%s WHERE token=%s",
        (int(time.time()*1000),score,token))
    conn.commit(); ch=c.rowcount; conn.close()
    if ch==0: return jsonify({'error':'user not found'}),401
    return jsonify({'ok':True})

@app.route('/top', methods=['GET'])
def get_top():
    limit=max(1,min(int(request.args.get('limit',100)),100))
    now_ms=int(time.time()*1000)
    conn=get_db(); c=cur(conn)
    c.execute("""SELECT nickname,score,last_seen,avatar_data FROM users
        WHERE nickname IS NOT NULL AND nickname!='' ORDER BY score DESC,last_seen ASC LIMIT %s""",(limit,))
    rows=c.fetchall()
    c.execute("SELECT COUNT(*) as cnt FROM users WHERE nickname IS NOT NULL AND nickname!=''")
    total=c.fetchone()['cnt']
    c.execute("""SELECT COUNT(*) as cnt FROM users WHERE nickname IS NOT NULL
        AND nickname!='' AND last_seen>%s""",(now_ms-ONLINE_WINDOW_MS,))
    online=c.fetchone()['cnt']; conn.close()
    players=[{'nickname':r['nickname'],'score':r['score'] or 0,
        'last_seen':r['last_seen'] or 0,'avatar_data':r['avatar_data']} for r in rows]
    return jsonify({'success':True,'players':players,'total':total,
        'online':online,'offline':total-online})

@app.route('/my-id', methods=['GET'])
def my_id():
    token=request.args.get('token')
    if not token: return jsonify({'success':False}),400
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id,nickname FROM users WHERE token=%s",(token,))
    row=c.fetchone(); conn.close()
    if not row: return jsonify({'success':False}),401
    return jsonify({'success':True,'id':row['id'],'nickname':row['nickname']})

@app.route('/my-balance', methods=['GET'])
def my_balance():
    token=request.args.get('token')
    if not token: return jsonify({'success':False,'is_balance':0})
    conn=get_db(); c=cur(conn)
    c.execute("SELECT is_balance FROM users WHERE token=%s",(token,))
    row=c.fetchone(); conn.close()
    if not row: return jsonify({'success':False,'is_balance':0})
    return jsonify({'success':True,'is_balance':row['is_balance'] or 0})

@app.route('/referrals/pending', methods=['GET'])
def referrals_pending():
    token=request.args.get('token')
    if not token: return jsonify({'success':False,'pending':[],'my_id':None})
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id,nickname,referral_seen_id FROM users WHERE token=%s",(token,))
    me=c.fetchone()
    if not me: conn.close(); return jsonify({'success':False,'pending':[],'my_id':None})
    seen_id=me['referral_seen_id'] or 0
    c.execute("""SELECT id,nickname FROM users WHERE (referrer_id=%s OR referrer_nickname=%s)
        AND id>%s ORDER BY id ASC""",(me['id'],me['nickname'],seen_id))
    rows=c.fetchall(); conn.close()
    pending=[{'id':r['id'],'nickname':r['nickname']} for r in rows]
    return jsonify({'success':True,'pending':pending,'count':len(pending),'my_id':me['id']})

@app.route('/referrals/mark-seen', methods=['POST'])
def referrals_mark_seen():
    d=request.get_json() or {}; token=d.get('token'); last_id=int(d.get('last_id',0))
    if not token or last_id<=0: return jsonify({'success':False,'error':'bad params'}),400
    conn=get_db(); c=cur(conn)
    c.execute("""UPDATE users SET referral_seen_id=CASE
        WHEN referral_seen_id IS NULL OR referral_seen_id<%s THEN %s
        ELSE referral_seen_id END WHERE token=%s""",(last_id,last_id,token))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/my-referrals', methods=['GET'])
def my_referrals():
    token=request.args.get('token')
    if not token: return jsonify({'success':False,'referrals':[],'count':0})
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id,nickname FROM users WHERE token=%s",(token,))
    me=c.fetchone()
    if not me: conn.close(); return jsonify({'success':False,'referrals':[],'count':0})
    c.execute("""SELECT nickname FROM users WHERE referrer_id=%s OR referrer_nickname=%s
        ORDER BY id ASC""",(me['id'],me['nickname']))
    refs=[{'nickname':r['nickname']} for r in c.fetchall()]
    conn.close(); return jsonify({'success':True,'referrals':refs,'count':len(refs)})

@app.route('/claim-referral', methods=['POST'])
def claim_referral():
    d=request.get_json() or {}; token=d.get('token'); amount=int(d.get('amount',0))
    if not token or amount<=0: return jsonify({'success':False,'error':'bad params'}),400
    conn=get_db(); c=cur(conn)
    c.execute("UPDATE users SET is_balance=is_balance+%s WHERE token=%s",(amount,token))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/check-sub', methods=['GET'])
def check_sub(): return jsonify({'subscribed':True})

def _get_user_by_token(token):
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id,nickname,gender,region,role FROM users WHERE token=%s",(token,))
    u=c.fetchone(); conn.close(); return u

def _get_user_full_by_token(token):
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id,nickname,gender FROM users WHERE token=%s",(token,))
    u=c.fetchone(); conn.close(); return u

def _is_admin(token):
    u=_get_user_by_token(token); return u and u.get('role')=='admin'

@app.route('/send-message', methods=['POST'])
def send_message():
    try:
        d=request.get_json() or {}; token=d.get('token'); text=(d.get('text') or '').strip()
        if not token or not text: return jsonify({'success':False,'error':'Пустое сообщение'}),400
        if len(text)>500: return jsonify({'success':False,'error':'Слишком длинное'}),400
        u=_get_user_by_token(token)
        if not u: return jsonify({'success':False,'error':'Пользователь не найден'}),401
        region=(u['region'] or '').strip().lower()
        if region!='ингушетия': return jsonify({'success':False,'error':'Чат только для Ингушетии'}),403
        gender=(u['gender'] or 'male').strip().lower()
        if gender not in ('male','female'): gender='male'
        conn=get_db(); c=cur(conn)
        c.execute("""INSERT INTO messages (user_id,nickname,gender,region,text,created_at)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (u['id'],u['nickname'],gender,u['region'],text,int(time.time()*1000)))
        conn.commit(); conn.close(); return jsonify({'success':True})
    except Exception as e:
        print("[send-message]",e); traceback.print_exc()
        return jsonify({'success':False,'error':'Ошибка сервера'}),500

@app.route('/get-messages', methods=['GET'])
def get_messages():
    try:
        token=request.args.get('token','')
        if not token: return jsonify({'success':False,'error':'Не авторизован','messages':[]})
        u=_get_user_by_token(token)
        if not u: return jsonify({'success':False,'error':'Не авторизован','messages':[]})
        my_gender=(u['gender'] or 'male').strip().lower()
        if my_gender not in ('male','female'): my_gender='male'
        conn=get_db(); c=cur(conn)
        c.execute("""SELECT id,nickname,gender,text,created_at FROM messages
            WHERE gender=%s ORDER BY id DESC LIMIT 100""",(my_gender,))
        rows=c.fetchall(); conn.close()
        msgs=[dict(r) for r in rows]; msgs.reverse()
        return jsonify({'success':True,'messages':msgs,'chat':my_gender})
    except Exception as e:
        print("[get-messages]",e); traceback.print_exc()
        return jsonify({'success':False,'error':'Ошибка сервера','messages':[]}),500

@app.route('/delete-message', methods=['POST'])
def delete_message():
    d=request.get_json() or {}; token=d.get('token'); mid=d.get('message_id')
    if not token or not mid: return jsonify({'success':False,'error':'bad params'}),400
    if not _is_admin(token): return jsonify({'success':False,'error':'Только для админов'}),403
    conn=get_db(); c=cur(conn)
    c.execute("DELETE FROM messages WHERE id=%s",(mid,))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/edit-message', methods=['POST'])
def edit_message():
    d=request.get_json() or {}; token=d.get('token'); mid=d.get('message_id')
    nt=(d.get('text') or '').strip()
    if not token or not mid or not nt: return jsonify({'success':False,'error':'bad params'}),400
    if not _is_admin(token): return jsonify({'success':False,'error':'Только для админов'}),403
    conn=get_db(); c=cur(conn)
    c.execute("UPDATE messages SET text=%s WHERE id=%s",(nt,mid))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/pin-message', methods=['POST'])
def pin_message():
    d=request.get_json() or {}; token=d.get('token'); mid=d.get('message_id')
    if not token or not mid: return jsonify({'success':False,'error':'bad params'}),400
    if not _is_admin(token): return jsonify({'success':False,'error':'Только для админов'}),403
    return jsonify({'success':True})

@app.route('/chat-stats', methods=['GET'])
def chat_stats():
    token=request.args.get('token')
    if not token: return jsonify({'success':False}),400
    conn=get_db(); c=cur(conn)
    c.execute("SELECT COUNT(*) as cnt FROM users WHERE nickname IS NOT NULL AND nickname!=''")
    total=c.fetchone()['cnt']
    c.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM messages")
    chatters=c.fetchone()['cnt']
    now_ms=int(time.time()*1000)
    c.execute("SELECT COUNT(*) as cnt FROM users WHERE last_seen>%s",(now_ms-ONLINE_WINDOW_MS,))
    online=c.fetchone()['cnt']
    c.execute("""SELECT nickname,MAX(created_at) as last_time FROM messages
        GROUP BY nickname,user_id ORDER BY last_time DESC LIMIT 50""")
    history=[{'nickname':r['nickname'],'last_time':r['last_time']} for r in c.fetchall()]
    conn.close()
    return jsonify({'success':True,'total_players':total,'unique_chatters':chatters,
        'online_now':online,'history':history})

@app.route('/groups/create', methods=['POST'])
def groups_create():
    d=request.get_json() or {}; token=d.get('token'); name=(d.get('name') or '').strip()
    if not token or not name: return jsonify({'success':False,'error':'bad params'}),400
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    code=secrets.token_urlsafe(8); now_ms=int(time.time()*1000)
    conn=get_db(); c=cur(conn)
    c.execute("""INSERT INTO group_chats (name,owner_id,invite_code,created_at)
        VALUES (%s,%s,%s,%s) RETURNING id""",(name,u['id'],code,now_ms))
    cid=c.fetchone()['id']
    c.execute("INSERT INTO group_members (chat_id,user_id,joined_at) VALUES (%s,%s,%s)",
        (cid,u['id'],now_ms))
    conn.commit(); conn.close()
    return jsonify({'success':True,'chat_id':cid,'invite_code':code,'name':name})

@app.route('/groups/list', methods=['GET'])
def groups_list():
    token=request.args.get('token')
    if not token: return jsonify({'success':False,'chats':[]})
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'chats':[]})
    conn=get_db(); c=cur(conn)
    c.execute("""SELECT gc.id,gc.name,gc.invite_code,gc.owner_id,gc.created_at
        FROM group_chats gc JOIN group_members gm ON gm.chat_id=gc.id
        WHERE gm.user_id=%s ORDER BY gc.created_at DESC""",(u['id'],))
    chats=[{'id':r['id'],'name':r['name'],'invite_code':r['invite_code'],
        'owner_id':r['owner_id'],'is_owner':r['owner_id']==u['id']} for r in c.fetchall()]
    conn.close(); return jsonify({'success':True,'chats':chats})

@app.route('/groups/join', methods=['POST'])
def groups_join():
    d=request.get_json() or {}; token=d.get('token'); code=(d.get('invite_code') or '').strip()
    if not token or not code: return jsonify({'success':False,'error':'bad params'}),400
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id,name FROM group_chats WHERE invite_code=%s",(code,))
    chat=c.fetchone()
    if not chat: conn.close(); return jsonify({'success':False,'error':'Чат не найден'}),404
    c.execute("SELECT id FROM group_members WHERE chat_id=%s AND user_id=%s",(chat['id'],u['id']))
    if c.fetchone():
        conn.close(); return jsonify({'success':True,'chat_id':chat['id'],'name':chat['name'],'already':True})
    c.execute("INSERT INTO group_members (chat_id,user_id,joined_at) VALUES (%s,%s,%s)",
        (chat['id'],u['id'],int(time.time()*1000)))
    conn.commit(); conn.close()
    return jsonify({'success':True,'chat_id':chat['id'],'name':chat['name']})

@app.route('/groups/leave', methods=['POST'])
def groups_leave():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id')
    if not token or not cid: return jsonify({'success':False,'error':'bad params'}),400
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("DELETE FROM group_members WHERE chat_id=%s AND user_id=%s",(cid,u['id']))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/groups/add-member', methods=['POST'])
def groups_add_member():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id')
    nick=(d.get('nickname') or '').strip()
    if not token or not cid or not nick: return jsonify({'success':False,'error':'bad params'}),400
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("SELECT owner_id FROM group_chats WHERE id=%s",(cid,))
    chat=c.fetchone()
    if not chat: conn.close(); return jsonify({'success':False,'error':'Чат не найден'}),404
    if chat['owner_id']!=u['id']:
        conn.close(); return jsonify({'success':False,'error':'Только владелец может добавлять'}),403
    c.execute("SELECT id,nickname FROM users WHERE nickname=%s",(nick,))
    t=c.fetchone()
    if not t: conn.close(); return jsonify({'success':False,'error':'Игрок не найден'}),404
    c.execute("SELECT id FROM group_members WHERE chat_id=%s AND user_id=%s",(cid,t['id']))
    if c.fetchone(): conn.close(); return jsonify({'success':False,'error':'Уже в чате'}),400
    c.execute("INSERT INTO group_members (chat_id,user_id,joined_at) VALUES (%s,%s,%s)",
        (cid,t['id'],int(time.time()*1000)))
    conn.commit(); conn.close()
    return jsonify({'success':True,'nickname':t['nickname']})

@app.route('/groups/members', methods=['GET'])
def groups_members():
    token=request.args.get('token'); cid=request.args.get('chat_id')
    if not token or not cid: return jsonify({'success':False,'members':[]})
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'members':[]})
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id FROM group_members WHERE chat_id=%s AND user_id=%s",(cid,u['id']))
    if not c.fetchone(): conn.close(); return jsonify({'success':False,'error':'Нет доступа'}),403
    c.execute("SELECT owner_id FROM group_chats WHERE id=%s",(cid,))
    ch=c.fetchone(); owner_id=ch['owner_id'] if ch else None
    c.execute("""SELECT u.id,u.nickname,u.gender,gm.joined_at,gm.is_admin,
        gm.can_delete_messages,gm.can_kick,gm.can_pin,gm.can_edit
        FROM group_members gm JOIN users u ON u.id=gm.user_id
        WHERE gm.chat_id=%s ORDER BY gm.joined_at ASC""",(cid,))
    members=[{'id':r['id'],'nickname':r['nickname'],'gender':r['gender'],
        'joined_at':r['joined_at'],'is_owner':r['id']==owner_id,
        'is_admin':bool(r['is_admin']),'can_delete_messages':bool(r['can_delete_messages']),
        'can_kick':bool(r['can_kick']),'can_pin':bool(r['can_pin']),
        'can_edit':bool(r['can_edit'])} for r in c.fetchall()]
    conn.close()
    return jsonify({'success':True,'members':members,'owner_id':owner_id})

@app.route('/groups/send', methods=['POST'])
def groups_send():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id')
    text=(d.get('text') or '').strip()
    if not token or not cid or not text: return jsonify({'success':False,'error':'bad params'}),400
    if len(text)>500: return jsonify({'success':False,'error':'Слишком длинное'}),400
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id FROM group_members WHERE chat_id=%s AND user_id=%s",(cid,u['id']))
    if not c.fetchone(): conn.close(); return jsonify({'success':False,'error':'Нет доступа'}),403
    c.execute("""INSERT INTO group_messages (chat_id,user_id,nickname,text,created_at)
        VALUES (%s,%s,%s,%s,%s)""",(cid,u['id'],u['nickname'],text,int(time.time()*1000)))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/groups/messages', methods=['GET'])
def groups_messages():
    token=request.args.get('token'); cid=request.args.get('chat_id')
    if not token or not cid: return jsonify({'success':False,'messages':[]})
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'messages':[]})
    conn=get_db(); c=cur(conn)
    c.execute("SELECT id FROM group_members WHERE chat_id=%s AND user_id=%s",(cid,u['id']))
    if not c.fetchone(): conn.close(); return jsonify({'success':False,'error':'Нет доступа','messages':[]}),403
    c.execute("""SELECT id,user_id,nickname,text,created_at FROM group_messages
        WHERE chat_id=%s ORDER BY id DESC LIMIT 100""",(cid,))
    rows=c.fetchall()
    c.execute("SELECT owner_id FROM group_chats WHERE id=%s",(cid,))
    cr=c.fetchone(); owner_id=cr['owner_id'] if cr else None
    c.execute("""SELECT is_admin,can_delete_messages,can_kick,can_pin,can_edit
        FROM group_members WHERE chat_id=%s AND user_id=%s""",(cid,u['id']))
    mp=c.fetchone(); conn.close()
    msgs=[dict(r) for r in rows]; msgs.reverse()
    return jsonify({'success':True,'messages':msgs,'owner_id':owner_id,
        'my_perms':{'is_owner':u['id']==owner_id,
            'is_admin':bool(mp['is_admin']) if mp else False,
            'can_delete_messages':bool(mp['can_delete_messages']) if mp else False,
            'can_kick':bool(mp['can_kick']) if mp else False,
            'can_pin':bool(mp['can_pin']) if mp else False,
            'can_edit':bool(mp['can_edit']) if mp else False}})

def _check_group_perm(token,cid,perm_name):
    u=_get_user_full_by_token(token)
    if not u: return None,False,False
    conn=get_db(); c=cur(conn)
    c.execute("SELECT owner_id FROM group_chats WHERE id=%s",(cid,))
    ch=c.fetchone()
    if not ch: conn.close(); return u,False,False
    if ch['owner_id']==u['id']: conn.close(); return u,True,True
    c.execute(f"SELECT {perm_name} FROM group_members WHERE chat_id=%s AND user_id=%s",(cid,u['id']))
    row=c.fetchone(); conn.close()
    return u,False,bool(row and row[perm_name])

@app.route('/groups/delete', methods=['POST'])
def groups_delete():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id')
    if not token or not cid: return jsonify({'success':False,'error':'bad params'}),400
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("SELECT owner_id FROM group_chats WHERE id=%s",(cid,))
    ch=c.fetchone()
    if not ch: conn.close(); return jsonify({'success':False,'error':'Чат не найден'}),404
    if ch['owner_id']!=u['id']:
        conn.close(); return jsonify({'success':False,'error':'Только владелец'}),403
    c.execute("DELETE FROM group_messages WHERE chat_id=%s",(cid,))
    c.execute("DELETE FROM group_members WHERE chat_id=%s",(cid,))
    c.execute("DELETE FROM group_chats WHERE id=%s",(cid,))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/groups/kick', methods=['POST'])
def groups_kick():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id'); uid=d.get('user_id')
    if not token or not cid or not uid: return jsonify({'success':False,'error':'bad params'}),400
    u,is_owner,has_perm=_check_group_perm(token,cid,'can_kick')
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    if not (is_owner or has_perm): return jsonify({'success':False,'error':'Нет прав'}),403
    conn=get_db(); c=cur(conn)
    c.execute("SELECT owner_id FROM group_chats WHERE id=%s",(cid,))
    ch=c.fetchone()
    if ch and ch['owner_id']==uid:
        conn.close(); return jsonify({'success':False,'error':'Нельзя кикнуть владельца'}),403
    c.execute("DELETE FROM group_members WHERE chat_id=%s AND user_id=%s",(cid,uid))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/groups/message/delete', methods=['POST'])
def groups_message_delete():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id'); mid=d.get('message_id')
    if not token or not cid or not mid: return jsonify({'success':False,'error':'bad params'}),400
    u,is_owner,has_perm=_check_group_perm(token,cid,'can_delete_messages')
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("SELECT user_id FROM group_messages WHERE id=%s AND chat_id=%s",(mid,cid))
    msg=c.fetchone()
    if not msg: conn.close(); return jsonify({'success':False,'error':'Сообщение не найдено'}),404
    if not (is_owner or has_perm or msg['user_id']==u['id']):
        conn.close(); return jsonify({'success':False,'error':'Нет прав'}),403
    c.execute("DELETE FROM group_messages WHERE id=%s",(mid,))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/groups/message/edit', methods=['POST'])
def groups_message_edit():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id')
    mid=d.get('message_id'); nt=(d.get('text') or '').strip()
    if not token or not cid or not mid or not nt: return jsonify({'success':False,'error':'bad params'}),400
    if len(nt)>500: return jsonify({'success':False,'error':'Слишком длинное'}),400
    u,is_owner,has_perm=_check_group_perm(token,cid,'can_edit')
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("SELECT user_id FROM group_messages WHERE id=%s AND chat_id=%s",(mid,cid))
    msg=c.fetchone()
    if not msg: conn.close(); return jsonify({'success':False,'error':'Сообщение не найдено'}),404
    if not (is_owner or has_perm or msg['user_id']==u['id']):
        conn.close(); return jsonify({'success':False,'error':'Нет прав'}),403
    c.execute("UPDATE group_messages SET text=%s WHERE id=%s",(nt,mid))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/groups/set-admin', methods=['POST'])
def groups_set_admin():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id'); uid=d.get('user_id')
    is_admin=1 if d.get('is_admin') else 0; perms=d.get('perms') or {}
    if not token or not cid or not uid: return jsonify({'success':False,'error':'bad params'}),400
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("SELECT owner_id FROM group_chats WHERE id=%s",(cid,))
    ch=c.fetchone()
    if not ch: conn.close(); return jsonify({'success':False,'error':'Чат не найден'}),404
    if ch['owner_id']!=u['id']:
        conn.close(); return jsonify({'success':False,'error':'Только владелец назначает'}),403
    c.execute("""UPDATE group_members SET is_admin=%s,can_delete_messages=%s,
        can_kick=%s,can_pin=%s,can_edit=%s WHERE chat_id=%s AND user_id=%s""",
        (is_admin,1 if perms.get('can_delete_messages') else 0,
         1 if perms.get('can_kick') else 0,1 if perms.get('can_pin') else 0,
         1 if perms.get('can_edit') else 0,cid,uid))
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/groups/rename', methods=['POST'])
def groups_rename():
    d=request.get_json() or {}; token=d.get('token'); cid=d.get('chat_id')
    nn=(d.get('name') or '').strip()
    if not token or not cid or not nn: return jsonify({'success':False,'error':'bad params'}),400
    u=_get_user_full_by_token(token)
    if not u: return jsonify({'success':False,'error':'user not found'}),401
    conn=get_db(); c=cur(conn)
    c.execute("SELECT owner_id FROM group_chats WHERE id=%s",(cid,))
    ch=c.fetchone()
    if not ch: conn.close(); return jsonify({'success':False,'error':'Чат не найден'}),404
    if ch['owner_id']!=u['id']: conn.close(); return jsonify({'success':False,'error':'Только владелец'}),403
    c.execute("UPDATE group_chats SET name=%s WHERE id=%s",(nn,cid))
    conn.commit(); conn.close(); return jsonify({'success':True,'name':nn})

# ==================== ИГРЫ / СТАВКИ ====================
GAME_CONFIG = {
    'roulette': {'win_chance': 0.48, 'multiplier': 2.0,  'name': 'Рулетка'},
    'dice':     {'win_chance': 0.45, 'multiplier': 2.2,  'name': 'Кубик'},
    'coin':     {'win_chance': 0.50, 'multiplier': 1.9,  'name': 'Монетка'},
    'slots':    {'win_chance': 0.30, 'multiplier': 3.0,  'name': 'Слоты'},
    'basket':   {'win_chance': 0.40, 'multiplier': 2.4,  'name': 'Баскетбол'},
    'mine':     {'win_chance': 0.35, 'multiplier': 2.8,  'name': 'Майнинг'},
    'wheel':    {'win_chance': 0.42, 'multiplier': 2.3,  'name': 'Колесо'},
    'darts':    {'win_chance': 0.38, 'multiplier': 2.5,  'name': 'Дартс'},
    'fishing':  {'win_chance': 0.44, 'multiplier': 2.2,  'name': 'Рыбалка'},
    'cards':    {'win_chance': 0.40, 'multiplier': 2.4,  'name': 'Карты'},
    'shells':   {'win_chance': 0.33, 'multiplier': 2.9,  'name': 'Фокусник'},
    'craps':    {'win_chance': 0.37, 'multiplier': 2.6,  'name': 'Кости'},
    'archery':  {'win_chance': 0.36, 'multiplier': 2.7,  'name': 'Лучник'},
    'penalty':  {'win_chance': 0.42, 'multiplier': 2.3,  'name': 'Пенальти'},
    'basket3':  {'win_chance': 0.28, 'multiplier': 3.3,  'name': '3-очковый'},
    'mines':    {'win_chance': 0.32, 'multiplier': 3.1,  'name': 'Сапёр'},
}
MIN_BET = 1000
MAX_BET = 1000000

@app.route('/games/list', methods=['GET'])
def games_list():
    return jsonify({'success': True, 'games': [
        {'id': k, 'name': v['name'], 'win_chance': v['win_chance'],
         'multiplier': v['multiplier'], 'min_bet': MIN_BET, 'max_bet': MAX_BET}
        for k, v in GAME_CONFIG.items()
    ]})

@app.route('/games/play', methods=['POST'])
def games_play():
    d = request.get_json() or {}
    token = d.get('token')
    game_id = (d.get('game_id') or '').strip()
    try:
        bet = int(d.get('bet', 0))
    except:
        return jsonify({'success': False, 'error': 'Некорректная ставка'}), 400

    if not token or not game_id:
        return jsonify({'success': False, 'error': 'bad params'}), 400
    if game_id not in GAME_CONFIG:
        return jsonify({'success': False, 'error': 'Игра не найдена'}), 404
    if bet < MIN_BET or bet > MAX_BET:
        return jsonify({'success': False, 'error': f'Ставка от {MIN_BET} до {MAX_BET}'}), 400

    conn = get_db(); c = cur(conn)
    c.execute("SELECT id, nickname, score FROM users WHERE token=%s", (token,))
    u = c.fetchone()
    if not u:
        conn.close(); return jsonify({'success': False, 'error': 'Игрок не найден'}), 401

    current_score = u['score'] or 0
    if current_score < bet:
        conn.close(); return jsonify({'success': False, 'error': 'Недостаточно очков', 'score': current_score}), 400

    cfg = GAME_CONFIG[game_id]
    win = secrets.randbelow(10000) < int(cfg['win_chance'] * 10000)

    if win:
        payout = int(bet * cfg['multiplier'])
        new_score = current_score - bet + payout
    else:
        payout = 0
        new_score = current_score - bet

    if new_score < 0:
        new_score = 0

    c.execute("UPDATE users SET score=%s, last_seen=%s WHERE id=%s",
              (new_score, int(time.time()*1000), u['id']))
    c.execute("""INSERT INTO game_bets (user_id, nickname, game_id, bet, win, payout, multiplier, created_at)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
              (u['id'], u['nickname'], game_id, bet, win, payout, cfg['multiplier'], int(time.time()*1000)))
    conn.commit(); conn.close()

    return jsonify({
        'success': True, 'win': win, 'bet': bet, 'payout': payout,
        'new_score': new_score, 'multiplier': cfg['multiplier'],
        'game_id': game_id, 'game_name': cfg['name']
    })

@app.route('/games/history', methods=['GET'])
def games_history():
    token = request.args.get('token')
    limit = max(1, min(int(request.args.get('limit', 20)), 50))
    if not token:
        return jsonify({'success': False, 'bets': []})
    conn = get_db(); c = cur(conn)
    c.execute("SELECT id FROM users WHERE token=%s", (token,))
    u = c.fetchone()
    if not u:
        conn.close(); return jsonify({'success': False, 'bets': []})
    c.execute("""SELECT game_id, bet, win, payout, multiplier, created_at
                 FROM game_bets WHERE user_id=%s ORDER BY id DESC LIMIT %s""",
              (u['id'], limit))
    rows = c.fetchall(); conn.close()
    return jsonify({'success': True, 'bets': [dict(r) for r in rows]})

@app.route('/games/top-wins', methods=['GET'])
def games_top_wins():
    limit = max(1, min(int(request.args.get('limit', 10)), 20))
    conn = get_db(); c = cur(conn)
    c.execute("""SELECT nickname, game_id, bet, payout, multiplier, created_at
                 FROM game_bets WHERE win=TRUE ORDER BY payout DESC LIMIT %s""", (limit,))
    rows = c.fetchall(); conn.close()
    return jsonify({'success': True, 'wins': [dict(r) for r in rows]})

@app.route('/')
def index(): return jsonify({'status':'ok','message':'IngSoft API v2'})

init_db()

if __name__ == '__main__':
    port=int(os.getenv('PORT',5000))
    app.run(host='0.0.0.0',port=port)
