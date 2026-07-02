import os
import json
import uuid
import time
from typing import Dict, Any, List, Optional

CONVS_DIR = "conversations"

def init_convs_dir():
    os.makedirs(CONVS_DIR, exist_ok=True)
    os.makedirs(os.path.join("cerberai", "static", "generated"), exist_ok=True)

def list_conversations() -> List[Dict[str, Any]]:
    init_convs_dir()
    convs = []
    for fname in os.listdir(CONVS_DIR):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(CONVS_DIR, fname), "r") as f:
                    data = json.load(f)
                    convs.append({
                        "id": data.get("id"),
                        "title": data.get("title", "New Conversation"),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at")
                    })
            except Exception:
                pass
    # Sort by updated_at descending
    convs.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return convs

def get_conversation(conv_id: str) -> Optional[Dict[str, Any]]:
    init_convs_dir()
    path = os.path.join(CONVS_DIR, f"{conv_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None

def create_conversation(title: str = "New Chat") -> Dict[str, Any]:
    init_convs_dir()
    conv_id = str(uuid.uuid4())
    now = time.time()
    data = {
        "id": conv_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "messages": []
    }
    save_conversation(data)
    return data

def save_conversation(data: Dict[str, Any]):
    init_convs_dir()
    conv_id = data["id"]
    data["updated_at"] = time.time()
    path = os.path.join(CONVS_DIR, f"{conv_id}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def delete_conversation(conv_id: str) -> bool:
    init_convs_dir()
    path = os.path.join(CONVS_DIR, f"{conv_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
