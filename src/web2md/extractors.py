"""HTML から Markdown への変換およびメタデータ・ナビゲーション抽出モジュール。"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from markdownify import markdownify
from pydantic import BaseModel

ExtractorType = Literal["dom-markdownify", "crawl4ai"]
EXTRACTOR_METHODS: tuple[ExtractorType, ...] = ("dom-markdownify", "crawl4ai")

_MAIN_SELECTORS: tuple[str, ...] = (
    "main",
    '[role="main"]',
    "article",
    ".theme-doc-markdown",
    ".md-content",
    ".vp-doc",
    "body",
)

_UNWANTED_TAGS: tuple[str, ...] = (
    "nav",
    "footer",
    "aside",
    "script",
    "style",
    "noscript",
    "svg",
    "form",
    "button",
    "template",
)

_UNWANTED_SELECTORS: tuple[str, ...] = (
    ".breadcrumbs",
    '[aria-label*="breadcrumb" i]',
    ".pagination-nav",
    ".table-of-contents",
    ".toc",
    ".theme-edit-this-page",
    ".theme-doc-footer",
    ".hash-link",
    ".headerlink",
    ".sr-only",
    "[hidden]",
)

_CODE_LANG_CLASS_RE = re.compile(r"^(?:language|lang|highlight-source)-([a-zA-Z0-9_+-]+)$")
_EMPTY_ANCHOR_RE = re.compile(r"\[\s*\]\([^)]+\)")
_HEADING_ANCHOR_TEXT_RE = re.compile(r"^[\u200b#\u00b6\s]*$")
_PAGINATION_LINE_RE = re.compile(r"^\s*\[(?:Previous|Next)(?:\s+[^\]]*)?\]\([^)]+\)\s*$", re.IGNORECASE)
_EDIT_PAGE_LINE_RE = re.compile(r"^\s*(?:\[)?Edit this page(?:\]\([^)]+\))?\s*$", re.IGNORECASE)
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_FORMAT_RE = re.compile(r"[*_`~]")


class PageMetadata(BaseModel):
    """ページから抽出したタイトルと概要。"""

    title: str
    description: str


def _extract_lang_from_attrs(tag: Tag | None) -> str:
    if tag is None:
        return ""
    for attr in ("data-language", "data-lang"):
        val = tag.get(attr)
        if isinstance(val, str) and val.strip():
            return val.strip()
    classes = tag.get("class")
    if isinstance(classes, list):
        for cls in classes:
            if not isinstance(cls, str):
                continue
            match = _CODE_LANG_CLASS_RE.match(cls)
            if match:
                return match.group(1)
    return ""


def _detect_code_language(el: Tag) -> str:
    """`<pre>` 要素・内包 `<code>`・最大3階層上の親要素からコードブロックの言語名を検出する。"""
    code = el.find("code")
    candidates: list[Tag | None] = [code if isinstance(code, Tag) else None, el]
    parent = el.parent
    for _ in range(3):
        if not isinstance(parent, Tag):
            break
        candidates.append(parent)
        parent = parent.parent
    for candidate in candidates:
        lang = _extract_lang_from_attrs(candidate)
        if lang:
            return lang
    return ""


def _normalize_admonitions(container: Tag, soup: BeautifulSoup) -> None:
    """Docusaurus 等の Admonition 要素を Markdown の引用ブロックへ整形する。"""
    for admonition in list(container.select(".theme-admonition, .admonition")):
        if admonition.find_parent("blockquote") is not None:
            continue

        heading = admonition.select_one('[class*="admonitionHeading" i], .admonition-heading, .admonition-title')
        if heading is not None:
            heading_text = re.sub(r"\s+", " ", heading.get_text()).strip()
            if heading_text:
                p_tag = soup.new_tag("p")
                strong_tag = soup.new_tag("strong")
                strong_tag.string = heading_text
                p_tag.append(strong_tag)
                heading.replace_with(p_tag)
            else:
                heading.decompose()

        for content in list(admonition.select('[class*="admonitionContent" i], .admonition-content')):
            content.unwrap()

        admonition.name = "blockquote"


def _normalize_anchor_newlines(container: Tag) -> None:
    """`<a>` 要素内の改行を含む空白を単一スペースに正規化する。"""
    for anchor in container.find_all("a"):
        for node in list(anchor.descendants):
            if isinstance(node, NavigableString) and ("\n" in node or "\r" in node):
                if node.find_parent("pre") is not None:
                    continue
                node.replace_with(re.sub(r"\s*\r?\n\s*", " ", str(node)))


def _strip_unwanted_dom_elements(container: Tag) -> None:
    """ナビゲーション、目次、パンくず、編集リンク等のノイズ要素を DOM から除去する。"""
    for tag_name in _UNWANTED_TAGS:
        for el in list(container.find_all(tag_name)):
            el.decompose()

    for selector in _UNWANTED_SELECTORS:
        for el in list(container.select(selector)):
            el.decompose()

    for header in list(container.find_all("header")):
        if header.get("role") == "banner" or header.find("nav") is not None or header.find("h1") is None:
            header.decompose()

    for heading in container.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        for anchor in list(heading.find_all("a")):
            if _HEADING_ANCHOR_TEXT_RE.match(anchor.get_text()):
                anchor.decompose()


def _html_to_markdown(html_fragment: str) -> str:
    return markdownify(
        html_fragment,
        heading_style="ATX",
        bullets="-",
        code_language_callback=_detect_code_language,
    )


def _strip_leading_nav_lines(lines: list[str]) -> list[str]:
    """先頭の `# ` 見出しより前にある短いパンくず・目次行のみを安全に除去する。"""
    first_h1_idx: int | None = None
    for idx, line in enumerate(lines[:30]):
        if line.lstrip().startswith("# "):
            first_h1_idx = idx
            break

    if first_h1_idx is None or first_h1_idx == 0:
        return lines

    preamble = [line.strip() for line in lines[:first_h1_idx] if line.strip()]
    is_nav_preamble = all(
        len(line) <= 100
        and (line.startswith(("* ", "- ", "[")) or line.lower() in {"on this page", "table of contents", "contents"})
        for line in preamble
    )
    return lines[first_h1_idx:] if is_nav_preamble else lines


def _postprocess_markdown(markdown: str, *, strip_leading_nav: bool = False) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "")
    text = _EMPTY_ANCHOR_RE.sub("", text)

    lines = text.split("\n")
    if strip_leading_nav:
        lines = _strip_leading_nav_lines(lines)

    cleaned_lines: list[str] = []
    for line in lines:
        if _PAGINATION_LINE_RE.match(line) or _EDIT_PAGE_LINE_RE.match(line):
            continue
        cleaned_lines.append(line.rstrip())

    normalized = _MULTI_NEWLINE_RE.sub("\n\n", "\n".join(cleaned_lines))
    return normalized.strip()


def _extract_with_dom_markdownify(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    container: Tag | None = None
    for selector in _MAIN_SELECTORS:
        found = soup.select_one(selector)
        if found is not None:
            container = found
            break

    target = container if container is not None else soup
    _strip_unwanted_dom_elements(target)
    _normalize_admonitions(target, soup)
    _normalize_anchor_newlines(target)
    return _postprocess_markdown(_html_to_markdown(str(target)))


def _extract_with_crawl4ai(html: str, url: str, crawl4ai_markdown: str | None) -> str:
    if crawl4ai_markdown and crawl4ai_markdown.strip():
        return _postprocess_markdown(crawl4ai_markdown, strip_leading_nav=True)

    target_html = html
    if html.strip():
        soup = BeautifulSoup(html, "lxml")
        main_el = soup.select_one("main")
        if main_el is not None:
            target_html = str(main_el)

    generator = DefaultMarkdownGenerator()
    result = generator.generate_markdown(input_html=target_html, base_url=url, citations=False)
    return _postprocess_markdown(result.raw_markdown, strip_leading_nav=True)


def extract_markdown(
    html: str,
    url: str = "",
    method: ExtractorType = "dom-markdownify",
    crawl4ai_markdown: str | None = None,
) -> str:
    """指定した抽出手法を用いて HTML をクレンジング済み Markdown へ変換する。"""
    if not html.strip() and crawl4ai_markdown is None:
        return ""

    if method == "dom-markdownify":
        return _extract_with_dom_markdownify(html)
    if method == "crawl4ai":
        return _extract_with_crawl4ai(html, url, crawl4ai_markdown)

    raise ValueError(f"Unsupported extractor method: {method}")


def _extract_first_h1_from_markdown(markdown: str) -> str:
    in_code_block = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code_block = not in_code_block
            continue
        if not in_code_block and stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _extract_first_paragraph(markdown: str) -> str:
    in_code_block = False
    paragraph_lines: list[str] = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code_block = not in_code_block
            if paragraph_lines:
                break
            continue
        if in_code_block:
            continue
        if not stripped:
            if paragraph_lines:
                break
            continue
        if stripped.startswith(("#", "-", "*", ">", "|", "![", "---")) or re.match(r"^\d+\.\s+", stripped):
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(stripped)

    if not paragraph_lines:
        return ""

    joined = " ".join(paragraph_lines)
    joined = _MD_LINK_RE.sub(r"\1", joined)
    joined = _MD_FORMAT_RE.sub("", joined)
    return re.sub(r"\s+", " ", joined).strip()


def _truncate_text(text: str, max_length: int = 150) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_length:
        return clean
    return clean[: max_length - 3].rstrip() + "..."


def _clean_html_title(raw_title: str) -> str:
    title = re.sub(r"\s+", " ", raw_title).strip()
    for sep in (" | ", " - ", " — ", " · "):
        if sep in title:
            prefix = title.split(sep, 1)[0].strip()
            if prefix:
                return prefix
    return title


def extract_page_metadata(html: str, markdown: str, fallback_title: str = "") -> PageMetadata:
    """HTML と変換後 Markdown からページのタイトルおよび概要文を抽出する。"""
    soup = BeautifulSoup(html, "lxml") if html.strip() else BeautifulSoup("", "lxml")

    title = _extract_first_h1_from_markdown(markdown)
    if not title:
        h1 = soup.find("h1")
        if h1 is not None:
            for anchor in list(h1.find_all("a")):
                if _HEADING_ANCHOR_TEXT_RE.match(anchor.get_text()):
                    anchor.decompose()
            title = re.sub(r"\s+", " ", h1.get_text()).strip()

    if not title:
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title is not None and isinstance(og_title.get("content"), str):
            title = str(og_title["content"]).strip()

    if not title and soup.title is not None:
        title = _clean_html_title(soup.title.get_text())

    if not title:
        title = fallback_title.strip() or "Untitled"

    description = ""
    for meta_selector in ('meta[name="description"]', 'meta[property="og:description"]'):
        meta = soup.select_one(meta_selector)
        if meta is not None and isinstance(meta.get("content"), str):
            candidate = str(meta["content"]).strip()
            if candidate:
                description = _truncate_text(candidate)
                break

    if not description:
        first_para = _extract_first_paragraph(markdown)
        if first_para:
            description = _truncate_text(first_para)

    if not description:
        description = title

    return PageMetadata(title=title, description=description)


def extract_sidebar_links(html: str, base_url: str) -> list[str]:
    """サイドバーやナビゲーション DOM からドキュメントリンクを出現順に抽出する。"""
    if not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(base_url).netloc.lower() if base_url else ""

    sidebar_selectors = (
        "aside nav",
        "nav.menu",
        ".sidebar",
        ".bd-sidebar",
        ".md-sidebar--primary",
        ".VPSidebar",
        "aside",
        "nav",
    )

    candidate_links: list[str] = []
    seen: set[str] = set()

    for selector in sidebar_selectors:
        containers = soup.select(selector)
        if not containers:
            continue
        for container in containers:
            aria_label = str(container.get("aria-label") or "").lower()
            raw_classes = container.get("class")
            classes = (
                " ".join(str(c) for c in raw_classes).lower()
                if isinstance(raw_classes, list)
                else str(raw_classes or "").lower()
            )
            if "breadcrumb" in aria_label or "pagination" in classes or "table-of-contents" in classes:
                continue

            for anchor in container.find_all("a", href=True):
                href = str(anchor["href"]).strip()
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                abs_url = urljoin(base_url, href) if base_url else href
                parsed = urlparse(abs_url)
                if parsed.scheme and parsed.scheme not in ("http", "https"):
                    continue
                if base_host and parsed.netloc and parsed.netloc.lower() != base_host:
                    continue

                clean_url = parsed._replace(fragment="").geturl()
                if clean_url not in seen:
                    seen.add(clean_url)
                    candidate_links.append(clean_url)
        if candidate_links:
            break

    return candidate_links
