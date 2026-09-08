# Echo — Agent Tool Definitions

Echo uses OpenAI function calling to give the agent access to structured tools alongside its RAG retrieval pipeline. These tools allow the agent to look up specific pages, search for topics, and handle date-dependent queries accurately.

All tools are defined in `tools.py` and dispatched via `run_tool()`.

---

## Tool 1: `search_pages_metadata`

**Purpose**
A fast keyword search over the titles and URLs of all pages in the knowledge base. Used to discover which pages are relevant to a query before fetching full content.

**When the agent uses it**
The agent calls this first when a user's question maps to a specific topic (e.g. "work permit", "Welcome Stamp", "student visa"). It is faster and cheaper than a full semantic search and helps the agent confirm a page exists before fetching it.

**Inputs**

| Parameter | Type   | Description                                              |
|-----------|--------|----------------------------------------------------------|
| `query`   | string | A keyword or topic to search for (e.g. "work permit")   |

**Output**
A JSON object. If matches are found:
```json
{
  "found": true,
  "matches": [
    {
      "title": "WORK PERMITS",
      "url": "https://immigration.gov.bb/pages/WorkPermit.aspx",
      "preview": "All non-nationals desirous of working in Barbados..."
    }
  ]
}
```
If no matches:
```json
{
  "found": false,
  "message": "No pages matched 'query'.",
  "available_pages": ["page title 1", "page title 2", ...]
}
```

**Scoring logic**
- Query found in page title: +3 points
- Query found in page URL: +2 points
- Individual words (>3 chars) found in title: +1 each
- Individual words found in the first 800 characters of page text: +1 each

Returns up to 5 results ranked by score.

---

## Tool 2: `get_page_by_topic`

**Purpose**
Fetches the complete text of a knowledge base page by topic name. Used when the agent needs the full content of a page — not just a RAG chunk — to answer a detailed requirements question accurately.

**When the agent uses it**
After `search_pages_metadata` has confirmed which page is relevant, the agent calls this to retrieve the full text. This ensures nothing is missed for questions like "what are all the documents required for a long-term work permit?"

**Inputs**

| Parameter | Type   | Description                                                         |
|-----------|--------|---------------------------------------------------------------------|
| `topic`   | string | Page title or topic name (e.g. "WORK PERMITS", "Welcome Stamp")    |

**Output**
A JSON object. If a matching page is found:
```json
{
  "found": true,
  "title": "WORK PERMITS",
  "url": "https://immigration.gov.bb/pages/WorkPermit.aspx",
  "text": "...full page text..."
}
```
If no close match:
```json
{
  "found": false,
  "message": "No page closely matched 'topic'.",
  "available_pages": ["page title 1", "page title 2", ...]
}
```

**Matching logic**
Uses a combination of substring matching and `SequenceMatcher` similarity scoring:
- Topic substring found in title: score 2.0 + similarity ratio
- Individual words (>3 chars) found in title: score 1.0 + similarity ratio
- Topic found in URL: score 0.8
- Fallback: pure similarity ratio

A match is returned only if the score exceeds 0.25.

---

## Tool 3: `get_current_date`

**Purpose**
Returns today's date in multiple formats. Used to answer any question that depends on the current date, such as visa expiry calculations, how many days remain before a deadline, or whether a permit has lapsed.

**When the agent uses it**
Any time the user's query involves words like "today", "now", "currently", "how many days", "expires", or asks about deadlines relative to the present. Without this tool, the model's training cutoff date would be used, which may be wrong.

**Inputs**
None.

**Output**
```json
{
  "date": "2026-04-20",
  "formatted": "April 20, 2026",
  "day_of_week": "Monday",
  "time_utc_approx": "14:35"
}
```

**Example use cases**
- "My Welcome Stamp started on March 1st — how many months do I have left?"
- "My work permit expires in 30 days, what should I do?"
- "Is today a working day at the Immigration Department?"

---

## Tool Interaction Pattern

The agent follows this pattern when handling a user query:

```
User asks a question
       │
       ▼
 RAG retrieval (FAISS semantic search on pre-built index)
       │
       ▼
 If query is topic-specific → call search_pages_metadata(query)
       │
       ▼
 If full page content needed → call get_page_by_topic(topic)
       │
       ▼
 If query is date-dependent → call get_current_date()
       │
       ▼
 Combine RAG context + tool results → generate final response
```

Tools can be called in sequence within a single conversation turn. The agent continues calling tools until it has sufficient information to compose a complete, cited answer.
