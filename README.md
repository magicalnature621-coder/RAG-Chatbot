# IIIT Kottayam CampusBot: Live RAG AI Chatbot with Auto-Sync Web Crawler

An end-to-end, production-grade **Retrieval-Augmented Generation (RAG)** web application designed specifically for **IIIT Kottayam (`https://iiitkottayam.ac.in/#!/home`)**.

Featuring a **ChatGPT/Claude-style conversational UI**, **User Authentication (Login/Register)**, **Persistent Chat History continuation**, an **SPA-Aware Web Crawler** with **SHA-256 change detection**, and a **hybrid vector retrieval engine** that answers college questions with live citations.

---

## Key Features

1. **ChatGPT-Style Web Interface**:
   - Left sidebar displaying past chat sessions for each user.
   - Click to reopen previous conversations and continue chatting right where you left off.
   - `+ New Chat` button to begin new threads.
   - Markdown rendering for tables, lists, and bold text.
   - Voice input dictation via Web Speech API.

2. **User Authentication & Session Security**:
   - User registration and login powered by PBKDF2 HMAC SHA-256 password hashing with unique salts.
   - Session tokens persisted per user in SQLite (`data/college_rag.db`).

3. **SPA-Aware Web Crawler & Document Loaders**:
   - Specially built to traverse IIIT Kottayam's AngularJS router (`scripts/app.js`), discovering and indexing over 40+ official view templates (`views/admission.html`, `views/placement.html`, `views/btech_cs_home.html`, faculty pages, etc.).
   - Canonical URL mapping: Links extracted chunks directly to user-facing routes like `https://iiitkottayam.ac.in/#!/placement`.

4. **Automated Change Detection & Auto-Syncing**:
   - Calculates **SHA-256 content hashes** for each crawled webpage.
   - If a page has changed or new announcements are added, it removes stale chunks and dynamically upserts new vector embeddings into the vector store.
   - Background periodic daemon timer + manual **"Crawl & Sync Now"** button in the UI.

5. **Multi-Model LLM Engine**:
   - **Groq** (Llama 3.3 70B / 3.1 8B) - ultra-fast inference with free tier.
   - **Google Gemini** (Gemini 1.5/2.5 Flash).
   - **OpenAI** (GPT-4o-mini).
   - **Built-in Offline Fallback**: Works 100% locally with grounded extractive synthesis if no API key is provided, guaranteeing zero crashes.

6. **Clickable Source Citations**:
   - Every answer cites the exact official webpage and includes clickable badge links directly to `iiitkottayam.ac.in`.

---

## Architecture Diagram

```
+--------------------------------------------------------------------------------------------------+
|                                    Client Web Interface                                          |
|                                                                                                  |
|  +---------------------------+  +-------------------------------------------------------------+  |
|  |     Sidebar (History)     |  |                    Main Chat Area                           |  |
|  |  +---------------------+  |  |  +--------------------------------------------------------+ |  |
|  |  | [+ New Chat]        |  |  |  | Header: [IIITK CampusBot] [Groq/Gemini/Local] [Sync]   | |  |
|  |  +---------------------+  |  |  +--------------------------------------------------------+ |  |
|  |  | Past Chat Sessions: |  |  |  | Q&A Stream with Citations:                             | |  |
|  |  | - "Placements 2026" |  |  |  | User: "What is the highest placement package at IIITK?" | |  |
|  |  | - "B.Tech CSE Fees" |  |  |  | Bot: "The highest CTC reached 60 LPA..."             | |  |
|  |  | - "Hostel Rules"    |  |  |  | [Source: iiitkottayam.ac.in/#!/placement] (Clickable) | |  |
|  |  +---------------------+  |  |  +--------------------------------------------------------+ |  |
|  |  | [Crawler / Sync UI] |  |  |  | Auto-expanding Input Box + Send Button                 | |  |
|  |  | [User / Logout]     |  |  +-------------------------------------------------------------+  |
|  +---------------------------+                                                                   |
+-----------------------------------------------|--------------------------------------------------+
                                                | REST API
                                                v
+--------------------------------------------------------------------------------------------------+
|                                  FastAPI Backend Server                                          |
|                                                                                                  |
|   +------------------------------------+          +------------------------------------------+   |
|   |  IIITK Crawler & Document Loader   |          |           RAG Pipeline Engine            |   |
|   |  - AngularJS Route / View Loader   |          |  - Hybrid BM25 + Cosine Vector Search    |   |
|   |  - HTML Parser & Text Cleaner      |          |  - Multi-Model LLM (Groq / Gemini /      |   |
|   |  - SHA-256 Content Hash Detection  |          |    OpenAI / Local Fallback)              |   |
|   |  - Background Periodic Sync Timer  |          |  - Strict Grounding & Anti-Hallucination |   |
|   +-----------------+------------------+          +--------------------+---------------------+   |
|                     |                                                  ^                         |
|                     | (New/Updated Chunks)                             | (Relevant Chunks)       |
|                     v                                                  |                         |
|   +------------------------------------+          +--------------------+---------------------+   |
|   |      SQLite Database               |          |       Vector Store (data/vectors.json)   |   |
|   |  - `crawled_pages` (url, hash, dt) | <----->  |  - Incremental upsert & delete by URL    |   |
|   |  - `users`, `sessions`, `messages` |          |  - Fast similarity search                |   |
|   +------------------------------------+          +------------------------------------------+   |
+--------------------------------------------------------------------------------------------------+
```

---

## Quick Start

### 1. Requirements
- Python 3.10+
- Packages installed from `requirements.txt`:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Launch the Application
Run the one-click starter:
```bash
python run.py
```

### 3. Open in Browser
Navigate to:
```
http://127.0.0.1:8000
```

---

## How to Test
1. **Sign In / Create Account**:
   - Register a new account or click **"Quick Demo Login"**.
2. **Ask Questions**:
   - *"What are the B.Tech programs offered at IIIT Kottayam?"*
   - *"What is the highest placement package?"*
   - *"Tell me about M.Tech in Cyber Security"*
   - *"What clubs and extracurricular activities are available?"*
3. **Check Citations**:
   - Notice the clickable source badges under the bot's response that take you directly to `https://iiitkottayam.ac.in/#!/placement` or `#!/admission`.
4. **Test Chat History Continuation**:
   - Click **`+ New Chat`** to start a different topic.
   - Click back to your first chat in the sidebar to see the entire previous conversation and continue chatting.
5. **Test Web Crawler & Sync**:
   - Click **"Knowledge Base"** in the sidebar.
   - Inspect the indexed view templates and their SHA-256 hashes.
   - Click **"Crawl & Sync Now"** to test live re-syncing.
