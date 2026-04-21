"""
tools.py — OpenAI function-calling tool definitions and implementations.

Three tools:
  search_pages_metadata  — fast keyword search over page titles/URLs
  get_page_by_topic      — return full text of the best-matching page
  get_current_date       — return today's date for date-dependent queries
"""

import json
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

PAGES_PATH = "knowledge_base/pages.json"


def _load_pages() -> list[dict]:
    return json.loads(Path(PAGES_PATH).read_text(encoding="utf-8"))


# ── Tool implementations ──────────────────────────────────────────────────────

def search_pages_metadata(query: str) -> str:
    """
    Keyword search over page titles and URLs.
    Returns up to 5 ranked matches with title, URL, and a short text preview.
    """
    pages = _load_pages()
    query_lower = query.lower()
    results = []

    for page in pages:
        title = page.get("title", "")
        url = page.get("url", "")
        score = 0

        if query_lower in title.lower():
            score += 3
        if query_lower in url.lower():
            score += 2
        for word in query_lower.split():
            if len(word) > 3 and word in title.lower():
                score += 1
            if len(word) > 3 and word in page.get("text", "").lower()[:800]:
                score += 1

        if score > 0:
            results.append({
                "title": title,
                "url": url,
                "preview": page.get("text", "")[:200].strip(),
                "score": score,
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    if not results:
        available = [p["title"] for p in pages]
        return json.dumps({
            "found": False,
            "message": f"No pages matched '{query}'.",
            "available_pages": available,
        })

    return json.dumps({
        "found": True,
        "matches": [{k: v for k, v in r.items() if k != "score"} for r in results[:5]],
    })


def get_page_by_topic(topic: str) -> str:
    """
    Return the full text of the page whose title best matches the topic.
    Scores by substring containment first, then sequence similarity as fallback.
    """
    pages = _load_pages()
    topic_lower = topic.lower()

    best_page = None
    best_score = -1.0

    for page in pages:
        title = page.get("title", "").lower()
        url = page.get("url", "").lower()

        # Substring hit on title is the strongest signal
        if topic_lower in title:
            score = 2.0 + SequenceMatcher(None, topic_lower, title).ratio()
        elif any(w in title for w in topic_lower.split() if len(w) > 3):
            score = 1.0 + SequenceMatcher(None, topic_lower, title).ratio()
        elif topic_lower in url:
            score = 0.8
        else:
            score = SequenceMatcher(None, topic_lower, title).ratio()

        if score > best_score:
            best_score = score
            best_page = page

    if best_page and best_score > 0.25:
        return json.dumps({
            "found": True,
            "title": best_page["title"],
            "url": best_page["url"],
            "text": best_page["text"],
        })

    available = [p["title"] for p in pages]
    return json.dumps({
        "found": False,
        "message": f"No page closely matched '{topic}'.",
        "available_pages": available,
    })


def get_current_date() -> str:
    """Return today's date in several formats useful for date calculations."""
    now = datetime.now()
    return json.dumps({
        "date": now.strftime("%Y-%m-%d"),
        "formatted": now.strftime("%B %d, %Y"),
        "day_of_week": now.strftime("%A"),
        "time_utc_approx": now.strftime("%H:%M"),
    })


# ── Dispatch ──────────────────────────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "search_pages_metadata": lambda args: search_pages_metadata(**args),
    "get_page_by_topic": lambda args: get_page_by_topic(**args),
    "get_current_date": lambda _: get_current_date(),
}


def run_tool(name: str, arguments_json: str) -> str:
    """Parse tool arguments and call the matching function. Returns JSON string."""
    args = json.loads(arguments_json) if arguments_json else {}
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    return fn(args)


# ── OpenAI tool schemas ───────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_pages_metadata",
            "description": (
                "Search available knowledge base pages by keyword. "
                "Use this FIRST when a query maps to a specific topic (e.g. 'work permit', "
                "'student visa', 'welcome stamp') to find the right page before fetching it. "
                "Faster and cheaper than embedding search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword or topic to search for (e.g. 'work permit', 'welcome stamp', 'extension of stay')",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_by_topic",
            "description": (
                "Fetch the complete text of a specific immigration page by topic name. "
                "Use when you need the FULL page content rather than RAG chunks — "
                "ensures nothing is missed for detailed requirement questions. "
                "Best used after search_pages_metadata has confirmed which page to fetch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Page title or topic (e.g. 'WORK PERMITS', 'Student Visas', 'Welcome Stamp', 'Extensions of Stay')",
                    }
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": (
                "Get today's date and day of week. "
                "Use whenever the user asks a date-dependent question: "
                "visa/permit expiry, how many days remain, application deadlines, "
                "or any calculation involving 'today', 'now', 'currently'."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
