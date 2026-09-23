import json
import re
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


DEFAULT_TIMEOUT = 20
MAX_ARTICLE_CHARS = 16000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


def _clean_text(text):
    text = unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _meta(soup, *names):
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content"):
            return _clean_text(tag["content"])
    return None


def _canonical_url(soup, fallback):
    link = soup.find("link", rel=lambda value: value and "canonical" in value)
    if link and link.get("href"):
        return urljoin(fallback, link["href"])
    return fallback


def _remove_noise(soup):
    for tag in soup([
        "script", "style", "noscript", "svg", "form", "button", "nav",
        "footer", "header", "aside", "iframe"
    ]):
        tag.decompose()


def _candidate_blocks(soup):
    selectors = [
        "article",
        "[itemprop='articleBody']",
        ".article-body",
        ".article__body",
        ".detail-content",
        ".detail__content",
        ".content-detail",
        ".post-content",
        ".entry-content",
        ".fck_detail",
        ".singular-content",
    ]

    candidates = []
    for selector in selectors:
        for node in soup.select(selector):
            text = "\n".join(
                _clean_text(p.get_text(" ", strip=True))
                for p in node.find_all(["p", "h2", "h3", "li"])
                if _clean_text(p.get_text(" ", strip=True))
            )
            if len(text) >= 300:
                candidates.append(text)

    if candidates:
        return candidates

    paragraphs = [
        _clean_text(p.get_text(" ", strip=True))
        for p in soup.find_all("p")
    ]
    paragraphs = [
        p for p in paragraphs
        if len(p) >= 40
        and not re.search(
            r"(đăng ký|đăng nhập|quảng cáo|copyright|theo dõi chúng tôi)",
            p,
            flags=re.I,
        )
    ]
    return ["\n".join(paragraphs)] if paragraphs else []


def extract_article_html(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = (
        _meta(soup, "og:title", "twitter:title")
        or _clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    )
    description = _meta(
        soup,
        "og:description",
        "description",
        "twitter:description",
    )
    published = _meta(
        soup,
        "article:published_time",
        "datePublished",
        "pubdate",
    )
    canonical = _canonical_url(soup, url)

    _remove_noise(soup)
    candidates = _candidate_blocks(soup)
    body = max(candidates, key=len) if candidates else ""
    body = body[:MAX_ARTICLE_CHARS]

    return {
        "url": url,
        "canonical_url": canonical,
        "title": title,
        "description": description,
        "published": published,
        "text": body,
        "char_count": len(body),
        "readable": len(body) >= 300,
    }


def fetch_article(url, timeout=DEFAULT_TIMEOUT):
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        raise ValueError(f"Unsupported content-type: {content_type}")

    result = extract_article_html(response.text, response.url)
    result["http_status"] = response.status_code
    return result


def build_source_bundle(editorial_item, max_sources=3):
    sources = editorial_item.get("sources", [])
    ranked = sorted(
        sources,
        key=lambda s: 0 if s.get("tier") == "OFFICIAL" else 1,
    )

    bundle = []
    for source in ranked[:max_sources]:
        url = source.get("url")
        if not url:
            continue

        record = {
            "source": source.get("source"),
            "tier": source.get("tier"),
            "declared_title": source.get("title"),
            "url": url,
        }

        try:
            record["article"] = fetch_article(url)
            record["status"] = (
                "READ_OK"
                if record["article"].get("readable")
                else "READ_TOO_SHORT"
            )
        except Exception as exc:
            record["status"] = "READ_FAILED"
            record["error"] = str(exc)

        bundle.append(record)

    return bundle


def save_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
