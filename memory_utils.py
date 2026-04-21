import json
import tiktoken
from pathlib import Path
from datetime import datetime
from config import CHAT_MODEL

MAX_HISTORY_TOKENS = 3000
CONVERSATIONS_DIR = Path("conversations")


# ── Token utilities ───────────────────────────────────────────────────────────

def count_tokens(messages: list[dict], model: str = CHAT_MODEL) -> int:
    enc = tiktoken.encoding_for_model(model)
    total = 0
    for msg in messages:
        total += 4
        total += len(enc.encode(msg["content"]))
    total += 2
    return total


def trim_history(messages: list[dict], max_tokens: int = MAX_HISTORY_TOKENS) -> list[dict]:
    """Drop oldest user/assistant pairs until the list fits within max_tokens."""
    system = [m for m in messages if m["role"] == "system"]
    history = [m for m in messages if m["role"] != "system"]

    while count_tokens(system + history) > max_tokens:
        if len(history) >= 2:
            history = history[2:]   # drop oldest user/assistant pair together
        elif len(history) == 1:
            history = []
        else:
            break

    return system + history


# ── Conversation management ───────────────────────────────────────────────────

def new_conversation_id() -> str:
    return datetime.now().strftime("conv_%Y%m%d_%H%M%S")


def conversation_title(messages: list[dict]) -> str:
    """Derive a short title from the first user message."""
    for msg in messages:
        if msg["role"] == "user":
            title = msg["content"].strip().replace("\n", " ")
            return title[:45] + "..." if len(title) > 45 else title
    return "New conversation"


def save_conversation(conv_id: str, messages: list[dict]) -> None:
    CONVERSATIONS_DIR.mkdir(exist_ok=True)
    data = {"title": conversation_title(messages), "messages": messages}
    (CONVERSATIONS_DIR / f"{conv_id}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def load_conversation(conv_id: str) -> list[dict]:
    path = CONVERSATIONS_DIR / f"{conv_id}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("messages", [])
    except (json.JSONDecodeError, OSError):
        return []


def list_conversations() -> list[dict]:
    """Return all saved conversations sorted by most recent first."""
    CONVERSATIONS_DIR.mkdir(exist_ok=True)
    convs = []
    for f in sorted(
        CONVERSATIONS_DIR.glob("conv_*.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    ):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            convs.append({"id": f.stem, "title": data.get("title", "Untitled")})
        except (json.JSONDecodeError, OSError):
            pass
    return convs


def delete_conversation(conv_id: str) -> None:
    path = CONVERSATIONS_DIR / f"{conv_id}.json"
    if path.exists():
        path.unlink()
