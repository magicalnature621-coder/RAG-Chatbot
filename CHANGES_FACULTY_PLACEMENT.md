# Faculty & Placement fix

## Root cause
- The crawler fetched the raw AngularJS template for /faculty and /placement.
  Those templates only hold placeholders (`{{faculty.name}}`), so the index had
  no names, departments, phones or emails (the faculty chunk was literally
  "contact_phone location_onRoom ... insert_link").
- Real rendering needs Playwright. Without it the placeholders were indexed
  and the page was marked "unchanged" on every later sync.
- Even with real text, 220-word chunks and top-5 retrieval cannot return all
  faculty members for "list all faculty".

## What changed
- backend/crawler/dynamic_pages.py (new): renders the SPA route, waits for
  Angular to replace placeholders, rejects output that still has placeholders,
  parses HTML tables into records, and saves debug dumps to data/debug/.
- backend/rag/structured.py (new): stores full faculty/placement records in
  data/structured.json and detects faculty/placement questions.
- backend/crawler/crawler.py: /faculty and /placement go through the structured
  path. If no real records are found, the stale entries are removed instead of
  keeping placeholder text.
- backend/rag/pipeline.py: faculty/placement questions receive the complete
  record set as the first context chunk. In local (no-LLM) mode, a faculty
  question returns the full table directly.

## How to apply
1. Copy the files over the project.
2. pip install playwright && playwright install chromium
3. python scripts/diagnose_dynamic_pages.py  (check the record counts; the
   output also lists the XHR URLs the page calls)
4. Click "Crawl & Sync Now" in the UI (or POST /api/crawler/sync).
5. Check data/structured.json and try: "list all faculty", "email of the CSE
   professors", "what are the placement packages".

## Known limits
- The live Faculty page uses cards, not tables. extract_faculty tries tables
  first, then the card parser (extract_faculty_cards), which reads name,
  designation, research areas, qualification, phone, room and email (the site
  writes emails as "name at iiitkottayam dot ac.in"). If the site's card markup
  changes and diagnose_dynamic_pages.py reports 0 records, update the selectors
  in extract_faculty_cards from data/debug/faculty.html.
- The placement text includes the site navigation menu, which is noisy.
  Tightening it needs the page's main content selector.
- Intent words such as "email" or "director" will also trigger the faculty
  list. That is intentional for now, but it can be narrowed.
