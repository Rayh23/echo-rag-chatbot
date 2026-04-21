# Echo — Design Process Explanation

## What Is Echo?

Echo is an AI-powered chat assistant built for a business environment. It can hold a conversation, remember what was said earlier in a session, and — most importantly — read documents you upload and use them to answer your questions accurately. Think of it as a knowledgeable colleague who has read every file you hand them and can answer questions about it on demand.

---

## The Problem We Were Solving

General AI assistants like ChatGPT are powerful, but they only know what they were trained on. If you ask them about your company's internal report, your specific contract, or a document unique to your organisation, they cannot help — because they have never seen it.

Echo solves this by letting you upload your own documents. It reads them, understands them, and uses that knowledge to give you accurate, relevant answers — while still being able to handle general questions when no document is provided.

---

## How It Works

Echo is built around three core ideas working together:

**1. Read the document**
When you upload a file (PDF, Word document, or plain text), Echo extracts all the text from it automatically. It handles the messy work of different file formats so you don't have to think about it.

**2. Find the relevant parts**
Rather than sending your entire document to the AI every time you ask a question (which would be slow and expensive), Echo breaks the document into smaller sections — called chunks — and finds only the sections most relevant to what you just asked. Those relevant sections are what gets passed to the AI, not the whole document.

**3. Answer with context**
The AI receives your question, the relevant document sections, and the recent conversation history — and produces a response grounded in what your document actually says.

This approach is called **Retrieval-Augmented Generation**, or RAG. It is the industry-standard method for building AI systems that work with private or specialised documents.

---

## Key Design Decisions

### Keeping costs low
Every time the AI reads a document chunk or answers a question, it costs a small amount in API usage. To minimise this, Echo caches documents — meaning if you upload the same file twice, it does not re-process it. It recognises the file has not changed and reuses the previous result instantly.

### Keeping conversations manageable
AI models can only read so much text at once. If a conversation grows very long, sending all of it with every message becomes wasteful and eventually impossible. Echo uses a token counter (a way of measuring text length the same way the AI does) and quietly trims the oldest parts of the conversation when it gets too long — keeping the most recent and relevant exchanges while staying within limits.

### Remembering conversations between sessions
Standard web applications forget everything the moment you close the browser. Echo saves your conversation history to a file on the computer running it, so when you return, the conversation picks up where it left off. Clicking "Clear conversation" wipes this cleanly.

### One tool for everything
Rather than using large, complex AI frameworks that obscure what is happening, Echo was built using direct calls to OpenAI's own tools — the same underlying technology that powers ChatGPT. This keeps the logic transparent, easy to follow, and straightforward to explain.

---

## The Interface

Echo was built using Streamlit, a tool that turns Python code into a web application without needing to build a separate website. The interface was designed to feel calm and approachable — a soft animated background, rounded message bubbles, and a clean sidebar for uploading documents. The goal was a tool that feels pleasant to use during a working day, not clinical or intimidating.

---

## Summary

Echo demonstrates how a business can give an AI assistant access to its own documents in a controlled, efficient, and cost-aware way — without sending sensitive files to a third party permanently or relying on an AI to guess at information it was never given.
