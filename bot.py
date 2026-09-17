import time

# ============ ДОБАВИТЬ В bot.py ============

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    """Обновляет last_seen игрока — кто зашёл, тот онлайн"""
    data = request.get_json() or {}
    token = data.get('token')
    score = data.get('score', 0)
    if not token:
        return jsonify({'error': 'no token'}), 400
    
    conn = sqlite3.connect('ingsoft.db')
    c = conn.cursor()
    # Проверяем есть ли столбец last_seen
    try:
        c.execute("SELECT last_seen FROM users WHERE token = ?", (token,))
        row = c.fetchone()
        if row:
            c.execute("UPDATE users SET last_seen = ?, score = ? WHERE token = ?",
                      (int(time.time() * 1000), score, token))
        else:
            # Токена нет — возможно, ищем по другому полю
            return jsonify({'error': 'user not found'}), 401
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/top', methods=['GET'])
def get_top():
    """Возвращает топ игроков + онлайн/оффлайн статистику"""
    limit = int(request.args.get('limit', 100))
    now_ms = int(time.time() * 1000)
    online_window_ms = 5 * 60 * 1000  # 5 минут = онлайн
    
    conn = sqlite3.connect('ingsoft.db')
    c = conn.cursor()
    
    try:
        # Получаем всех игроков с их score и last_seen
        c.execute("""
            SELECT nickname, score, last_seen, avatar_data
            FROM users
            WHERE nickname IS NOT NULL
            ORDER BY score DESC, last_seen ASC
            LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        
        # Общее количество
        c.execute("SELECT COUNT(*) FROM users WHERE nickname IS NOT NULL")
        total = c.fetchone()[0]
        
        # Онлайн/Оффлайн
        c.execute("SELECT COUNT(*) FROM users WHERE nickname IS NOT NULL AND last_seen > ?",
                  (now_ms - online_window_ms,))
        online = c.fetchone()[0]
        offline = total - online
        
        players = [{
            'nickname': row[0],
            'score': row[1] or 0,
            'last_seen': row[2] or 0,
            'avatar_data': row[3] if len(row) > 3 else None
        } for row in rows]
        
        conn.close()
        return jsonify({
            'success': True,
            'players': players,
            'total': total,
            'online': online,
            'offline': offline
        })
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)}), 500


# Обнови /save-progress чтобы обновлял last_seen тоже.
# НАЙДИ у себя @app.route('/save-progress', ...) и добавь в SQL строку:
# last_seen = <текущее время в мс>
