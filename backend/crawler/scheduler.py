import threading
import logging
from typing import Optional, Dict, Any
from backend.crawler.crawler import CollegeCrawler
from backend.database import get_setting

logger = logging.getLogger("crawler_scheduler")

class CrawlerScheduler:
    def __init__(self, crawler: CollegeCrawler):
        self.crawler = crawler
        self.interval_seconds = 6 * 3600  # Default: every 6 hours
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_run_result: Optional[Dict[str, Any]] = None

    def start(self, interval_hours: float = 6.0):
        self.interval_seconds = int(interval_hours * 3600)
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="CrawlerScheduler")
        self._thread.start()
        logger.info(f"Background crawler scheduler started (interval: {interval_hours}h)")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run_loop(self):
        # Wait a full interval before the first scheduled run. An empty index
        # is already crawled at startup (run.py / app lifespan), so crawling
        # again seconds after boot would just duplicate that work.
        while not self._stop_event.wait(self.interval_seconds):
            try:
                target_url = get_setting("college_website_url", "https://iiitkottayam.ac.in/#!/home")
                logger.info(f"Triggering scheduled crawl for {target_url}")
                self.last_run_result = self.crawler.run_sync(target_url=target_url)
            except Exception as e:
                logger.error(f"Error during scheduled crawl: {e}")

    def sync_now(self, target_url: Optional[str] = None) -> Dict[str, Any]:
        result = self.crawler.run_sync(target_url=target_url)
        self.last_run_result = result
        return result
