import json
import time
import uuid
import httpx
import numpy as np
from typing import List, Dict, Any, Optional
from .database import get_db_connection

def init_memory_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS semantic_memories (
        id TEXT PRIMARY KEY,
        content TEXT,
        embedding TEXT,  -- JSON serialized float list
        created_at REAL,
        meta_data TEXT
    )
    """)
    conn.commit()
    conn.close()

# Initialize table
init_memory_db()

async def get_embedding(text: str, manager) -> Optional[List[float]]:
    """Query the active llama.cpp server to get the embedding vector for the text."""
    # Find an active llama.cpp backend
    active_backend = None
    for b_id, backend in manager.backends.items():
        if backend.backend == "llamacpp" and await backend.is_loaded():
            active_backend = backend
            break
            
    if not active_backend:
        return None
        
    url = f"{active_backend.server_url}/embedding"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json={"content": text})
            if res.status_code == 200:
                return res.json().get("embedding")
    except Exception as e:
        print(f"Error generating embedding: {e}")
    return None

def save_memory(content: str, embedding: List[float], meta_data: Optional[Dict] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO semantic_memories (id, content, embedding, created_at, meta_data) VALUES (?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            content,
            json.dumps(embedding),
            time.time(),
            json.dumps(meta_data or {})
        )
    )
    conn.commit()
    conn.close()

def search_memories(query_embedding: List[float], threshold: float = 0.70, limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieve all memories and calculate cosine similarity in numpy."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, content, embedding, created_at, meta_data FROM semantic_memories")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return []
        
    q_vec = np.array(query_embedding)
    q_norm = np.linalg.norm(q_vec)
    if q_norm == 0:
        return []
        
    results = []
    for row in rows:
        try:
            m_embedding = json.loads(row["embedding"])
            m_vec = np.array(m_embedding)
            m_norm = np.linalg.norm(m_vec)
            if m_norm == 0:
                continue
                
            similarity = np.dot(q_vec, m_vec) / (q_norm * m_norm)
            if similarity >= threshold:
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "meta_data": json.loads(row["meta_data"]),
                    "similarity": float(similarity)
                })
        except Exception:
            continue
            
    # Sort by similarity descending
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]

async def extract_and_save_memories(conversation_history: List[Dict[str, str]], manager):
    """
    Asynchronously analyze the conversation to extract persistent facts about the user.
    Uses the active LLM backend to run the extraction.
    """
    # Find an active llama.cpp backend
    active_backend = None
    for b_id, backend in manager.backends.items():
        if backend.backend == "llamacpp" and await backend.is_loaded():
            active_backend = backend
            break
            
    if not active_backend:
        return
        
    # We only analyze the last exchange to keep it fast
    if len(conversation_history) < 2:
        return
        
    last_user = conversation_history[-2]["content"]
    last_assistant = conversation_history[-1]["content"]
    
    system_prompt = (
        "You are an expert fact extractor. Analyze the user's message and the assistant's response. "
        "Extract any persistent personal facts, preferences, background, or goals about the user. "
        "Format the output as a clean bulleted list of declarative sentences, e.g. '- The user is learning Python.' "
        "Only extract facts that are clear and useful. If no new personal details are mentioned, return nothing. "
        "Do NOT write any introduction, summary, or explanations."
    )
    
    user_prompt = f"User: {last_user}\nAssistant: {last_assistant}"
    
    payload = {
        "prompt": f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n",
        "temperature": 0.1,
        "max_tokens": 150,
        "stop": ["<|im_end|>"]
    }
    
    try:
        url = f"{active_backend.server_url}/completion"
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                output = res.json().get("content", "").strip()
                lines = [line.strip().lstrip("-").strip() for line in output.split("\n") if line.strip().startswith("-")]
                for fact in lines:
                    if fact and len(fact) > 5:
                        # Generate embedding and save
                        emb = await get_embedding(fact, manager)
                        if emb:
                            save_memory(fact, emb, {"source": "conversation_extraction"})
                            print(f"CerberAI Memory: Extracted and saved new fact: '{fact}'")
    except Exception as e:
        print(f"Error during memory extraction: {e}")
