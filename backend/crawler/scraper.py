import re
import urllib.parse
from html.parser import HTMLParser
from typing import List, Tuple, Dict, Any, Set, Optional

class SmartHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.fed: List[str] = []
        self.links: List[str] = []
        self.title: str = ""
        self.in_title: bool = False
        self.ignore_depth: int = 0
        # Only tags that always have a closing tag may go here: the depth counter
        # is decremented on the end tag. Void elements like <meta>/<link> never
        # close, so listing them made everything after the first <meta> vanish
        # from browser-rendered pages. They carry no text anyway.
        self.ignore_tags: Set[str] = {'script', 'style', 'noscript', 'svg', 'template'}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag_lower = tag.lower()
        if tag_lower in self.ignore_tags:
            self.ignore_depth += 1
            return

        if tag_lower == 'title':
            self.in_title = True

        if tag_lower == 'a':
            for name, val in attrs:
                if name.lower() == 'href' and val:
                    val = val.strip()
                    if not val.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                        absolute_url = urllib.parse.urljoin(self.base_url, val)
                        if '#!' not in absolute_url:
                            absolute_url = absolute_url.split('#')[0]
                        self.links.append(absolute_url)

        # Block-level whitespace
        if tag_lower in {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'tr', 'table', 'br', 'section', 'article', 'th', 'td'}:
            self.fed.append(' ')

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower in self.ignore_tags:
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return

        if tag_lower == 'title':
            self.in_title = False

        if self.ignore_depth > 0:
            return

        if tag_lower in {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'tr', 'section', 'article'}:
            self.fed.append('\n')
        elif tag_lower in {'th', 'td'}:
            self.fed.append(' | ')

    def handle_data(self, data: str):
        if self.ignore_depth > 0:
            return
        if self.in_title and not self.title:
            self.title = data.strip()
        cleaned = data.strip()
        if cleaned:
            # Trailing space prevents adjacent inline text nodes (e.g. a label
            # and a value in neighboring <span>s) from being fused into one
            # run-together word when there's no block-level tag between them.
            self.fed.append(cleaned + ' ')

    def get_text(self) -> str:
        raw_text = ''.join(self.fed)
        # Strip unrendered AngularJS bindings like {{faculty.name}}. If a page
        # couldn't be JS-rendered (Playwright missing, or the render failed),
        # these leak through as literal template syntax rather than data -
        # better to drop them than index them as if they were real content.
        raw_text = re.sub(r'\{\{[^{}]*\}\}', '', raw_text)
        # Angular's own ng-if fallback text for "no data yet" - not real
        # page content either.
        raw_text = re.sub(
            r'Nothing to Display\.?\s*This happen\w*\s*because the request data is not available\.?',
            '', raw_text, flags=re.IGNORECASE
        )
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in raw_text.splitlines()]
        cleaned_lines = [l for l in lines if l]
        return '\n'.join(cleaned_lines)

def parse_html(html_content: str, url: str) -> Dict[str, Any]:
    parser = SmartHTMLParser(base_url=url)
    try:
        parser.feed(html_content)
    except Exception:
        pass
    
    clean_text = parser.get_text()
    title = parser.title or url.split('/')[-1] or "College Page"
    
    return {
        "url": url,
        "title": title,
        "text": clean_text,
        "links": list(set(parser.links))
    }
