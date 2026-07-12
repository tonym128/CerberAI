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
        timestamp REAL,
        model_name TEXT
    )
    """)
    
    try:
        cursor.execute("ALTER TABLE inference_stats ADD COLUMN model_name TEXT")
    except Exception:
        pass
    
    # 6. Model Registry table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS model_registry (
        id TEXT PRIMARY KEY,
        function_id TEXT,
        display_name TEXT,
        model_type TEXT,
        backend TEXT,
        purpose TEXT,
        vram_estimate_gb REAL,
        filename TEXT,
        repo_id TEXT,
        first_seen REAL,
        last_seen REAL,
        is_active INTEGER DEFAULT 1
    )
    """)
    
    # 7. Job Queue table for Async Orchestration
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS job_queue (
        id TEXT PRIMARY KEY,
        task_type TEXT,
        parameters TEXT,
        status TEXT,
        progress REAL DEFAULT 0.0,
        result TEXT,
        error TEXT,
        vram_required REAL DEFAULT 0.0,
        created_at REAL,
        started_at REAL,
        completed_at REAL
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

# ==========================================================================
# INFERENCE STATS OPERATIONS
# ==========================================================================
def db_add_inference_stat(
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    load_time: float,
    time_to_first_token: float,
    total_time: float,
    model_name: Optional[str] = None
):
    if model_name is not None and not isinstance(model_name, str):
        model_name = None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO inference_stats (model_id, prompt_tokens, completion_tokens, load_time, time_to_first_token, total_time, timestamp, model_name)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (model_id, prompt_tokens, completion_tokens, load_time, time_to_first_token, total_time, time.time(), model_name))
    conn.commit()
    conn.close()

def db_get_aggregated_stats(session_start: float) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    intervals = {
        "session": session_start,
        "daily": time.time() - 86400,
        "weekly": time.time() - 7 * 86400,
        "monthly": time.time() - 30 * 86400,
        "all_time": 0
    }
    
    report = {}
    for name, start_ts in intervals.items():
        cursor.execute("""
            SELECT model_id, prompt_tokens, completion_tokens, load_time, time_to_first_token, total_time, timestamp, model_name
            FROM inference_stats
            WHERE timestamp >= ?
        """, (start_ts,))
        rows = [dict(r) for r in cursor.fetchall()]
        
        # Aggregate
        total_requests = len(rows)
        total_prompt_tokens = sum(r["prompt_tokens"] for r in rows)
        total_completion_tokens = sum(r["completion_tokens"] for r in rows)
        
        # Calculate tokens/sec safely (sum of completion_tokens / sum of generation time)
        total_generation_time = sum(r["total_time"] - r["load_time"] for r in rows)
        if total_generation_time <= 0:
            total_generation_time = sum(r["total_time"] for r in rows)
            
        avg_tokens_sec = 0.0
        if total_generation_time > 0:
            avg_tokens_sec = total_completion_tokens / total_generation_time
            
        avg_load_time = 0.0
        if total_requests > 0:
            avg_load_time = sum(r["load_time"] for r in rows) / total_requests
            
        avg_ttft = 0.0
        if total_requests > 0:
            avg_ttft = sum(r["time_to_first_token"] for r in rows) / total_requests
            
        # Model level usage
        model_usage = {}
        for r in rows:
            m_id = r["model_id"]
            m_name = r.get("model_name") or m_id
            key = (m_id, m_name)
            if key not in model_usage:
                model_usage[key] = {
                    "requests": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_load_time": 0.0,
                    "total_ttft": 0.0,
                    "total_generation_time": 0.0
                }
            u = model_usage[key]
            u["requests"] += 1
            u["prompt_tokens"] += r["prompt_tokens"]
            u["completion_tokens"] += r["completion_tokens"]
            u["total_load_time"] += r["load_time"]
            u["total_ttft"] += r["time_to_first_token"]
            gen_time = r["total_time"] - r["load_time"]
            if gen_time <= 0:
                gen_time = r["total_time"]
            u["total_generation_time"] += gen_time
            
        # Finalize models data
        models_data = []
        for (m_id, m_name), u in model_usage.items():
            avg_m_tps = 0.0
            if u["total_generation_time"] > 0:
                avg_m_tps = u["completion_tokens"] / u["total_generation_time"]
                
            models_data.append({
                "model_id": m_id,
                "model_name": m_name,
                "requests": u["requests"],
                "prompt_tokens": u["prompt_tokens"],
                "completion_tokens": u["completion_tokens"],
                "avg_tokens_sec": avg_m_tps,
                "avg_load_time": u["total_load_time"] / u["requests"],
                "avg_time_to_first_token": u["total_ttft"] / u["requests"]
            })
            
        report[name] = {
            "total_requests": total_requests,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "avg_tokens_sec": avg_tokens_sec,
            "avg_load_time": avg_load_time,
            "avg_time_to_first_token": avg_ttft,
            "models": models_data
        }
        
    conn.close()
    return report

# ==========================================================================
# MODEL REGISTRY OPERATIONS
# ==========================================================================
def db_upsert_model_registry(
    function_id: str,
    display_name: str,
    model_type: str,
    backend: str,
    purpose: str,
    vram_estimate_gb: float,
    filename: str,
    repo_id: str
):
    """Insert or update a model in the registry. Updates last_seen and marks as active."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = time.time()
    
    # Check if exists
    cursor.execute("SELECT id FROM model_registry WHERE function_id = ? AND filename = ?", (function_id, filename))
    row = cursor.fetchone()
    
    if row:
        cursor.execute("""
        UPDATE model_registry SET display_name=?, model_type=?, backend=?, purpose=?, 
        vram_estimate_gb=?, repo_id=?, last_seen=?, is_active=1 WHERE id=?
        """, (display_name, model_type, backend, purpose, vram_estimate_gb, repo_id, now, row["id"]))
    else:
        import uuid
        item_id = str(uuid.uuid4())
        cursor.execute("""
        INSERT INTO model_registry (id, function_id, display_name, model_type, backend, purpose, vram_estimate_gb, filename, repo_id, first_seen, last_seen, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (item_id, function_id, display_name, model_type, backend, purpose, vram_estimate_gb, filename, repo_id, now, now))
    
    conn.commit()
    conn.close()

def db_get_model_registry() -> List[Dict[str, Any]]:
    """Get all models from the registry, ordered by active status then last_seen."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM model_registry ORDER BY is_active DESC, last_seen DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_mark_inactive_models(active_function_ids: List[str]):
    """Mark models not in the current config as inactive."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if active_function_ids:
        placeholders = ','.join('?' * len(active_function_ids))
        cursor.execute(f"UPDATE model_registry SET is_active=0 WHERE function_id NOT IN ({placeholders})", active_function_ids)
    else:
        cursor.execute("UPDATE model_registry SET is_active=0")
    conn.commit()
    conn.close()

# ==========================================================================
# ASYNC JOB QUEUE OPERATIONS
# ==========================================================================
def db_create_job(task_type: str, parameters: Dict[str, Any], vram_required: float) -> str:
    """Enqueue a new agent job."""
    import uuid
    job_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    now = time.time()
    cursor.execute("""
    INSERT INTO job_queue (id, task_type, parameters, status, progress, created_at, vram_required)
    VALUES (?, ?, ?, 'pending', 0.0, ?, ?)
    """, (job_id, task_type, json.dumps(parameters), now, vram_required))
    conn.commit()
    conn.close()
    return job_id

def db_update_job_status(
    job_id: str,
    status: str,
    progress: float = None,
    result: Dict[str, Any] = None,
    error: str = None
):
    """Update job state, progress, output, or execution error log."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = time.time()
    
    updates = ["status = ?"]
    params = [status]
    
    if status == "running":
        updates.append("started_at = ?")
        params.append(now)
    elif status in ("completed", "failed"):
        updates.append("completed_at = ?")
        params.append(now)
        
    if progress is not None:
        updates.append("progress = ?")
        params.append(progress)
    if result is not None:
        updates.append("result = ?")
        params.append(json.dumps(result))
    if error is not None:
        updates.append("error = ?")
        params.append(error)
        
    params.append(job_id)
    query = f"UPDATE job_queue SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, tuple(params))
    conn.commit()
    conn.close()

def db_get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve details of a specific job."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM job_queue WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        res["parameters"] = json.loads(res["parameters"]) if res["parameters"] else {}
        res["result"] = json.loads(res["result"]) if res["result"] else None
        return res
    return None

def db_list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """List recent jobs in queue."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM job_queue ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        item = dict(r)
        item["parameters"] = json.loads(item["parameters"]) if item["parameters"] else {}
        item["result"] = json.loads(item["result"]) if item["result"] else None
        results.append(item)
    return results

def db_get_next_pending_job() -> Optional[Dict[str, Any]]:
    """Retrieve the next pending job."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM job_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        item = dict(row)
        item["parameters"] = json.loads(item["parameters"]) if item["parameters"] else {}
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item
    return None

def db_delete_job(job_id: str) -> bool:
    """Delete a job from the queue database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM job_queue WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return True

def db_move_job(job_id: str, direction: str) -> bool:
    """Move a pending job up or down in the queue by swapping created_at timestamps."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, created_at FROM job_queue WHERE status = 'pending' ORDER BY created_at ASC")
    rows = cursor.fetchall()
    jobs = [dict(r) for r in rows]
    idx = -1
    for i, job in enumerate(jobs):
        if job["id"] == job_id:
            idx = i
            break
    if idx == -1:
        conn.close()
        return False
    swap_idx = -1
    if direction == "up" and idx > 0:
        swap_idx = idx - 1
    elif direction == "down" and idx < len(jobs) - 1:
        swap_idx = idx + 1
    if swap_idx != -1:
        t1 = jobs[idx]["created_at"]
        t2 = jobs[swap_idx]["created_at"]
        cursor.execute("UPDATE job_queue SET created_at = ? WHERE id = ?", (t2, jobs[idx]["id"]))
        cursor.execute("UPDATE job_queue SET created_at = ? WHERE id = ?", (t1, jobs[swap_idx]["id"]))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


