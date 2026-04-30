import argparse
import re
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

BASE_URL = "https://help.roomvu.com/en/"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "knowledge" / "roomvu_help_center.md"


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self.links.add(href)


class TextParser(HTMLParser):
    skip_tags = {"script", "style", "noscript", "svg"}
    block_tags = {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.skip_tags:
            self._skip_depth += 1
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.skip_tags and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text + " ")

    def text(self) -> str:
        raw = unescape("".join(self.parts))
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        return raw.strip()


def fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": "roomvu-support-knowledge-sync/1.0"}, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_links(html: str, page_url: str) -> set[str]:
    parser = LinkParser()
    parser.feed(html)
    out: set[str] = set()
    for href in parser.links:
        url = urljoin(page_url, href)
        parsed = urlparse(url)
        if parsed.netloc != "help.roomvu.com":
            continue
        clean = parsed._replace(query="", fragment="").geturl()
        if "/en/collections/" in clean or "/en/articles/" in clean:
            out.add(clean)
    return out


def title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("Home |") and line != "Skip to main content":
            return line[:140]
    return fallback


def discover_articles(base_url: str, delay: float) -> list[str]:
    home = fetch(base_url)
    collection_urls = sorted(url for url in extract_links(home, base_url) if "/en/collections/" in url)
    article_urls: set[str] = set(url for url in extract_links(home, base_url) if "/en/articles/" in url)
    for url in collection_urls:
        time.sleep(delay)
        html = fetch(url)
        article_urls.update(url for url in extract_links(html, url) if "/en/articles/" in url)
    return sorted(article_urls)


def build_knowledge(article_urls: list[str], delay: float, limit: int | None = None) -> str:
    lines = [
        "# roomvu Help Center articles",
        "",
        "Source: https://help.roomvu.com/en/",
        "",
        "These articles are synced for support draft grounding. Human agents must review drafts before sending.",
        "",
    ]
    selected = article_urls[:limit] if limit else article_urls
    for idx, url in enumerate(selected, start=1):
        if idx > 1:
            time.sleep(delay)
        html = fetch(url)
        text = TextParser()
        text.feed(html)
        body = text.text()
        title = title_from_text(body, url.rsplit("/", 1)[-1].replace("-", " ").title())
        lines.extend([
            f"## {title}",
            "",
            f"URL: {url}",
            "",
            body,
            "",
        ])
        print(f"[{idx}/{len(selected)}] synced {url}")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync roomvu Help Center articles into the assistant knowledge base.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--delay", type=float, default=1.0, help="Polite crawl delay in seconds")
    parser.add_argument("--limit", type=int, default=None, help="Optional article limit for testing")
    args = parser.parse_args()

    articles = discover_articles(args.base_url, args.delay)
    print(f"Discovered {len(articles)} article(s).")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_knowledge(articles, args.delay, args.limit), encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
