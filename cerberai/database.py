import sqlite3
import json
import time
from typing import List, Dict, Any, Optional

DB_PATH = "cerberai.db"

def get_db_connection():
    # Timeout of 30.0s ensures that concurrent writes wait instead of throwing lock errors
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Conversations table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT,
        created_at REAL,
        updated_at REAL,
        messages TEXT
    )
    """)
    
    # 2. Schedules table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id TEXT PRIMARY KEY,
        type TEXT,
        target TEXT,
        time TEXT,
        parameters TEXT,
        last_run TEXT
    )
    """)
    
    # 3. Media History table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS media_history (
        id TEXT PRIMARY KEY,
        type TEXT, -- 'video', 'report', 'podcast'
        filename TEXT,
        topic TEXT,
        date TEXT,
        query TEXT,
        md_filename TEXT,
        pdf_filename TEXT,
        created_at REAL,
        meta_data TEXT
    )
    """)
    
    # 4. Telegram History table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS telegram_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        timestamp REAL
    )
    """)
    
    # 5. Inference Stats table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inference_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        load_time REAL,
        time_to_first_token REAL,
        total_time REAL,
        timestamp REAL
    )
    """)
    
    conn.commit()
    conn.close()

# Initialize DB on import
init_db()

# ==========================================================================
# CONVERSATION OPERATIONS
# ==========================================================================
def db_list_conversations() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_get_conversation(conv_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, created_at, updated_at, messages FROM conversations WHERE id = ?", (conv_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        data = dict(row)
        try:
            data["messages"] = json.loads(data["messages"])
        except Exception:
            data["messages"] = []
        return data
    return None

def db_save_conversation(data: Dict[str, Any]):
    conn = get_db_connection()
    cursor = conn.cursor()
    conv_id = data["id"]
    title = data.get("title", "New Chat")
    created_at = data.get("created_at", time.time())
    updated_at = time.time()
    messages_str = json.dumps(data.get("messages", []))
    
    cursor.execute("""
    INSERT INTO conversations (id, title, created_at, updated_at, messages)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        title = excluded.title,
        updated_at = excluded.updated_at,
        messages = excluded.messages
    """, (conv_id, title, created_at, updated_at, messages_str))
    
    conn.commit()
    conn.close()

def db_delete_conversation(conv_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    changes = conn.total_changes
    conn.commit()
    conn.close()
    return changes > 0

# ==========================================================================
# SCHEDULES OPERATIONS
# ==========================================================================
def db_load_schedules() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, type, target, time, parameters, last_run FROM schedules")
    rows = cursor.fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["parameters"] = json.loads(d["parameters"])
        except Exception:
            d["parameters"] = {}
        results.append(d)
    return results

def db_save_schedules(schedules: List[Dict[str, Any]]):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Replace all existing schedules
    cursor.execute("DELETE FROM schedules")
    for s in schedules:
        params_str = json.dumps(s.get("parameters", {}))
        cursor.execute("""
        INSERT INTO schedules (id, type, target, time, parameters, last_run)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (s["id"], s["type"], s["target"], s["time"], params_str, s.get("last_run", "")))
    conn.commit()
    conn.close()

# ==========================================================================
# MEDIA HISTORY OPERATIONS
# ==========================================================================
def db_add_media_history(
    item_type: str,
    filename: str,
    topic: Optional[str] = None,
    date: Optional[str] = None,
    query: Optional[str] = None,
    md_filename: Optional[str] = None,
    pdf_filename: Optional[str] = None,
    meta_data: Optional[Dict[str, Any]] = None
):
    import uuid
    conn = get_db_connection()
    cursor = conn.cursor()
    item_id = str(uuid.uuid4())
    meta_str = json.dumps(meta_data or {})
    created_at = time.time()
    
    cursor.execute("""
    INSERT INTO media_history (id, type, filename, topic, date, query, md_filename, pdf_filename, created_at, meta_data)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (item_id, item_type, filename, topic, date, query, md_filename, pdf_filename, created_at, meta_str))
    
    conn.commit()
    conn.close()

def db_get_media_history(item_type: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, type, filename, topic, date, query, md_filename, pdf_filename, created_at, meta_data 
    FROM media_history 
    WHERE type = ? 
    ORDER BY created_at DESC
    """, (item_type,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["meta_data"] = json.loads(d["meta_data"])
        except Exception:
            d["meta_data"] = {}
        # Support compatibility with previous JSON fields
        if item_type == "video":
            d["video_url"] = f"/static/videos/{d['filename']}"
            if "stories" in d["meta_data"]:
                d["stories"] = d["meta_data"]["stories"]
        elif item_type == "report":
            d["report_url"] = f"/static/reports/{d['md_filename']}"
            d["pdf_url"] = f"/static/reports/{d['pdf_filename']}"
        elif item_type == "podcast":
            d["podcast_url"] = f"/static/podcasts/{d['filename']}"
            
        results.append(d)
    return results

def db_delete_media_history(item_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT type, filename, md_filename, pdf_filename FROM media_history WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    item = dict(row)
    cursor.execute("DELETE FROM media_history WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return item

# ==========================================================================
# TELEGRAM HISTORY OPERATIONS
# ==========================================================================
def db_add_telegram_history(role: str, content: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO telegram_history (role, content, timestamp)
    VALUES (?, ?, ?)
    """, (role, content, time.time()))
    conn.commit()
    conn.close()

def db_get_telegram_history() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role, content, timestamp FROM telegram_history ORDER BY timestamp DESC LIMIT 100")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
