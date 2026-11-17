from __future__ import annotations

import html as html_lib
import re
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from markdownify import MarkdownConverter
from pydantic import BaseModel

ExtractorType = Literal["dom-markdownify", "crawl4ai"]
EXTRACTOR_METHODS: tuple[ExtractorType, ...] = ("dom-markdownify", "crawl4ai")

# Ordered from framework-specific content containers to generic HTML/ARIA landmarks:
# - .theme-doc-markdown: Docusaurus article body (excludes breadcrumbs, TOC, and pagination inside <main>).
# - .md-content: MkDocs Material / Zensical content column (excludes .md-sidebar inside <main class="md-main">).
# - .vp-doc: VitePress rendered Markdown container (excludes .VPDocFooter and .VPDocAside inside <main>).
# - main: Standard HTML5 main landmark (MDN <main id="content">, generic docs).
# - [role="main"]: ARIA main landmark (MkDocs default theme <div role="main">, Sphinx themes).
# - article, body: Fallbacks for blog/article pages without a main landmark.
_MAIN_SELECTORS: tuple[str, ...] = (
    ".theme-doc-markdown",
    ".md-content",
    ".vp-doc",
    "main",
    '[role="main"]',
    "article",
    "body",
)

# Non-content HTML elements inside main containers across tested documentation frameworks:
# - nav, footer: In-page navigation (breadcrumbs, pagination, footers) inside <main> (Docusaurus, VitePress, Zensical).
# - aside: Secondary sidebars, TOC panels, and announcement banners (MDN .layout__right-sidebar, VitePress, Zensical).
# - script, style, noscript, template: Embedded scripts, CSS, and Web Component shadow-DOM templates (MDN <mdn-*>).
# - svg: Inline UI icon graphics (copy, search, external link, and theme icons; <img src="...svg"> is preserved).
# - button: Interactive UI controls such as copy-code and "Back to top" buttons (Docusaurus, VitePress, Zensical).
_UNWANTED_TAGS: tuple[str, ...] = (
    "nav",
    "footer",
    "aside",
    "script",
    "style",
    "noscript",
    "svg",
    "button",
    "template",
)

# Framework-specific UI chrome and metadata blocks verified on live documentation sites:
# - .breadcrumbs, [aria-label*="breadcrumb" i]: Breadcrumb trails (Docusaurus).
# - .pagination-nav: Prev/next page navigation blocks (Docusaurus).
# - .table-of-contents, .theme-doc-toc-mobile, .theme-doc-toc-desktop, .toc: In-page TOCs (Docusaurus, MkDocs).
# - .theme-edit-this-page, .theme-doc-footer: Edit links and doc footers (Docusaurus).
# - .md-content__button: Action icon buttons ("Edit this page", "Copy as Markdown") inside content (Zensical / Material).
# - .VPDocFooter, .edit-link: Page footer and GitHub edit link (VitePress).
# - .translation-banner, .article-footer: Localization banner and feedback/last-modified footer (MDN).
# - .example-header, [class*="language-"] > span.lang: Code block language badges that duplicate fence tags (MDN, VitePress).
# - .hash-link, .headerlink, .header-anchor: Heading permalink icons (Docusaurus, MkDocs / Zensical, VitePress).
# - .sr-only, .visually-hidden, [hidden]: Screen-reader-only utility text and hidden DOM nodes (VitePress, MDN, Zensical).
_UNWANTED_SELECTORS: tuple[str, ...] = (
    ".breadcrumbs",
    '[aria-label*="breadcrumb" i]',
    ".pagination-nav",
    ".table-of-contents",
    ".theme-doc-toc-mobile",
    ".theme-doc-toc-desktop",
    ".toc",
    ".theme-edit-this-page",
    ".theme-doc-footer",
    ".md-content__button",
    ".VPDocFooter",
    ".edit-link",
    ".translation-banner",
    ".article-footer",
    ".example-header",
    '[class*="language-"] > span.lang',
    ".hash-link",
    ".headerlink",
    ".header-anchor",
    ".sr-only",
    ".visually-hidden",
    "[hidden]",
)

# Ordered sidebar navigation selectors for TOC page ordering:
# - aside nav, .VPSidebar: Standard <aside><nav> and VitePress sidebar (Docusaurus, VitePress, MDN).
# - nav.menu: Docusaurus standalone sidebar nav (<nav class="menu">).
# - .md-sidebar--primary: MkDocs Material / Zensical primary left navigation sidebar.
# - .bs-sidebar, .bd-sidebar, .sidebar: MkDocs default theme, PyData Sphinx theme, and generic sidebar containers.
# - aside, nav: Generic fallbacks when no framework-specific sidebar container is present.
_SIDEBAR_SELECTORS: tuple[str, ...] = (
    "aside nav",
    "nav.menu",
    ".md-sidebar--primary",
    ".VPSidebar",
    ".bs-sidebar",
    ".bd-sidebar",
    ".sidebar",
    "aside",
    "nav",
)

# Matches Prism/Shiki/Highlight.js `language-*` / `lang-*` and GitHub `highlight-source-*` class names.
_CODE_LANG_CLASS_RE = re.compile(r"^(?:language|lang|highlight-source)-([a-zA-Z0-9_+-]+)$")
# Strips empty Markdown links `[](...)` left by icon-only anchors while negative lookbehind preserves `![](...)` images.
_EMPTY_ANCHOR_RE = re.compile(r"(?<!!)\[\s*\]\([^)]+\)")
# Matches empty or symbol-only heading permalink anchors (\u200b in Docusaurus/VitePress, #/¶ in Zensical, \uf0c1 in MkDocs).
_HEADING_ANCHOR_TEXT_RE = re.compile(r"^[\u200b#\u00b6\uf0c1\s]*$")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
# Strips inline Markdown formatting tokens and word-boundary `_` emphasis while preserving `snake_case` identifiers.
_MD_FORMAT_RE = re.compile(r"[*`~]|(?<!\w)_|_(?!\w)")


class PageMetadata(BaseModel):
    """Extracted title and short description for a document page."""

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
        str_classes = [cls for cls in classes if isinstance(cls, str)]
        for i, cls in enumerate(str_classes):
            if match := _CODE_LANG_CLASS_RE.match(cls):
                return match.group(1)
            # MDN SyntaxHighlighter emits `class="brush: js notranslate"`, tokenized as ["brush:", "js", ...].
            if cls == "brush:" and i + 1 < len(str_classes):
                next_cls = str_classes[i + 1].strip(";")
                if next_cls and next_cls != "notranslate":
                    return next_cls
    return ""


def _detect_code_language(el: Tag) -> str:
    # Docusaurus and Shiki often place the language-* class on an outer wrapper up to 3 levels above <pre>.
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


def _strip_unwanted_dom_elements(container: Tag) -> None:
    for el in container.find_all(list(_UNWANTED_TAGS)):
        el.decompose()

    for el in container.select(", ".join(_UNWANTED_SELECTORS)):
        el.decompose()

    for header in list(container.find_all("header")):
        # Preserve article title headers (<header><h1>...</h1></header>) while dropping banner headers.
        if header.get("role") == "banner" or header.find("nav") is not None or header.find("h1") is None:
            header.decompose()

    for heading in container.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        for anchor in list(heading.find_all("a")):
            if _HEADING_ANCHOR_TEXT_RE.match(anchor.get_text()):
                anchor.decompose()
            elif str(anchor.get("href") or "").startswith("#"):
                # MDN wraps heading text in `<a class="heading-anchor" href="#...">Title</a>`; unwrap self-links.
                anchor.unwrap()


def _normalize_admonitions(container: Tag, soup: BeautifulSoup) -> None:
    for admonition in list(container.select(".theme-admonition, .admonition, .custom-block, .notecard")):
        if admonition.find_parent("blockquote") is not None:
            continue

        heading = admonition.select_one(
            '[class*="admonitionHeading" i], .admonition-heading, .admonition-title, .custom-block-title'
        )
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
    for anchor in container.find_all("a"):
        for node in list(anchor.descendants):
            if isinstance(node, NavigableString) and ("\n" in node or "\r" in node):
                if node.find_parent("pre") is not None:
                    continue
                node.replace_with(re.sub(r"\s*\r?\n\s*", " ", str(node)))


def _strip_leading_nav_lines(lines: list[str]) -> list[str]:
    # Guard against wiping documents that lack a top-level H1 by dropping preamble only when an H1 appears early.
    first_h1_idx = next((i for i, line in enumerate(lines[:30]) if line.lstrip().startswith("# ")), None)
    if first_h1_idx is None or first_h1_idx == 0:
        return lines

    preamble = [line.strip() for line in lines[:first_h1_idx] if line.strip()]
    is_nav_preamble = all(
        len(line) <= 100
        and (line.startswith(("* ", "- ", "[")) or line.lower() in {"on this page", "table of contents", "contents"})
        for line in preamble
    )
    return lines[first_h1_idx:] if is_nav_preamble else lines


class _DomMarkdownConverter(MarkdownConverter):
    def __init__(self, *, base_url: str = "", **options: Any) -> None:
        super().__init__(**options)
        self._base_url = base_url if base_url.startswith(("http://", "https://")) else ""

    def convert_img(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        raw_src = el.get("src") or el.get("data-src")
        src = raw_src.strip() if isinstance(raw_src, str) else ""
        if not src:
            return ""
        if self._base_url and not src.startswith(("http://", "https://", "data:")):
            src = urljoin(self._base_url, src)

        attrs: list[str] = [f'src="{html_lib.escape(src, quote=True)}"']
        for attr_name in ("alt", "title", "width", "height"):
            raw_val = el.get(attr_name)
            if isinstance(raw_val, str):
                val = raw_val.strip()
                if val or attr_name == "alt":
                    attrs.append(f'{attr_name}="{html_lib.escape(val, quote=True)}"')
        return f"<img {' '.join(attrs)}>"


def _postprocess_markdown(markdown: str, *, strip_leading_nav: bool = False) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "")
    text = _EMPTY_ANCHOR_RE.sub("", text)

    lines = _strip_leading_nav_lines(text.split("\n")) if strip_leading_nav else text.split("\n")
    cleaned_lines = [line.rstrip() for line in lines]
    return _MULTI_NEWLINE_RE.sub("\n\n", "\n".join(cleaned_lines)).strip()


def _extract_with_dom_markdownify(html: str, url: str = "") -> str:
    soup = BeautifulSoup(html, "lxml")
    target = next((el for selector in _MAIN_SELECTORS if (el := soup.select_one(selector)) is not None), soup)
    _strip_unwanted_dom_elements(target)
    _normalize_admonitions(target, soup)
    _normalize_anchor_newlines(target)
    converter = _DomMarkdownConverter(
        base_url=url,
        heading_style="ATX",
        bullets="-",
        code_language_callback=_detect_code_language,
    )
    raw_markdown = converter.convert(str(target))
    return _postprocess_markdown(raw_markdown)


def _extract_with_crawl4ai(html: str, url: str, crawl4ai_markdown: str | None) -> str:
    if crawl4ai_markdown and crawl4ai_markdown.strip():
        return _postprocess_markdown(crawl4ai_markdown, strip_leading_nav=True)

    target_html = html
    if html.strip():
        main_el = BeautifulSoup(html, "lxml").select_one("main")
        if main_el is not None:
            target_html = str(main_el)

    result = DefaultMarkdownGenerator().generate_markdown(input_html=target_html, base_url=url, citations=False)
    return _postprocess_markdown(result.raw_markdown, strip_leading_nav=True)


def extract_markdown(
    html: str,
    url: str = "",
    method: ExtractorType = "dom-markdownify",
    crawl4ai_markdown: str | None = None,
) -> str:
    """Convert HTML into cleaned Markdown using the specified extraction method."""
    if not html.strip() and crawl4ai_markdown is None:
        return ""
    if method == "dom-markdownify":
        return _extract_with_dom_markdownify(html, url=url)
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
        if (
            not stripped
            or stripped.startswith(("#", "-", "*", ">", "|", "![", "<img", "---"))
            or re.match(r"^\d+\.\s+", stripped)
        ):
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(stripped)

    if not paragraph_lines:
        return ""

    joined = _HTML_IMG_TAG_RE.sub("", " ".join(paragraph_lines))
    joined = _MD_LINK_RE.sub(r"\1", joined)
    joined = _MD_FORMAT_RE.sub("", joined)
    return re.sub(r"\s+", " ", joined).strip()


def _truncate_text(text: str, max_length: int = 150) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_length:
        return clean
    return clean[: max_length - 3].rstrip() + "..."


def extract_page_metadata(html: str, markdown: str, fallback_title: str = "") -> PageMetadata:
    """Extract page title and description from HTML metadata and rendered Markdown."""
    soup = BeautifulSoup(html, "lxml") if html.strip() else BeautifulSoup("", "lxml")

    title = _extract_first_h1_from_markdown(markdown)
    if not title and (h1 := soup.find("h1")) is not None:
        for anchor in list(h1.find_all("a")):
            if _HEADING_ANCHOR_TEXT_RE.match(anchor.get_text()):
                anchor.decompose()
        title = re.sub(r"\s+", " ", h1.get_text()).strip()

    if not title:
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title is not None and isinstance(og_title.get("content"), str):
            title = str(og_title["content"]).strip()

    if not title and soup.title is not None:
        raw_title = re.sub(r"\s+", " ", soup.title.get_text()).strip()
        for sep in (" | ", " - ", " — ", " · "):
            if sep in raw_title and (prefix := raw_title.split(sep, 1)[0].strip()):
                raw_title = prefix
                break
        title = raw_title

    if not title:
        title = fallback_title.strip() or "Untitled"

    description = ""
    for meta_selector in ('meta[name="description"]', 'meta[property="og:description"]'):
        meta = soup.select_one(meta_selector)
        if meta is not None and isinstance(meta.get("content"), str) and (candidate := str(meta["content"]).strip()):
            description = _truncate_text(candidate)
            break

    if not description and (first_para := _extract_first_paragraph(markdown)):
        description = _truncate_text(first_para)

    return PageMetadata(title=title, description=description or title)


def extract_sidebar_links(html: str, base_url: str) -> list[str]:
    """Extract ordered, same-host document URLs from sidebar navigation DOM."""
    if not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(base_url).netloc.lower() if base_url else ""

    candidate_links: list[str] = []
    seen: set[str] = set()

    for selector in _SIDEBAR_SELECTORS:
        for container in soup.select(selector):
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
