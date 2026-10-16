"""
Run this once on your machine to see what the Faculty and Placement pages
really contain after JavaScript has run.

    pip install playwright && playwright install chromium
    python scripts/diagnose_dynamic_pages.py

It writes data/debug/<page>.html (rendered DOM), data/debug/<page>_xhr.json
(every XHR/fetch call the page made) and prints how many faculty records and
placement rows the extractor found. If the record count is 0, send the two
files from data/debug/ and the extractor can be adjusted to the exact markup.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from playwright.sync_api import sync_playwright  # noqa: E402

from backend.crawler.dynamic_pages import (  # noqa: E402
    render_dynamic_page,
    save_debug_dump,
    extract_faculty,
    extract_placement_rows,
    has_unrendered_placeholders,
)

PAGES = {
    "faculty": "https://iiitkottayam.ac.in/#!/faculty",
    "placement": "https://iiitkottayam.ac.in/#!/placement",
}


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for name, url in PAGES.items():
            print(f"\n=== {name}: {url}")
            rendered = render_dynamic_page(browser, url)
            if not rendered:
                print("  render failed (see warning above)")
                continue
            save_debug_dump(name, rendered)
            html = rendered["html"]
            print(f"  placeholders still present: {has_unrendered_placeholders(html)}")
            print(f"  XHR/fetch calls made: {len(rendered['xhr'])}")
            for x in rendered["xhr"][:15]:
                print(f"    [{x['status']}] {x['url']}")
            if name == "faculty":
                recs = extract_faculty(html)
                print(f"  faculty records extracted: {len(recs)}")
                for r in recs[:5]:
                    print("   ", r)
            else:
                rows = extract_placement_rows(html)
                print(f"  placement table rows extracted: {len(rows)}")
                for line in rows[:5]:
                    print("   ", line[:160])
        browser.close()
    print("\nDebug files written to data/debug/")


if __name__ == "__main__":
    main()
