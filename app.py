import base64
import io
import math
import streamlit as st
from pathlib import Path
from PIL import Image, ImageDraw

from config import client, CHAT_MODEL
from rag_utils import ingest_file, retrieve, load_prebuilt_index
from tools import TOOLS, run_tool
from memory_utils import (
    trim_history,
    new_conversation_id, save_conversation, load_conversation,
    list_conversations, delete_conversation,
)

# ── Constants ────────────────────────────────────────────────────────────────
UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)

BOT_AVATAR = Path("assets/immibot.png")

SYSTEM_PROMPT = (
    "You are Echo, an expert Barbados immigration assistant. "
    "Help users understand visa categories, entry requirements, "
    "work permits, and immigration procedures.\n\n"
    "When answering, think through the user's situation carefully before responding: "
    "identify which visa category or process applies to them, review the relevant "
    "requirements from the provided context, work through any eligibility criteria or "
    "edge cases, then give a clear and practical answer. End by mentioning the source "
    "pages your answer draws from. Do all of this naturally in your response — never "
    "use section headings or labels like ASSESS, ANALYSE, REASON, RECOMMEND, or CITE.\n\n"
    "You have access to three tools — use them proactively:\n"
    "- search_pages_metadata: use first when a query maps to a specific topic to find the right page.\n"
    "- get_page_by_topic: use to fetch the FULL page when you need complete requirements — "
    "more reliable than RAG chunks for direct topic questions.\n"
    "- get_current_date: use whenever the user asks anything date-dependent "
    "(expiry, deadlines, how long remaining).\n\n"
    "Rules:\n"
    "- Base answers strictly on provided context and tool results. If context does not cover "
    "the question, say so and direct the user to contact the Barbados Immigration Department.\n"
    "- Do not invent visa categories, fees, durations, or document requirements.\n"
    "- When quoting requirements, be precise.\n"
    "- This is informational guidance only — not legal advice. For complex cases, "
    "recommend consulting an immigration lawyer."
)

STARTER_PROMPTS = [
    "What visa do I need to visit Barbados?",
    "How do I apply for the Welcome Stamp remote work visa?",
    "What documents are required for a work permit?",
    "Can I extend my stay in Barbados as a tourist?",
]

# ── Avatar generators ─────────────────────────────────────────────────────────
@st.cache_resource
def echo_avatar() -> Image.Image:
    """Periwinkle purple circle with a 4-pointed AI star."""
    s = 80
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, s, s], fill=(140, 120, 200, 255))
    cx, cy, outer, inner = 40, 40, 26, 9
    pts = []
    for i in range(8):
        angle = math.pi * i / 4 - math.pi / 2
        r = outer if i % 2 == 0 else inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d.polygon(pts, fill=(255, 255, 255, 245))
    return img


@st.cache_resource
def sidebar_image() -> Image.Image:
    """Circular crop of the robot avatar."""
    img = Image.open(BOT_AVATAR).convert("RGBA")
    w, h = img.size
    sq = min(w, h)
    left, top = (w - sq) // 2, (h - sq) // 2
    img = img.crop((left, top, left + sq, top + sq))
    margin = int(sq * 0.05)
    img = img.crop((margin, margin, sq - margin, sq - margin))
    img = img.resize((220, 220), Image.LANCZOS)
    size = 220
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img, mask=mask)
    return result


@st.cache_resource
def get_prebuilt_index():
    """Load prebuilt FAISS index once per process. Returns (chunks, index) or ([], None)."""
    chunks, index = load_prebuilt_index()
    if chunks is None:
        return [], None
    return chunks, index


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Echo", layout="wide", page_icon=str(BOT_AVATAR))

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Base — deep Caribbean navy ── */
.stApp {
    background: #0D1B2A;
    background-attachment: fixed;
}

/* ── Animated orbs ── */
.orb {
    position: fixed;
    border-radius: 50%;
    filter: blur(42px);
    pointer-events: none;
    z-index: 0;
}
/* Sky blue — top left, fast */
.o1 {
    width: 560px; height: 560px;
    background: radial-gradient(circle, #0EA5E9, transparent 70%);
    opacity: 0.38;
    top: -8%; left: 5%;
    animation: drift1 11s ease-in-out infinite alternate;
}
/* Cobalt — top right, slow */
.o2 {
    width: 520px; height: 520px;
    background: radial-gradient(circle, #1D4ED8, transparent 70%);
    opacity: 0.32;
    top: -5%; right: 8%;
    animation: drift2 19s ease-in-out infinite alternate;
}
/* Ocean blue — center, medium */
.o3 {
    width: 600px; height: 600px;
    background: radial-gradient(circle, #0369A1, transparent 70%);
    opacity: 0.28;
    top: 30%; left: 28%;
    animation: drift3 14s ease-in-out infinite alternate;
}
/* Amber gold — bottom left, medium-fast */
.o4 {
    width: 480px; height: 480px;
    background: radial-gradient(circle, #D97706, transparent 70%);
    opacity: 0.35;
    bottom: 5%; left: 6%;
    animation: drift4 16s ease-in-out infinite alternate;
}
/* Warm gold — bottom right, fastest */
.o5 {
    width: 500px; height: 500px;
    background: radial-gradient(circle, #F59E0B, transparent 70%);
    opacity: 0.30;
    bottom: 0%; right: 4%;
    animation: drift5 8s ease-in-out infinite alternate;
}
/* Teal — mid left */
.o6 {
    width: 460px; height: 460px;
    background: radial-gradient(circle, #0F766E, transparent 70%);
    opacity: 0.33;
    top: 42%; left: -4%;
    animation: drift6 13s ease-in-out infinite alternate;
}

/* Multi-step keyframes — organic, breathing motion */
@keyframes drift1 {
    0%   { transform: translate(0px,   0px)   scale(1.00) rotate(0deg);   opacity: 0.38; }
    30%  { transform: translate(55px,  30px)  scale(1.10) rotate(4deg);   opacity: 0.50; }
    70%  { transform: translate(75px,  55px)  scale(1.06) rotate(-2deg);  opacity: 0.44; }
    100% { transform: translate(95px,  75px)  scale(1.14) rotate(6deg);   opacity: 0.38; }
}
@keyframes drift2 {
    0%   { transform: translate(0px,   0px)   scale(1.00) rotate(0deg);   opacity: 0.32; }
    25%  { transform: translate(-30px, 45px)  scale(1.07) rotate(-3deg);  opacity: 0.42; }
    65%  { transform: translate(-60px, 70px)  scale(1.04) rotate(5deg);   opacity: 0.38; }
    100% { transform: translate(-75px, 95px)  scale(1.10) rotate(-4deg);  opacity: 0.32; }
}
@keyframes drift3 {
    0%   { transform: translate(0px,   0px)   scale(1.00) rotate(0deg);   opacity: 0.28; }
    35%  { transform: translate(40px, -50px)  scale(1.12) rotate(3deg);   opacity: 0.40; }
    70%  { transform: translate(65px, -30px)  scale(1.08) rotate(-5deg);  opacity: 0.34; }
    100% { transform: translate(55px, -85px)  scale(1.18) rotate(7deg);   opacity: 0.28; }
}
@keyframes drift4 {
    0%   { transform: translate(0px,   0px)   scale(1.00) rotate(0deg);   opacity: 0.35; }
    40%  { transform: translate(50px, -35px)  scale(1.09) rotate(-4deg);  opacity: 0.48; }
    75%  { transform: translate(70px, -55px)  scale(1.05) rotate(6deg);   opacity: 0.40; }
    100% { transform: translate(85px, -65px)  scale(1.12) rotate(-3deg);  opacity: 0.35; }
}
@keyframes drift5 {
    0%   { transform: translate(0px,   0px)   scale(1.00) rotate(0deg);   opacity: 0.30; }
    20%  { transform: translate(-45px,-30px)  scale(1.11) rotate(5deg);   opacity: 0.44; }
    60%  { transform: translate(-65px,-55px)  scale(1.06) rotate(-6deg);  opacity: 0.36; }
    100% { transform: translate(-85px,-75px)  scale(1.14) rotate(4deg);   opacity: 0.30; }
}
@keyframes drift6 {
    0%   { transform: translate(0px,   0px)   scale(1.00) rotate(0deg);   opacity: 0.33; }
    45%  { transform: translate(45px, -40px)  scale(1.08) rotate(-5deg);  opacity: 0.46; }
    80%  { transform: translate(65px, -20px)  scale(1.13) rotate(4deg);   opacity: 0.38; }
    100% { transform: translate(75px, -65px)  scale(1.10) rotate(-2deg);  opacity: 0.33; }
}

/* Lift main content above orbs */
section.main {
    position: relative;
    z-index: 1;
}

/* Header — transparent */
header[data-testid="stHeader"] {
    background: transparent !important;
    border-bottom: none !important;
    box-shadow: none !important;
}
[data-testid="stDecoration"] { display: none; }

/* Main block-container — extra bottom padding keeps last message above input */
.main .block-container {
    background: transparent !important;
    box-shadow: none !important;
    padding-top: 3.5rem !important;
    padding-bottom: 9rem !important;
}

/* Fade mask — fully opaque by 60% so nothing bleeds under the input bar */
section.main::after {
    content: "";
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 160px;
    background: linear-gradient(to bottom,
        transparent 0%,
        rgba(13, 27, 42, 0.80) 45%,
        #0D1B2A 65%);
    pointer-events: none;
    z-index: 50;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: rgba(8, 18, 30, 0.78) !important;
    backdrop-filter: blur(20px);
    border-right: none !important;
    box-shadow: 4px 0 32px rgba(0, 0, 0, 0.35);
    overflow-y: auto !important;
}
section[data-testid="stSidebar"]::after {
    content: "";
    position: absolute;
    top: 0; right: 0;
    width: 1px; height: 100%;
    background: linear-gradient(to bottom,
        transparent,
        rgba(14, 165, 233, 0.28) 25%,
        rgba(14, 165, 233, 0.28) 75%,
        transparent);
}

/* Sidebar content padding */
[data-testid="stSidebarContent"] {
    padding-top: 0 !important;
    padding-bottom: 1.5rem !important;
}

/* Sidebar — New Chat and all top-level buttons */
section[data-testid="stSidebar"] > div > div > div > div > div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] .stButton button,
section[data-testid="stSidebar"] .stButton button {
    background: rgba(14, 165, 233, 0.10) !important;
    border: 1px solid rgba(14, 165, 233, 0.30) !important;
    border-radius: 8px !important;
    color: #E0F2FE !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em !important;
    transition: background 0.2s, border-color 0.2s !important;
    margin-top: 0.2rem !important;
    margin-bottom: 0.15rem !important;
}
section[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(14, 165, 233, 0.22) !important;
    border-color: rgba(14, 165, 233, 0.55) !important;
}

/* Sidebar — history item buttons (inside stHorizontalBlock, first column) */
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:first-child button {
    text-align: left !important;
    justify-content: flex-start !important;
    background: transparent !important;
    border: 1px solid transparent !important;
    border-left: 2px solid transparent !important;
    border-radius: 6px !important;
    color: rgba(186, 214, 240, 0.65) !important;
    font-weight: 400 !important;
    font-size: 0.80rem !important;
    padding: 0.3rem 0.6rem !important;
    margin: 0.05rem 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:first-child button:hover {
    background: rgba(14, 165, 233, 0.10) !important;
    border-left-color: rgba(14, 165, 233, 0.55) !important;
    color: #E0F2FE !important;
}

/* Sidebar — delete (×) button */
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:last-child button {
    background: transparent !important;
    border: none !important;
    color: rgba(255, 255, 255, 0.28) !important;
    font-size: 1rem !important;
    padding: 0 !important;
    margin: 0 !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:last-child button:hover {
    color: rgba(255, 90, 90, 0.80) !important;
    background: transparent !important;
}

/* Sidebar dividers and headings */
section[data-testid="stSidebar"] hr {
    margin-top: 0.6rem !important;
    margin-bottom: 0.6rem !important;
    border-color: rgba(14, 165, 233, 0.18) !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #BAD6F0;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.10em !important;
    text-transform: uppercase !important;
    margin-top: 0.5rem !important;
    margin-bottom: 0.3rem !important;
}

/* ── Hide user avatar ── */
[data-testid="stChatMessageAvatarUser"] {
    display: none !important;
    width: 0 !important;
    min-width: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}

/* ── User bubble — Caribbean teal tint ── */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: rgba(14, 165, 233, 0.14);
    border: 1px solid rgba(14, 165, 233, 0.30);
    border-radius: 999px;
    padding: 10px 22px;
    margin-bottom: 8px;
    backdrop-filter: blur(8px);
    box-shadow: none;
}

/* ── Assistant bubble — warm gold tint ── */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
    background: rgba(217, 119, 6, 0.12);
    border: 1px solid rgba(245, 158, 11, 0.25);
    border-radius: 999px;
    padding: 10px 22px;
    margin-bottom: 4px;
    backdrop-filter: blur(8px);
    box-shadow: none;
}

/* ── Bottom bar — strip backgrounds ── */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottom"] > div > div,
[data-testid="stBottom"] > div > div > div,
.stChatFloatingInputContainer,
.stChatFloatingInputContainer > div,
[data-testid="stChatInputContainer"],
[data-testid="stChatInputContainer"] > div {
    background: transparent !important;
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* ── Chat input — white pill ── */
[data-testid="stChatInput"] {
    border-radius: 999px !important;
    border: 1px solid rgba(200, 200, 200, 0.60) !important;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.18) !important;
    backdrop-filter: blur(12px) !important;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.90) !important;
}
[data-testid="stChatInput"] * {
    background: rgba(255, 255, 255, 0.90) !important;
    border: none !important;
    box-shadow: none !important;
    color: #0D1B2A !important;
}
[data-testid="stChatInput"] textarea {
    border-radius: 999px !important;
    padding-left: 1.4rem !important;
    caret-color: #0D1B2A !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: rgba(13, 27, 42, 0.40) !important;
}

/* ── Starter prompt pills ── */
[data-testid="stMain"] .stButton button {
    background: rgba(14, 165, 233, 0.14) !important;
    border: 1px solid rgba(14, 165, 233, 0.38) !important;
    border-radius: 999px !important;
    color: rgba(224, 242, 254, 0.92) !important;
    font-size: 0.82rem !important;
    padding: 0.45rem 1rem !important;
    backdrop-filter: blur(8px);
    transition: background 0.2s, border-color 0.2s;
}
[data-testid="stMain"] .stButton button:hover {
    background: rgba(14, 165, 233, 0.26) !important;
    border-color: rgba(14, 165, 233, 0.60) !important;
}

/* Global dividers */
hr { border-color: rgba(14, 165, 233, 0.20); }
</style>
""", unsafe_allow_html=True)

# ── Animated orb divs ────────────────────────────────────────────────────────
st.markdown("""
<div class="orb o1"></div>
<div class="orb o2"></div>
<div class="orb o3"></div>
<div class="orb o4"></div>
<div class="orb o5"></div>
<div class="orb o6"></div>
""", unsafe_allow_html=True)

# ── Session state defaults ────────────────────────────────────────────────────
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = new_conversation_id()
if "history" not in st.session_state:
    st.session_state.history = []
# Prebuilt knowledge base (loaded once from disk)
if "base_chunks" not in st.session_state:
    st.session_state.base_chunks = []
if "base_index" not in st.session_state:
    st.session_state.base_index = None
# User-uploaded file (session-scoped)
if "user_chunks" not in st.session_state:
    st.session_state.user_chunks = []
if "user_index" not in st.session_state:
    st.session_state.user_index = None
if "ingested_file" not in st.session_state:
    st.session_state.ingested_file = None
# Starter prompt pill interaction
if "starter_used" not in st.session_state:
    st.session_state.starter_used = None

# ── Load prebuilt index (once per process) ────────────────────────────────────
_base_chunks, _base_index = get_prebuilt_index()
if not st.session_state.base_chunks and _base_chunks:
    st.session_state.base_chunks = _base_chunks
    st.session_state.base_index = _base_index

# ── Helpers ───────────────────────────────────────────────────────────────────
def build_messages(history: list[dict], user_query: str, context_chunks: list[dict]) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context_chunks:
        parts = []
        for chunk in context_chunks:
            if chunk.get("source_url"):
                header = f"[Source: {chunk['page_title']} — {chunk['source_url']}]"
            else:
                header = f"[Source: {chunk['page_title']}]"
            parts.append(f"{header}\n{chunk['text']}")
        sep = "\n\n---\n\n"
        context_text = sep.join(parts)
        messages.append({"role": "system", "content": "Relevant immigration information:\n\n" + context_text})
    messages += history
    messages.append({"role": "user", "content": user_query})
    return messages


def get_reply(user_query: str) -> tuple[str, list[dict]]:
    """
    Returns (reply_text, source_chunks_used).
    Runs a tool-calling loop: model may invoke tools zero or more times
    before producing a final text response.
    """
    retrieved: list[dict] = []

    if st.session_state.base_index is not None:
        base_hits = retrieve(user_query, st.session_state.base_index, st.session_state.base_chunks, k=4)
        retrieved.extend(base_hits)

    if st.session_state.user_index is not None:
        user_hits = retrieve(user_query, st.session_state.user_index, st.session_state.user_chunks, k=2)
        retrieved.extend(user_hits)

    # Deduplicate by text
    seen, unique = set(), []
    for c in retrieved:
        if c["text"] not in seen:
            seen.add(c["text"])
            unique.append(c)

    messages = build_messages(st.session_state.history, user_query, unique)
    messages = trim_history(messages)

    # Tool-calling loop — continues until the model returns a plain text response
    while True:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
        )

        msg = response.choices[0].message

        # No tool calls — final answer
        if not msg.tool_calls:
            return msg.content, unique

        # Append assistant turn (contains tool_calls)
        messages.append(msg)

        # Execute every requested tool and append results
        for tc in msg.tool_calls:
            result = run_tool(tc.function.name, tc.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    _buf = io.BytesIO()
    sidebar_image().save(_buf, format="PNG")
    _b64 = base64.b64encode(_buf.getvalue()).decode()
    st.markdown(f"""
    <div style="display:flex;flex-direction:column;align-items:center;
                padding:1.6rem 0 1.2rem;gap:0.4rem;">
        <img src="data:image/png;base64,{_b64}" width="100"
             style="border-radius:50%;box-shadow:0 0 0 2px rgba(14,165,233,0.30);" />
        <span style="font-size:1.45rem;font-weight:700;color:#E0F2FE;
                     letter-spacing:0.1em;
                     text-shadow:0 2px 16px rgba(14,165,233,0.55);">
            Echo
        </span>
        <span style="color:rgba(186,214,240,0.50);font-size:0.68rem;
                     letter-spacing:0.18em;text-transform:uppercase;font-weight:500;
                     margin-top:-0.1rem;">
            Immigration Assistant
        </span>
    </div>
    """, unsafe_allow_html=True)

    if st.button("+ New Chat", use_container_width=True):
        if st.session_state.history:
            save_conversation(st.session_state.conversation_id, st.session_state.history)
        st.session_state.conversation_id = new_conversation_id()
        st.session_state.history = []
        st.session_state.user_chunks = []
        st.session_state.user_index = None
        st.session_state.ingested_file = None
        st.session_state.starter_used = None
        st.rerun()

    convs = list_conversations()
    if convs:
        st.markdown(
            "<p style='color:rgba(255,255,255,0.5);font-size:0.75rem;"
            "margin:0.5rem 0 0.25rem;'>Recent</p>",
            unsafe_allow_html=True,
        )
        for conv in convs:
            is_active = conv["id"] == st.session_state.conversation_id
            label = ("▶ " if is_active else "") + conv["title"]
            col_title, col_del = st.columns([5, 1])
            with col_title:
                if st.button(label, key=conv["id"], use_container_width=True):
                    if not is_active:
                        if st.session_state.history:
                            save_conversation(
                                st.session_state.conversation_id,
                                st.session_state.history,
                            )
                        st.session_state.conversation_id = conv["id"]
                        st.session_state.history = load_conversation(conv["id"])
                        st.session_state.user_chunks = []
                        st.session_state.user_index = None
                        st.session_state.ingested_file = None
                        st.rerun()
            with col_del:
                if st.button("×", key=f"del_{conv['id']}"):
                    delete_conversation(conv["id"])
                    if is_active:
                        st.session_state.conversation_id = new_conversation_id()
                        st.session_state.history = []
                        st.session_state.user_chunks = []
                        st.session_state.user_index = None
                        st.session_state.ingested_file = None
                    st.rerun()

    st.divider()
    st.header("Documents")
    uploaded = st.file_uploader(
        "Upload a file to chat with",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=False,
    )

    if uploaded:
        save_path = UPLOADS_DIR / uploaded.name
        save_path.write_bytes(uploaded.getbuffer())
        if st.session_state.ingested_file != uploaded.name:
            with st.spinner(f"Ingesting {uploaded.name}..."):
                chunk_dicts, index = ingest_file(str(save_path))
                st.session_state.user_chunks = chunk_dicts
                st.session_state.user_index = index
                st.session_state.ingested_file = uploaded.name
            st.toast(f"Ready — {len(chunk_dicts)} chunks indexed", icon="✅")
        else:
            st.toast(f"{uploaded.name} already loaded", icon="📄")

    if st.session_state.ingested_file:
        st.caption(f"Active file: {st.session_state.ingested_file}")

    st.divider()
    if st.button("Delete this chat", use_container_width=True):
        delete_conversation(st.session_state.conversation_id)
        st.session_state.conversation_id = new_conversation_id()
        st.session_state.history = []
        st.session_state.user_chunks = []
        st.session_state.user_index = None
        st.session_state.ingested_file = None
        st.rerun()

# ── Chat input — captured before welcome check ────────────────────────────────
prompt = st.chat_input("Ask Echo anything about Barbados immigration...")

# Resolve starter prompt
effective_prompt = prompt or st.session_state.starter_used
if st.session_state.starter_used:
    st.session_state.starter_used = None  # consume immediately

# ── Welcome screen ────────────────────────────────────────────────────────────
if not st.session_state.history and not effective_prompt:
    # Top spacer — pushes text to visual centre of the viewport
    st.markdown('<div style="height: 18vh;"></div>', unsafe_allow_html=True)

    # Welcome heading + subtitle — normal flow, centred
    st.markdown("""
    <div style="text-align: center; padding: 0 2rem;">
        <div style="
            font-size: 2.8rem;
            font-weight: 700;
            color: white;
            letter-spacing: 0.06em;
            text-shadow: 0 2px 24px rgba(14, 165, 233, 0.55);
        ">Hi, I'm Echo ✦</div>
        <div style="
            font-size: 1.05rem;
            color: rgba(255, 255, 255, 0.72);
            max-width: 460px;
            margin: 0.9rem auto 0;
            line-height: 1.6;
        ">Your Barbados immigration guide. Ask me anything about visas,
        permits, and entry requirements.</div>
    </div>
    """, unsafe_allow_html=True)

    # Gap between text and starter pills
    st.markdown('<div style="height: 2rem;"></div>', unsafe_allow_html=True)

    # Starter prompt pills — 2-column grid, directly below the text
    cols = st.columns(2)
    for i, starter in enumerate(STARTER_PROMPTS):
        with cols[i % 2]:
            if st.button(starter, key=f"starter_{i}", use_container_width=True):
                st.session_state.starter_used = starter
                st.rerun()

# ── Chat display ──────────────────────────────────────────────────────────────
for msg in st.session_state.history:
    avatar = echo_avatar() if msg["role"] == "assistant" else "user"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# ── Process prompt ────────────────────────────────────────────────────────────
if effective_prompt:
    with st.chat_message("user"):
        st.markdown(effective_prompt)

    with st.chat_message("assistant", avatar=echo_avatar()):
        with st.spinner("Thinking..."):
            reply, source_chunks = get_reply(effective_prompt)
        st.markdown(reply)

    # Source citations — rendered below the assistant bubble
    unique_sources = {}
    for c in source_chunks:
        url = c.get("source_url", "")
        if url and url not in unique_sources:
            unique_sources[url] = c["page_title"]
    if unique_sources:
        links = " &nbsp;·&nbsp; ".join(
            f'<a href="{url}" target="_blank" style="'
            'color:rgba(220,180,190,0.85);font-size:0.72rem;'
            'text-decoration:none;">{title}</a>'
            for url, title in unique_sources.items()
        )
        st.markdown(
            f'<div style="padding-left:3.5rem;margin-top:-0.3rem;'
            f'margin-bottom:0.75rem;">{links}</div>',
            unsafe_allow_html=True,
        )

    st.session_state.history.append({"role": "user", "content": effective_prompt})
    st.session_state.history.append({"role": "assistant", "content": reply})
    save_conversation(st.session_state.conversation_id, st.session_state.history)
    st.rerun()
