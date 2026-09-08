"""
tools.py — OpenAI function-calling tool definitions and implementations.

Four tools:
  search_pages_metadata    — fast keyword search over page titles/URLs
  get_page_by_topic        — return full text of the best-matching page
  lookup_visa_requirement  — deterministic country -> visa requirement lookup
  get_current_date         — return today's date for date-dependent queries
"""

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

PAGES_PATH = "knowledge_base/pages.json"
VISA_REQUIREMENTS_PATH = "knowledge_base/visa_requirements.txt"


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


# ── Visa requirement table ────────────────────────────────────────────────────
# The country list is a lookup table, not prose: embedding search blurs ~25
# country names into a single chunk and reliably misses individual countries,
# so nationality questions are answered from a parse of the source file.

_visa_table: list[dict] | None = None

# Demonym endings, stripped to recover a country name ("Nigerian" -> "Nigeria").
# Stems are only ever tried as EXACT matches — no fuzzy matching, because
# "Niger" and "Nigeria" are one edit apart and must never be confused.
_DEMONYM_SUFFIXES = ("n", "an", "ian", "ean", "ese", "ish", "i", "ic")


def _normalize(name: str) -> str:
    """Lowercase, drop punctuation and a leading 'the', collapse whitespace."""
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(words)


def _split_top_level(text: str) -> list[str]:
    """Split a comma list, ignoring commas nested inside parentheses."""
    parts, depth, current = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _make_entry(raw_name: str, visa_required: bool, max_stay, category: str) -> dict:
    """Build one country record, pulling any parenthetical out as a qualifier."""
    match = re.match(r"^(.*?)\s*\((.*)\)\s*$", raw_name.strip())
    return {
        "country": (match.group(1) if match else raw_name).strip(),
        "visa_required": visa_required,
        "max_stay": max_stay,
        "category": category,
        "qualifier": match.group(2).strip() if match else None,
    }


def _parse_visa_table(path: str = VISA_REQUIREMENTS_PATH) -> list[dict]:
    """
    Parse visa_requirements.txt into one record per country.

    Handles the three shapes in the file: the flat visa-required list, grouped
    exemptions whose members sit on a following "(A, B, C)" line, and the
    per-country "- Country: 3 months" lines.
    """
    entries: list[dict] = []
    mode = None                      # "required" | "exempt" | None
    group = group_stay = None
    group_had_members = True

    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line == "---":
            continue

        if line.startswith("COUNTRIES REQUIRING A VISA"):
            mode, group = "required", None
            continue
        if line.startswith("COUNTRIES THAT DO NOT REQUIRE A VISA"):
            mode, group = "exempt", None
            continue
        if line.startswith("IMPORTANT NOTES") or line.startswith("CONTACT FOR"):
            mode = None
            continue
        if mode is None:
            continue

        header = re.match(r"^(.*?)\s+—\s+Permitted stay:\s*(.*?):?$", line)
        if mode == "exempt" and header:
            # A group that never gained members is itself a country (e.g. Canada).
            if group and not group_had_members:
                entries.append(_make_entry(group, False, group_stay, "No visa required"))
            group = header.group(1).strip()
            group_stay = re.sub(r"\s*\(varies by agreement\)", "", header.group(2)).strip()
            group_had_members = False
            continue

        if mode == "exempt" and group and line.startswith("(") and line.endswith(")"):
            for member in _split_top_level(line[1:-1]):
                if member.lower().startswith("and other"):
                    continue         # "and other Commonwealth members" is not a country
                entries.append(_make_entry(member, False, group_stay, group))
                group_had_members = True
            continue

        if line.startswith("- "):
            body = line[2:].strip()
            if mode == "required":
                entries.append(_make_entry(body, True, None, "Visa required"))
            else:
                name, _, stay = body.partition(":")
                entries.append(_make_entry(
                    name, False, stay.strip() or group_stay, group or "No visa required"
                ))
                group_had_members = True
            continue

    if group and not group_had_members:
        entries.append(_make_entry(group, False, group_stay, "No visa required"))
    return entries


def _visa_entries() -> list[dict]:
    """Parse the table once per process."""
    global _visa_table
    if _visa_table is None:
        _visa_table = _parse_visa_table()
    return _visa_table


def _entry_names(entry: dict) -> set[str]:
    """Normalized names an entry answers to: its own, plus any alias in parens."""
    names = {_normalize(entry["country"])}
    qualifier = entry.get("qualifier")
    # A parenthetical is either an alias ("Myanmar (Burma)") or a condition
    # ("holders of regular passports only"); only aliases are worth matching.
    if qualifier and not re.search(r"passport|holder|only", qualifier, re.I):
        names.add(_normalize(qualifier))
    return names


def lookup_visa_requirement(country: str) -> str:
    """
    Look up whether one nationality needs a visa for Barbados and how long they
    may stay. Exact matching only — an unrecognised country returns found:false
    with suggestions rather than a guess.
    """
    entries = _visa_entries()
    target = _normalize(country)

    stems = {target}
    for suffix in _DEMONYM_SUFFIXES:
        if target.endswith(suffix) and len(target) > len(suffix) + 2:
            stem = target[: -len(suffix)]
            stems.update({stem, stem + "a"})

    matches = [e for e in entries if _entry_names(e) & stems]

    if not matches:
        close = [
            e["country"] for e in entries
            if SequenceMatcher(None, target, _normalize(e["country"])).ratio() > 0.7
        ]
        return json.dumps({
            "found": False,
            "query": country,
            "message": (
                f"'{country}' is not listed in the Ministry of Foreign Affairs visa table. "
                "Do not guess this nationality's visa status."
            ),
            "guidance": (
                "Per the source document, citizens of countries not listed should contact "
                "the Barbados Ministry of Foreign Affairs or the nearest Barbados Embassy / "
                "High Commission to confirm their visa status."
            ),
            "did_you_mean": close[:5],
        })

    return json.dumps({
        "found": True,
        "query": country,
        "matches": [{k: v for k, v in m.items() if v is not None} for m in matches],
        "always_required": [
            "Valid passport",
            "Return or onward ticket",
            "Sufficient funds for the stay",
            "Accommodation details (hotel booking or host address)",
        ],
        "caveat": (
            "Being visa-exempt does not guarantee entry — immigration officers may refuse "
            "entry if requirements are not satisfied."
        ),
        "source": "Barbados Ministry of Foreign Affairs visa table, revised May 09, 2025",
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
    "lookup_visa_requirement": lambda args: lookup_visa_requirement(**args),
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
            "name": "lookup_visa_requirement",
            "description": (
                "Look up whether citizens of a specific country need a visa to enter Barbados, "
                "and the maximum permitted stay. You MUST call this for ANY question that "
                "mentions a nationality, citizenship, passport, or country of origin — the "
                "answer is a lookup in the official Ministry of Foreign Affairs table and must "
                "never be inferred from general context or prior knowledge. "
                "If it returns found:false, say the nationality is not listed and point the "
                "user to the Ministry of Foreign Affairs — do not guess."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "country": {
                        "type": "string",
                        "description": "Country name, e.g. 'Nigeria', 'Jamaica', 'Iran'. Pass the country, not the demonym, where possible.",
                    }
                },
                "required": ["country"],
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
