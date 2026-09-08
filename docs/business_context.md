# Echo — Business Intelligence and Knowledge Base Context

This document describes the data sources that power Echo's knowledge base, how they were gathered, and how the agent uses them.

---

## Overview

Echo is a domain-specific assistant for Barbados immigration. Its knowledge base is built entirely from publicly available, official government sources. There is no synthetic or fabricated data — all content originates from the Barbados Immigration Department, the Ministry of Foreign Affairs, or the Barbados Tourism Authority.

The knowledge base serves two roles:
1. **Pre-built FAISS index** — embedded at setup time, loaded on app start, always available
2. **User-uploaded documents** — ingested at runtime per session, for supplementary personal context (e.g. a user uploading their own visa documents)

---

## Knowledge Base Sources

### Source 1: Barbados Immigration Department Website
**URL:** https://immigration.gov.bb
**Type:** Scraped HTML — official government website
**Method:** `scraper.py` fetches 14 public-facing pages using the `requests` library and `BeautifulSoup` for HTML parsing. Non-content elements (navigation, scripts, footers) are stripped. Text is cleaned and saved to `knowledge_base/pages.json`.

**Pages included:**

| Page Title                        | URL Path                          | Content Summary                                           |
|-----------------------------------|-----------------------------------|-----------------------------------------------------------|
| Visitors to Barbados              | /pages/visitor.aspx               | Entry requirements, online form, minors travelling        |
| Barbados Travel Documents         | /pages/Requirements.aspx          | Passport types and application requirements               |
| Services Offered                  | /pages/SERVICES.aspx              | Full list of immigration services available               |
| Downloadable Forms                | /pages/Downloads.aspx             | All official application form names and categories        |
| Office Locations                  | /pages/Contactus.aspx             | All department contacts, phone numbers, email addresses   |
| Barbadians Traveling Abroad       | /pages/Traveling.aspx             | Requirements for Barbadian nationals leaving              |
| Online Payment Information        | /pages/OnlinePayments.aspx        | How to pay fees online, appointment system                |
| Passports                         | /pages/Passport.aspx              | New passport application requirements and fees            |
| Replacement of Passports          | /pages/replace_passport.aspx      | Lost/stolen/damaged passport process                      |
| Work Permits                      | /pages/WorkPermit.aspx            | Short-term and long-term work permit requirements         |
| Extensions of Stay                | /pages/extension.aspx             | How to apply to extend a visitor stay                     |
| Student Visas                     | /pages/StudentVisa.aspx           | Student visa application process and required forms       |
| Barbadian Citizenship             | /pages/Citizenship.aspx           | Citizenship pathways, eligibility, required documents     |
| Frequently Asked Questions        | /pages/faq.aspx                   | General immigration FAQs                                  |

**Scraping policy:** Only public-facing informational pages are scraped. Login paths (`/Account/`), admin paths (`/Administration/`), and portals are explicitly excluded. A 1.5-second delay is applied between requests to avoid overloading the server.

---

### Source 2: Visit Barbados — Welcome Stamp Page
**URL:** https://www.visitbarbados.org/barbados-welcome-stamp
**Type:** Scraped HTML — official Barbados Tourism Authority website
**Method:** Same scraper pipeline as Source 1.
**Content:** Detailed information about the Barbados Welcome Stamp 12-month remote work visa — eligibility, fees (US$2,000 individual / US$3,000 family), application process, and benefits.

---

### Source 3: Barbados Immigration — Visa Requirements Page
**URL:** https://immigration.gov.bb/pages/Visa_Requirements.aspx
**Type:** Scraped HTML
**Content:** Transit visa and cruise passenger visa requirements. Supplementary to the full visa requirements document.

---

### Source 4: Visa Requirements by Nationality (Structured Document)
**File:** `knowledge_base/visa_requirements.txt`
**Type:** Manually structured text document
**Original source:** Ministry of Foreign Affairs and Foreign Trade, Barbados — *Updated Visa List, Revised May 09, 2025* (official PDF)
**Method:** The official PDF was reviewed and its content converted into a structured plain-text document covering:
- Countries that require a visa to enter Barbados (17 countries listed)
- Countries that do not require a visa, grouped by region/agreement, with permitted stay durations
- Important notes on entry requirements (passport validity, return tickets, funds)
- Contact information for visa enquiries

**Why this source:** The official immigration.gov.bb website does not publish a complete, machine-readable country-by-country visa list. The PDF from the Ministry of Foreign Affairs is the authoritative source for this information.

---

### Source 5: Plain-Language Immigration Guide
**File:** `knowledge_base/immigration_guide.txt`
**Type:** Authored explanatory document
**Original sources:** Synthesised from all scraped pages above
**Purpose:** The official immigration website provides accurate requirements but limited explanation of *why*, *when*, or *how* processes work in practice. This guide fills that gap with 10 sections written in plain language:

| Section | Topic |
|---------|-------|
| 1 | Understanding your situation — which immigration category applies to you |
| 2 | Do I need a visa to visit Barbados? |
| 3 | Arriving at the airport — what to expect |
| 4 | The Welcome Stamp — living and working remotely |
| 5 | Work permits — working for a Barbadian employer |
| 6 | Student visas |
| 7 | Extending your stay |
| 8 | Long-term pathways — permanent residence and citizenship |
| 9 | Fees and payments |
| 10 | Full contact directory |

This document is the primary source for conversational, explanatory answers. The scraped official pages serve as authoritative backup for specific requirements and fees.

---

## How the Agent Uses This Data

### At Index Build Time (`build_index.py`)
- All sources are loaded and chunked using a paragraph-aware semantic chunker (`semantic_chunk_text()`)
- Each chunk stores the source URL, page title, and section heading as metadata
- Chunks are embedded using OpenAI `text-embedding-3-small` and stored in a FAISS `IndexFlatL2` vector index
- The index and chunk metadata are saved to `faiss_index/`

### At Query Time (`app.py`)
1. The user's query is embedded using the same model
2. The FAISS index returns the top-k most semantically similar chunks (k=4 from the base index, k=2 from any user-uploaded file)
3. Chunks are injected into the system prompt with source labels: `[Source: {page_title} — {source_url}]`
4. The agent's function-calling tools can also retrieve additional page content on demand (see `agent_tools.md`)
5. Source URLs are rendered as clickable citation links below each response

### Chunk Metadata Structure
Each chunk in the index has the following fields:
```json
{
  "text": "The actual chunk text...",
  "source_url": "https://immigration.gov.bb/pages/WorkPermit.aspx",
  "page_title": "WORK PERMITS",
  "section": "Requirements for short-term work permits"
}
```

For locally authored documents with no URL, `source_url` is an empty string and only `page_title` is cited.

---

## Data Freshness and Limitations

- Scraped content reflects the state of the websites at the time `scraper.py` was last run
- The visa requirements document is based on the Ministry of Foreign Affairs PDF revised May 09, 2025
- Immigration rules change — fees, document requirements, and eligibility criteria may have been updated since the last scrape
- Echo always advises users to verify current requirements directly with the Barbados Immigration Department before making travel decisions
- Echo's responses are informational only and do not constitute legal or immigration advice
