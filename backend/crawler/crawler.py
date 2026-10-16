import urllib.request
import urllib.parse
import re
import hashlib
import time
import logging
import threading
from typing import Dict, Any, List, Optional, Set
from collections import deque

from backend.crawler.scraper import parse_html
from backend.crawler.dynamic_pages import (
    render_dynamic_page,
    save_debug_dump,
    extract_faculty,
    extract_placement_rows,
    has_unrendered_placeholders,
)
from backend.rag.structured import load_structured, save_structured, faculty_document, placement_document
from backend.database import get_crawled_page, upsert_crawled_page, get_setting, set_setting

logger = logging.getLogger("crawler")

# SPA routes whose content is loaded by XHR and needs the structured path.
STRUCTURED_ROUTES = {"/faculty", "/placement"}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def _get_playwright_sync():
    """
    Returns the playwright sync_playwright entrypoint if the package (and its
    browser binaries) are installed, else None. Kept as a soft dependency:
    the crawler still works without it, just can't see JS-rendered content.
    """
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def render_with_browser(browser, url: str, wait_ms: int = 2500, timeout_ms: int = 20000) -> Optional[str]:
    """
    Loads `url` in a real headless browser and returns the fully rendered
    DOM. This is what lets AngularJS pages that fetch their data via AJAX
    (e.g. Faculty Directory, which binds {{faculty.name}} after an XHR call)
    show up with real content instead of unrendered template placeholders.
    """
    try:
        page = browser.new_page(user_agent=USER_AGENT)
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception:
            # Some SPA routes never go fully idle (polling, etc.) - a plain
            # load is still far better than nothing.
            page.goto(url, wait_until="load", timeout=timeout_ms)
        page.wait_for_timeout(wait_ms)  # let Angular's digest cycle settle after any XHR
        content = page.content()
        page.close()
        return content
    except Exception as e:
        logger.warning(f"Playwright render failed for {url}: {e}")
        return None


def fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type or "text/plain" in content_type or "application/javascript" in content_type or "text/javascript" in content_type or url.endswith(('.html', '.htm', '.js', '.txt')):
                charset = "utf-8"
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip()
                return response.read().decode(charset, errors="ignore")
    except Exception as e:
        logger.warning(f"Error fetching {url}: {e}")
        return None
    return None

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

class CollegeCrawler:
    def __init__(self, vector_store=None):
        self.vector_store = vector_store
        self.is_running = False
        self.last_sync_time = None
        # Manual sync, the scheduler and the startup crawl all share one
        # crawler; only one may write to the index at a time.
        self._sync_lock = threading.Lock()

    def crawl_iiit_kottayam(self, base_url: str = "https://iiitkottayam.ac.in", max_views: int = 50) -> Dict[str, Any]:
        """Custom SPA crawler tailored for IIIT Kottayam's AngularJS router"""
        logger.info("Starting IIIT Kottayam SPA crawl...")
        app_js_url = urllib.parse.urljoin(base_url, "scripts/app.js")
        app_js_content = fetch_url(app_js_url)

        view_map = []
        if app_js_content:
            # Pattern matches .when('/route', { templateUrl: 'views/xxx.html' })
            pattern = r'\.when\(\s*["\']([^"\']+)["\']\s*,\s*\{.*?templateUrl\s*:\s*(?:function\(\)\s*\{\s*return\s*["\']([^"\']+)["\']|["\']([^"\']+)["\'])'
            matches = re.findall(pattern, app_js_content, re.DOTALL)
            for route, t1, t2 in matches:
                template = (t1 or t2).split('?')[0].strip()
                if template and template.endswith('.html'):
                    view_map.append((route, template))

        # Core high-priority fallback views if app.js regex misses anything
        priority_views = [
            ("/home", "views/home.html", "Welcome to IIIT Kottayam"),
            ("/admission", "views/admission.html", "Admission | IIIT Kottayam"),
            ("/placement", "views/placement.html", "Training & Placements | IIIT Kottayam"),
            ("/btech_cs_home", "views/btech_cs_home.html", "B.Tech Computer Science | IIIT Kottayam"),
            ("/btech_ec_home", "views/btech_ec_home.html", "B.Tech Electronics & Comm. | IIIT Kottayam"),
            ("/btech_cyber_home", "views/btech_cyber_home.html", "B.Tech Cyber Security | IIIT Kottayam"),
            ("/btech_ai_home", "views/btech_ai_home.html", "B.Tech AI & Data Science | IIIT Kottayam"),
            ("/btech_MnC_home", "views/btech_MnC_home.html", "B.Tech Mathematics & Computing | IIIT Kottayam"),
            ("/mtech_home", "views/mtech_home.html", "M.Tech Programmes | IIIT Kottayam"),
            ("/mtech_cyber", "views/mtech_cyber.html", "M.Tech Cyber Security | IIIT Kottayam"),
            ("/phd_home", "views/phd_home.html", "PhD Admissions | IIIT Kottayam"),
            ("/faculty", "views/faculty.html", "Faculty Directory | IIIT Kottayam"),
            ("/antiragging", "views/antiRagging.html", "Anti Ragging Policy | IIIT Kottayam"),
            ("/culturalClub", "views/culturalClub.html", "Cultural Clubs | IIIT Kottayam"),
            ("/technical", "views/technical.html", "Technical Clubs | IIIT Kottayam"),
            ("/adminstaff", "views/adminstaff.html", "Administration Staff | IIIT Kottayam"),
            ("/dept_head", "views/dept_head.html", "Department Heads | IIIT Kottayam"),
            ("/campus", "views/campus.html", "Campus Facilities | IIIT Kottayam")
        ]

        # Combine discovered views with priority list
        processed_routes = set()
        all_targets = []
        
        for route, template, title in priority_views:
            all_targets.append((route, template, title))
            processed_routes.add(route)

        for route, template in view_map:
            if route not in processed_routes and ":" not in route and len(all_targets) < max_views:
                title = f"{route.strip('/').replace('_', ' ').title()} | IIIT Kottayam"
                all_targets.append((route, template, title))
                processed_routes.add(route)

        stats = {
            "total_targets": len(all_targets),
            "crawled": 0,
            "new_or_updated": 0,
            "unchanged": 0,
            "failed": 0,
            "chunks_indexed": 0,
            "pages": [],
            "rendered_with_browser": False
        }

        # Try to get a headless browser for pages whose content only appears
        # after JavaScript runs (e.g. Faculty Directory, which fills in
        # {{faculty.name}} via an AJAX call rather than shipping real names
        # in the static HTML). Soft dependency: falls back cleanly if
        # Playwright isn't installed.
        sync_playwright_fn = _get_playwright_sync()
        pw_ctx = None
        browser = None
        if sync_playwright_fn:
            try:
                pw_ctx = sync_playwright_fn().start()
                browser = pw_ctx.chromium.launch(headless=True)
                stats["rendered_with_browser"] = True
                logger.info("Playwright available - rendering pages with a headless browser to capture JS-driven content.")
            except Exception as e:
                logger.warning(f"Could not start Playwright browser ({e}) - falling back to static HTML fetch.")
                browser = None
        else:
            logger.warning(
                "Playwright not installed - dynamic/JS-rendered pages (e.g. Faculty Directory) "
                "will only show unrendered template placeholders. Run 'pip install playwright "
                "&& playwright install chromium' for real content on those pages."
            )

        try:
            for route, template_path, default_title in all_targets:
                template_url = urllib.parse.urljoin(base_url, template_path)
                public_url = f"https://iiitkottayam.ac.in/#!{route}"

                title_override = None
                if route in STRUCTURED_ROUTES:
                    # Faculty / Placement: render, extract records, and refuse
                    # to index unrendered Angular placeholders.
                    clean_text, title_override = self._structured_text(browser, route, public_url)
                    if not clean_text:
                        stats["failed"] += 1
                        logger.warning(f"No usable structured content for {public_url}; removing stale index entries.")
                        if self.vector_store:
                            self.vector_store.delete_document(public_url)
                            self.vector_store.save()
                        continue
                    parsed = {"title": title_override}
                else:
                    raw_html = None
                    if browser:
                        # Navigate the real SPA URL so app.js/controllers actually
                        # run and populate any data-bound content.
                        raw_html = render_with_browser(browser, public_url)
                    if not raw_html:
                        # No browser available, or rendering failed - fall back
                        # to the static Angular template fetch (works fine for
                        # plain static pages, e.g. most B.Tech programme pages).
                        raw_html = fetch_url(template_url)
                    if not raw_html:
                        stats["failed"] += 1
                        continue

                    parsed = parse_html(raw_html, public_url)
                    clean_text = parsed["text"]

                # Skip templates that have negligible text content
                if len(clean_text) < 40:
                    continue

                title = title_override or default_title or parsed["title"]
                content_hash = compute_hash(clean_text)

                # Change detection check
                existing_page = get_crawled_page(public_url)
                is_changed = (existing_page is None) or (existing_page.get("content_hash") != content_hash)

                chunk_count = 0
                if is_changed:
                    # Ingest into vector store
                    if self.vector_store:
                        chunk_count = self.vector_store.upsert_document(
                            doc_id=public_url,
                            title=title,
                            text=clean_text,
                            source_url=public_url
                        )
                    status = "updated" if existing_page else "new"
                    upsert_crawled_page(public_url, title, content_hash, chunk_count, status)
                    stats["new_or_updated"] += 1
                    stats["chunks_indexed"] += chunk_count
                else:
                    chunk_count = existing_page.get("chunk_count", 0)
                    status = "unchanged"
                    upsert_crawled_page(public_url, title, content_hash, chunk_count, status)
                    stats["unchanged"] += 1

                stats["crawled"] += 1
                stats["pages"].append({
                    "url": public_url,
                    "title": title,
                    "status": status,
                    "chunks": chunk_count
                })

                # Small delay to be polite to the server
                time.sleep(0.05)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if pw_ctx:
                try:
                    pw_ctx.stop()
                except Exception:
                    pass

        return stats

    def _structured_text(self, browser, route: str, public_url: str):
        """
        Returns (indexable_text, title) for Faculty / Placement, or (None, None)
        when the page could not be rendered into real records. Persists the
        records to data/structured.json for exact list answers.
        """
        if not browser:
            logger.warning(
                f"{public_url} needs a headless browser to load its data. "
                "Install with: pip install playwright && playwright install chromium"
            )
            return None, None

        rendered = render_dynamic_page(browser, public_url)
        if not rendered:
            return None, None
        save_debug_dump(route.strip("/"), rendered)  # data/debug/<route>.html + _xhr.json

        data = load_structured()
        if route == "/faculty":
            records = extract_faculty(rendered["html"])
            if len(records) < 3:
                logger.warning(
                    f"Faculty page rendered but only {len(records)} records were parsed. "
                    "Check data/debug/faculty.html and faculty_xhr.json."
                )
                return None, None
            data["faculty"] = records
            save_structured(data)
            logger.info(f"Extracted {len(records)} faculty records.")
            return faculty_document(records), "Faculty Directory | IIIT Kottayam"

        if route == "/placement":
            lines = extract_placement_rows(rendered["html"])
            page_text = parse_html(rendered["html"], public_url)["text"]
            if has_unrendered_placeholders(page_text):
                logger.warning("Placement page still contains unrendered placeholders.")
                return None, None
            if not lines and len(page_text) < 200:
                return None, None
            data["placement_lines"] = lines
            data["placement_text"] = page_text
            save_structured(data)
            logger.info(f"Extracted {len(lines)} placement table rows.")
            return placement_document(lines, page_text), "Training & Placements | IIIT Kottayam"

        return None, None

    def crawl_standard(self, start_url: str, max_pages: int = 30) -> Dict[str, Any]:
        """Generic standard web crawler for regular websites"""
        domain = urllib.parse.urlparse(start_url).netloc
        queue = deque([start_url])
        visited: Set[str] = set()
        
        stats = {
            "total_targets": 0,
            "crawled": 0,
            "new_or_updated": 0,
            "unchanged": 0,
            "failed": 0,
            "chunks_indexed": 0,
            "pages": []
        }

        while queue and len(visited) < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            raw_html = fetch_url(url)
            if not raw_html:
                stats["failed"] += 1
                continue

            parsed = parse_html(raw_html, url)
            clean_text = parsed["text"]
            if len(clean_text) < 50:
                continue

            title = parsed["title"]
            content_hash = compute_hash(clean_text)

            existing = get_crawled_page(url)
            is_changed = (existing is None) or (existing.get("content_hash") != content_hash)
            chunk_count = 0

            if is_changed:
                if self.vector_store:
                    chunk_count = self.vector_store.upsert_document(
                        doc_id=url,
                        title=title,
                        text=clean_text,
                        source_url=url
                    )
                status = "updated" if existing else "new"
                upsert_crawled_page(url, title, content_hash, chunk_count, status)
                stats["new_or_updated"] += 1
                stats["chunks_indexed"] += chunk_count
            else:
                chunk_count = existing.get("chunk_count", 0)
                status = "unchanged"
                upsert_crawled_page(url, title, content_hash, chunk_count, status)
                stats["unchanged"] += 1

            stats["crawled"] += 1
            stats["pages"].append({
                "url": url,
                "title": title,
                "status": status,
                "chunks": chunk_count
            })

            # Queue internal links
            for link in parsed.get("links", []):
                link_domain = urllib.parse.urlparse(link).netloc
                if link_domain == domain and link not in visited and len(visited) + len(queue) < max_pages:
                    queue.append(link)

            time.sleep(0.1)

        return stats

    def run_sync(self, target_url: str = "https://iiitkottayam.ac.in/#!/home") -> Dict[str, Any]:
        """Main sync orchestrator"""
        if not self._sync_lock.acquire(blocking=False):
            logger.info("Sync requested while another sync is running; skipping.")
            return {"status": "in_progress", "crawled": 0, "new_or_updated": 0, "unchanged": 0,
                    "failed": 0, "chunks_indexed": 0, "pages": []}
        self.is_running = True
        try:
            target_url = target_url or get_setting("college_website_url", "https://iiitkottayam.ac.in/#!/home")
            set_setting("college_website_url", target_url)

            if "iiitkottayam.ac.in" in target_url:
                result = self.crawl_iiit_kottayam(base_url="https://iiitkottayam.ac.in", max_views=40)
            else:
                result = self.crawl_standard(start_url=target_url, max_pages=30)

            self.last_sync_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            set_setting("last_sync_time", self.last_sync_time)
            result["last_sync_time"] = self.last_sync_time
            return result
        finally:
            self.is_running = False
            self._sync_lock.release()
