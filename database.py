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
    
    # Table create hogi sirf agar exist na kare (kisi ka data wipe nahi hoga)
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

    conn.commit()
    cursor.close()
    conn.close()

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