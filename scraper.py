"""
scraper.py — Fetch and clean Barbados immigration pages.
Run once: python scraper.py
Output: knowledge_base/pages.json
"""

import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://immigration.gov.bb"

# Public-facing informational pages only — no login, admin, or upload paths
SEED_PATHS = [
    "/pages/visitor.aspx",
    "/pages/Requirements.aspx",
    "/pages/SERVICES.aspx",
    "/pages/Downloads.aspx",
    "/pages/Contactus.aspx",
    "/pages/Traveling.aspx",
    "/pages/OnlinePayments.aspx",
    "/pages/Passport.aspx",
    "/pages/replace_passport.aspx",
    "/pages/WorkPermit.aspx",
    "/pages/extension.aspx",
    "/pages/StudentVisa.aspx",
    "/pages/Citizenship.aspx",
    "/pages/faq.aspx",
]

# Full URLs from other official/government-affiliated sources
EXTRA_URLS = [
    "https://www.visitbarbados.org/barbados-welcome-stamp",
    "https://immigration.gov.bb/pages/Visa_Requirements.aspx",
    "https://www.foreign.gov.bb/services/consular-services/",
]

# Paths to skip — private, login, admin
SKIP_PATTERNS = ["/Account/", "/Administration/", "/RUSM/", "login", "Login", "portal"]

# Navigation link text that appears on every page — stripped from content
_NAV_LINES = {
    "[ Log In ]", "Log In", "Home", "Services", "Downloads",
    "Requirements", "FAQs", "Contact Us", "[ log in ]",
}


def _strip_nav_lines(text: str) -> str:
    """Remove common site-wide navigation lines from extracted text."""
    lines = [ln for ln in text.splitlines() if ln.strip() not in _NAV_LINES]
    return "\n".join(lines)


def _derive_title(soup, text: str) -> str:
    """Extract page title: try <title> tag, then first heading, then first content line."""
    tag = soup.find("title")
    if tag and tag.string and tag.string.strip():
        return tag.string.strip()
    for h in soup.find_all(["h1", "h2"]):
        t = h.get_text(strip=True)
        if t and t not in _NAV_LINES:
            return t
    # Fall back: first non-empty, non-nav line in cleaned text
    for line in text.splitlines():
        line = line.strip()
        if line and line not in _NAV_LINES and len(line) > 4:
            return line
    return ""


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EchoRAGBot/1.0; "
        "+https://github.com/student-project; educational use)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}


def should_skip(url: str) -> bool:
    return any(p in url for p in SKIP_PATTERNS)


def fetch_page(url: str, session: requests.Session) -> str | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [skip] {url} — {e}")
        return None


def clean_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": "navigation"}):
        tag.decompose()
    for tag in soup.find_all(class_=re.compile(r"menu|cookie|banner|sidebar|breadcrumb", re.I)):
        tag.decompose()

    # Main content — prefer <main>, fall back to <body>
    main = soup.find("main") or soup.find(id=re.compile(r"content|main", re.I)) or soup.body
    if main is None:
        return {"url": url, "title": "", "text": ""}

    # Extract text with line breaks at block-level tags
    raw_text = main.get_text(separator="\n")

    # Normalise whitespace and collapse blank runs
    lines = [line.strip() for line in raw_text.splitlines()]
    cleaned_lines = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 2:
                cleaned_lines.append("")
        else:
            blank_run = 0
            cleaned_lines.append(line)

    text = "\n".join(cleaned_lines).strip()
    text = _strip_nav_lines(text)
    title = _derive_title(soup, text)
    return {"url": url, "title": title, "text": text}


def scrape_all(seed_paths: list[str], delay: float = 1.5) -> list[dict]:
    pages = []
    with requests.Session() as session:
        for path in seed_paths:
            url = BASE_URL + path
            if should_skip(url):
                print(f"  [skip] {url}")
                continue
            print(f"Fetching {url} ...")
            html = fetch_page(url, session)
            if not html:
                continue
            page = clean_html(html, url)
            if page["text"]:
                pages.append(page)
                print(f"  OK — {len(page['text'])} chars, title: {page['title']!r}")
            else:
                print(f"  [empty] no text extracted from {url}")
            time.sleep(delay)
    return pages


def main():
    Path("knowledge_base").mkdir(exist_ok=True)
    total = len(SEED_PATHS) + len(EXTRA_URLS)
    print(f"Scraping {len(SEED_PATHS)} pages from {BASE_URL} + {len(EXTRA_URLS)} extra URLs...\n")
    pages = scrape_all(SEED_PATHS)

    # Fetch extra full URLs (other official sources)
    if EXTRA_URLS:
        print("\nFetching extra URLs...")
        extra_pages = []
        with requests.Session() as session:
            for url in EXTRA_URLS:
                if should_skip(url):
                    print(f"  [skip] {url}")
                    continue
                print(f"Fetching {url} ...")
                html = fetch_page(url, session)
                if not html:
                    continue
                page = clean_html(html, url)
                if page["text"]:
                    extra_pages.append(page)
                    print(f"  OK — {len(page['text'])} chars, title: {page['title']!r}")
                else:
                    print(f"  [empty] no text extracted from {url}")
                time.sleep(1.5)
        pages.extend(extra_pages)

    out = Path("knowledge_base/pages.json")
    out.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone — {len(pages)} pages saved to {out}")


if __name__ == "__main__":
    main()
