from typing import Dict, Any, List, Optional
import uuid
import time
from .database import (
    db_list_conversations,
    db_get_conversation,
    db_save_conversation,
    db_delete_conversation
)

def init_convs_dir():
    # Keep function for backward compatibility / startup checks
    pass

def list_conversations() -> List[Dict[str, Any]]:
    return db_list_conversations()

def get_conversation(conv_id: str) -> Optional[Dict[str, Any]]:
    return db_get_conversation(conv_id)

def create_conversation(title: str = "New Chat") -> Dict[str, Any]:
    conv_id = str(uuid.uuid4())
    now = time.time()
    data = {
        "id": conv_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "messages": []
    }
    db_save_conversation(data)
    return data

def save_conversation(data: Dict[str, Any]):
    db_save_conversation(data)

def delete_conversation(conv_id: str) -> bool:
    return db_delete_conversation(conv_id)
