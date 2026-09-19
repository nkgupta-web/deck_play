import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, List, Optional, Tuple
import config

def get_db_connection():
    # Neon cloud database connection
    return psycopg2.connect(config.DATABASE_URL, sslmode="require")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Existing Call 31 Stats Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS call31_stats (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            games INT DEFAULT 0,
            wins INT DEFAULT 0,
            round_wins INT DEFAULT 0,
            rounds_survived INT DEFAULT 0,
            exact_31 INT DEFAULT 0,
            exact_30_5 INT DEFAULT 0,
            current_streak INT DEFAULT 0,
            best_streak INT DEFAULT 0,
            ex_1 INT DEFAULT 0,
            ex_all INT DEFAULT 0,
            calls INT DEFAULT 0,
            passes INT DEFAULT 0,
            lives_lost INT DEFAULT 0,
            joint_wins INT DEFAULT 0
        );
    """)

    # Safe column migration agar purani table me joint_wins na ho
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'call31_stats' AND column_name = 'joint_wins';
    """)
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE call31_stats ADD COLUMN joint_wins INT DEFAULT 0;")

    # 2. Bot Admins Table (For /addadmin, /removeadmin, /admins)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            added_by BIGINT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. Registered Groups Table (For /groups, /announce, bot added/removed events)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registered_groups (
            chat_id BIGINT PRIMARY KEY,
            title TEXT,
            invite_link TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            added_by BIGINT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            removed_at TIMESTAMP
        );
    """)

    # 4. Bot Settings Table (For /maintenance persistence)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    cursor.execute("INSERT INTO bot_settings (key, value) VALUES ('maintenance', 'false') ON CONFLICT (key) DO NOTHING;")

    # 5. Admin Action Logs Table (Internal audit logs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id SERIAL PRIMARY KEY,
            admin_id BIGINT,
            admin_name TEXT,
            action TEXT,
            target TEXT,
            old_value TEXT,
            new_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    cursor.close()
    conn.close()

# ━━━━━━━━━━━━━━━━━━━━
# ADMIN & ROLE MANAGEMENT HELPERS
# ━━━━━━━━━━━━━━━━━━━━

def is_owner(user_id: int) -> bool:
    return user_id == config.OWNER_ID

def is_admin(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM bot_admins WHERE user_id = %s;", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return bool(row)

def add_admin(user_id: int, username: str, added_by: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bot_admins (user_id, username, added_by)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username;
    """, (user_id, username, added_by))
    conn.commit()
    cursor.close()
    conn.close()
    return True

def remove_admin(user_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bot_admins WHERE user_id = %s;", (user_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return deleted

def get_all_admins() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM bot_admins ORDER BY added_at ASC;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

# ━━━━━━━━━━━━━━━━━━━━
# MAINTENANCE HELPERS
# ━━━━━━━━━━━━━━━━━━━━

def get_maintenance_status() -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'maintenance';")
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0].lower() == "true" if row else False

def set_maintenance_status(status: bool):
    conn = get_db_connection()
    cursor = conn.cursor()
    val = "true" if status else "false"
    cursor.execute("UPDATE bot_settings SET value = %s WHERE key = 'maintenance';", (val,))
    conn.commit()
    cursor.close()
    conn.close()

# ━━━━━━━━━━━━━━━━━━━━
# ADMIN ACTION LOGGING
# ━━━━━━━━━━━━━━━━━━━━

def log_admin_action(admin_id: int, admin_name: str, action: str, target: str, old_val: str, new_val: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO admin_logs (admin_id, admin_name, action, target, old_value, new_value)
        VALUES (%s, %s, %s, %s, %s, %s);
    """, (admin_id, admin_name, action, target, str(old_val), str(new_val)))
    conn.commit()
    cursor.close()
    conn.close()

# ━━━━━━━━━━━━━━━━━━━━
# GROUP & BROADCAST HELPERS
# ━━━━━━━━━━━━━━━━━━━━

def register_group(chat_id: int, title: str, invite_link: Optional[str], added_by: Optional[int]):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO registered_groups (chat_id, title, invite_link, is_active, added_by, added_at)
        VALUES (%s, %s, %s, TRUE, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (chat_id) DO UPDATE 
        SET title = EXCLUDED.title,
            invite_link = COALESCE(EXCLUDED.invite_link, registered_groups.invite_link),
            is_active = TRUE,
            removed_at = NULL;
    """, (chat_id, title, invite_link, added_by))
    conn.commit()
    cursor.close()
    conn.close()

def unregister_group(chat_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE registered_groups 
        SET is_active = FALSE, removed_at = CURRENT_TIMESTAMP 
        WHERE chat_id = %s;
    """, (chat_id,))
    conn.commit()
    cursor.close()
    conn.close()

def get_registered_groups() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM registered_groups ORDER BY added_at DESC;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

def get_all_registered_users() -> List[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM call31_stats;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [r[0] for r in rows]

# ━━━━━━━━━━━━━━━━━━━━
# ADMIN STATS EDIT & RESET HELPERS
# ━━━━━━━━━━━━━━━━━━━━

def set_player_single_stat(user_id: int, stat_key: str, new_value: int):
    allowed_fields = {
        "games", "wins", "joint_wins", "rounds_survived", 
        "exact_31", "exact_30_5", "best_streak", 
        "ex_1", "ex_all", "passes", "lives_lost"
    }
    if stat_key not in allowed_fields:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE call31_stats SET {stat_key} = %s WHERE user_id = %s;", (new_value, user_id))
    conn.commit()
    cursor.close()
    conn.close()

def set_player_all_stats(user_id: int, stats: Dict[str, int]):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE call31_stats SET
            games = %s,
            wins = %s,
            joint_wins = %s,
            rounds_survived = %s,
            exact_31 = %s,
            exact_30_5 = %s,
            best_streak = %s,
            ex_1 = %s,
            passes = %s,
            lives_lost = %s
        WHERE user_id = %s;
    """, (
        stats["games"], stats["wins"], stats["joint_wins"], stats["rounds_survived"],
        stats["exact_31"], stats["exact_30_5"], stats["best_streak"], stats["ex_1"],
        stats["passes"], stats["lives_lost"], user_id
    ))
    conn.commit()
    cursor.close()
    conn.close()

def reset_player_stats(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE call31_stats SET
            games = 0,
            wins = 0,
            round_wins = 0,
            rounds_survived = 0,
            exact_31 = 0,
            exact_30_5 = 0,
            current_streak = 0,
            best_streak = 0,
            ex_1 = 0,
            ex_all = 0,
            calls = 0,
            passes = 0,
            lives_lost = 0,
            joint_wins = 0
        WHERE user_id = %s;
    """, (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

def get_overall_bot_metrics() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT 
            COUNT(*) as registered_users,
            COUNT(*) FILTER (WHERE games > 0) as active_users,
            COALESCE(SUM(games), 0) as total_games_played,
            COALESCE(SUM(wins), 0) as total_wins,
            COALESCE(SUM(joint_wins), 0) as total_joint_wins,
            COALESCE(SUM(rounds_survived), 0) as total_survived,
            COALESCE(SUM(exact_31), 0) as total_exact_31,
            COALESCE(SUM(exact_30_5), 0) as total_exact_30_5
        FROM call31_stats;
    """)
    call31_metrics = cursor.fetchone()

    cursor.execute("""
        SELECT 
            COUNT(*) as registered_groups,
            COUNT(*) FILTER (WHERE is_active = TRUE) as active_groups
        FROM registered_groups;
    """)
    group_metrics = cursor.fetchone()
    
    cursor.close()
    conn.close()

    return {
        "call31": dict(call31_metrics),
        "groups": dict(group_metrics)
    }

# ━━━━━━━━━━━━━━━━━━━━
# EXISTING GAMEPLAY FUNCTIONS (UNTOUCHED)
# ━━━━━━━━━━━━━━━━━━━━

def update_stat(user_id: int, name: str, field: str, amount: int = 1):
    allowed_fields = {
        "games", "wins", "round_wins", "rounds_survived", 
        "exact_31", "exact_30_5", "current_streak", "best_streak", 
        "ex_1", "ex_all", "calls", "passes", "lives_lost", "joint_wins"
    }
    if field not in allowed_fields:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO call31_stats (user_id, name)
        VALUES (%s, %s)
        ON CONFLICT(user_id) DO UPDATE SET name = EXCLUDED.name;
    """, (user_id, name))
    
    cursor.execute(f"""
        UPDATE call31_stats 
        SET {field} = {field} + %s 
        WHERE user_id = %s;
    """, (amount, user_id))
    
    conn.commit()
    cursor.close()
    conn.close()

def record_game_finish(winner_id: int, winner_name: str, participants: List[Tuple[int, str]]):
    conn = get_db_connection()
    cursor = conn.cursor()
    for u_id, name in participants:
        cursor.execute("""
            INSERT INTO call31_stats (user_id, name)
            VALUES (%s, %s)
            ON CONFLICT(user_id) DO UPDATE SET name = EXCLUDED.name;
        """, (u_id, name))
        cursor.execute("UPDATE call31_stats SET games = games + 1 WHERE user_id = %s;", (u_id,))
        
        if u_id == winner_id:
            cursor.execute("""
                UPDATE call31_stats 
                SET wins = wins + 1,
                    current_streak = current_streak + 1,
                    best_streak = GREATEST(best_streak, current_streak + 1)
                WHERE user_id = %s;
            """, (u_id,))
        else:
            cursor.execute("UPDATE call31_stats SET current_streak = 0 WHERE user_id = %s;", (u_id,))
            
    conn.commit()
    cursor.close()
    conn.close()

def record_joint_finish(winner_ids: List[int], participants: List[Tuple[int, str]]):
    conn = get_db_connection()
    cursor = conn.cursor()
    for u_id, name in participants:
        cursor.execute("""
            INSERT INTO call31_stats (user_id, name)
            VALUES (%s, %s)
            ON CONFLICT(user_id) DO UPDATE SET name = EXCLUDED.name;
        """, (u_id, name))
        cursor.execute("UPDATE call31_stats SET games = games + 1 WHERE user_id = %s;", (u_id,))
        
        if u_id in winner_ids:
            cursor.execute("UPDATE call31_stats SET joint_wins = joint_wins + 1 WHERE user_id = %s;", (u_id,))
        cursor.execute("UPDATE call31_stats SET current_streak = 0 WHERE user_id = %s;", (u_id,))
            
    conn.commit()
    cursor.close()
    conn.close()

def get_user_stats(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM call31_stats WHERE user_id = %s;", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return dict(row) if row else None

def get_leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM call31_stats ORDER BY wins DESC, joint_wins DESC, games ASC LIMIT %s;", (limit,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

def get_user_rank(user_id: int) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) + 1 
        FROM call31_stats 
        WHERE wins > (SELECT COALESCE(wins, 0) FROM call31_stats WHERE user_id = %s);
    """, (user_id,))
    row = cursor.fetchone()
    rank = row[0] if row else 1
    cursor.close()
    conn.close()
    return rank