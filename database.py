import sqlite3
from typing import Dict, Any, List, Optional, Tuple

DB_NAME = "deck_games.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS call31_stats (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            round_wins INTEGER DEFAULT 0,
            rounds_survived INTEGER DEFAULT 0,
            exact_31 INTEGER DEFAULT 0,
            exact_30_5 INTEGER DEFAULT 0,
            current_streak INTEGER DEFAULT 0,
            best_streak INTEGER DEFAULT 0,
            ex_1 INTEGER DEFAULT 0,
            ex_all INTEGER DEFAULT 0,
            calls INTEGER DEFAULT 0,
            passes INTEGER DEFAULT 0,
            lives_lost INTEGER DEFAULT 0,
            joint_wins INTEGER DEFAULT 0
        )
    """)

    # Safe column migration agar table pehle se exist karti ho
    cursor.execute("PRAGMA table_info(call31_stats)")
    columns = [row[1] for row in cursor.fetchall()]
    if "joint_wins" not in columns:
        cursor.execute("ALTER TABLE call31_stats ADD COLUMN joint_wins INTEGER DEFAULT 0")

    conn.commit()
    conn.close()

def update_stat(user_id: int, name: str, field: str, amount: int = 1):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO call31_stats (user_id, name)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET name = excluded.name
    """, (user_id, name))
    
    cursor.execute(f"""
        UPDATE call31_stats 
        SET {field} = {field} + ? 
        WHERE user_id = ?
    """, (amount, user_id))
    conn.commit()
    conn.close()

def record_game_finish(winner_id: int, winner_name: str, participants: List[Tuple[int, str]]):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for u_id, name in participants:
        cursor.execute("""
            INSERT INTO call31_stats (user_id, name)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET name = excluded.name
        """, (u_id, name))
        cursor.execute("UPDATE call31_stats SET games = games + 1 WHERE user_id = ?", (u_id,))
        
        if u_id == winner_id:
            cursor.execute("""
                UPDATE call31_stats 
                SET wins = wins + 1,
                    current_streak = current_streak + 1,
                    best_streak = MAX(best_streak, current_streak + 1)
                WHERE user_id = ?
            """, (u_id,))
        else:
            cursor.execute("UPDATE call31_stats SET current_streak = 0 WHERE user_id = ?", (u_id,))
            
    conn.commit()
    conn.close()

def record_joint_finish(winner_ids: List[int], participants: List[Tuple[int, str]]):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for u_id, name in participants:
        cursor.execute("""
            INSERT INTO call31_stats (user_id, name)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET name = excluded.name
        """, (u_id, name))
        cursor.execute("UPDATE call31_stats SET games = games + 1 WHERE user_id = ?", (u_id,))
        
        if u_id in winner_ids:
            cursor.execute("UPDATE call31_stats SET joint_wins = joint_wins + 1 WHERE user_id = ?", (u_id,))
        cursor.execute("UPDATE call31_stats SET current_streak = 0 WHERE user_id = ?", (u_id,))
            
    conn.commit()
    conn.close()

def get_user_stats(user_id: int) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM call31_stats WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM call31_stats ORDER BY wins DESC, joint_wins DESC, games ASC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_rank(user_id: int) -> int:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) + 1 
        FROM call31_stats 
        WHERE wins > (SELECT COALESCE(wins, 0) FROM call31_stats WHERE user_id = ?)
    """, (user_id,))
    rank = cursor.fetchone()[0]
    conn.close()
    return rank