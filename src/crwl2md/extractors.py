from __future__ import annotations

import html as html_lib
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from bs4.element import Comment, NavigableString, PageElement
from markdownify import MarkdownConverter
from pydantic import BaseModel

from crwl2md.markdown_code import iter_lines_with_code_flag

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
#   Inactive tab panels are also `hidden` but hold real content, so they are kept and labeled by `_label_tab_panels`.
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
    '[hidden]:not([role="tabpanel"])',
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

# Matches Prism/Shiki/Highlight.js `language-*`, GitHub `highlight-source-*`, and Sphinx `highlight-*` class names.
_CODE_LANG_CLASS_RE = re.compile(r"^(?:language|highlight-source|highlight)-([a-zA-Z0-9_+-]+)$")
# `lang-*` doubles as a UI-locale class on page wrappers (`lang-ja`), so it is honored only on <pre>/<code> themselves.
_CODE_LANG_SHORT_CLASS_RE = re.compile(r"^lang-([a-zA-Z0-9_+-]+)$")
# Sphinx emits `highlight-default` / `highlight-none`, and Highlight.js emits `language-undefined`, when no language is set.
_NON_LANGUAGE_NAMES = frozenset({"default", "none", "null", "plain", "plaintext", "text", "txt", "undefined"})
# Matches empty or symbol-only heading permalink anchors (\u200b in Docusaurus/VitePress, #/¶ in Zensical, \uf0c1 in MkDocs).
_HEADING_ANCHOR_TEXT_RE = re.compile(r"^[\u200b#\u00b6\uf0c1\s]*$")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SUB_SUP_TAG_RE = re.compile(r"</?(?:sub|sup)>", re.IGNORECASE)
# Strips unescaped inline formatting tokens and word-boundary `_` emphasis while preserving `snake_case` identifiers.
_MD_FORMAT_RE = re.compile(r"(?<!\\)[*`~]|(?<![\\\w])_|(?<!\\)_(?!\w)")
# Matches the backslash escapes markdownify adds in front of literal punctuation.
_MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!<>|~])")
_ATX_HEADING_RE = re.compile(r"^#{1,6}(?:\s|$)")
_THEMATIC_BREAK_RE = re.compile(r"^(?:[-*_]\s*){3,}$")
_ORDERED_LIST_ITEM_RE = re.compile(r"^\d+[.)]\s")
_BACKTICK_FENCE_RUN_RE = re.compile(r"`{3,}")
_BACKTICK_RUN_RE = re.compile(r"`+")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
# Blank lines before the first code line of a <pre>; the first line's own indentation is kept.
_PRE_LEADING_BLANK_RE = re.compile(r"^[ \n]*\n")
_HEADING_TAGS: tuple[str, ...] = ("h1", "h2", "h3", "h4", "h5", "h6")
_CODE_LINE_WRAPPER_TAGS = frozenset({"div", "p", "li"})
_ACTIVE_NAV_CLASS_RE = re.compile(r"(?:^|[\s_-])(?:active|current)(?:$|[\s_-])", re.IGNORECASE)


class PageMetadata(BaseModel):
    """Extracted title and short description for a document page."""

    title: str
    description: str


def _extract_lang_from_attrs(tag: Tag | None, *, is_code_element: bool) -> str:
    if tag is None:
        return ""
    for attr in ("data-language", "data-lang"):
        val = tag.get(attr)
        if isinstance(val, str) and (cleaned := val.strip()) and cleaned.lower() not in _NON_LANGUAGE_NAMES:
            return cleaned
    classes = tag.get("class")
    if isinstance(classes, list):
        str_classes = [cls for cls in classes if isinstance(cls, str)]
        # When Highlight.js runs in the browser on an unlabeled `<code>`, it sets `data-highlighted="yes"` and
        # appends `hljs` followed by a guessed `language-<auto>` class. An explicit language class already on
        # `<code>` appears before `hljs`; one placed on `<pre>` or a wrapper is picked up from that ancestor.
        if is_code_element and tag.get("data-highlighted") == "yes" and str_classes and str_classes[0] == "hljs":
            return ""
        for i, cls in enumerate(str_classes):
            match = _CODE_LANG_CLASS_RE.match(cls) or (
                _CODE_LANG_SHORT_CLASS_RE.match(cls) if is_code_element else None
            )
            if match and match.group(1).lower() not in _NON_LANGUAGE_NAMES:
                return match.group(1)
            # MDN SyntaxHighlighter emits `class="brush: js notranslate"`, tokenized as ["brush:", "js", ...].
            if cls == "brush:" and i + 1 < len(str_classes):
                next_cls = str_classes[i + 1].strip(";")
                if next_cls and next_cls != "notranslate" and next_cls.lower() not in _NON_LANGUAGE_NAMES:
                    return next_cls
    return ""


def _detect_code_language(el: Tag) -> str:
    # Docusaurus and Shiki often place the language-* class on an outer wrapper up to 3 levels above <pre>.
    code = el.find("code")
    for code_element in (code if isinstance(code, Tag) else None, el):
        if lang := _extract_lang_from_attrs(code_element, is_code_element=True):
            return lang
    parent = el.parent
    for _ in range(3):
        if not isinstance(parent, Tag):
            break
        if lang := _extract_lang_from_attrs(parent, is_code_element=False):
            return lang
        parent = parent.parent
    return ""


def _new_bold_paragraph(soup: BeautifulSoup, text: str) -> Tag:
    paragraph = soup.new_tag("p")
    strong = soup.new_tag("strong")
    strong.string = text
    paragraph.append(strong)
    return paragraph


def _label_tab_panels(container: Tag, soup: BeautifulSoup) -> None:
    # ARIA tab widgets (Docusaurus <Tabs>, Starlight <Tabs>) render every panel but hide the inactive ones.
    # Keep all panels and move each tab label in front of its panel so the variants stay distinguishable.
    for tablist in list(container.select('[role="tablist"]')):
        tabs = tablist.select('[role="tab"]')
        widget = next(
            (parent for parent in tablist.parents if parent.select_one('[role="tabpanel"]') is not None), None
        )
        panels = widget.select('[role="tabpanel"]') if widget is not None else []
        # Nested or lazily rendered widgets do not pair up one-to-one; leave those untouched.
        if not tabs or len(tabs) != len(panels):
            continue
        for tab, panel in zip(tabs, panels, strict=True):
            panel.insert(0, _new_bold_paragraph(soup, re.sub(r"\s+", " ", tab.get_text()).strip()))
        tablist.decompose()


def _strip_unwanted_dom_elements(container: Tag) -> None:
    # Headers are judged before <nav> removal so that navigation banners are still recognizable.
    for header in list(container.find_all("header")):
        # Preserve title headers (<header><h1>...</h1></header>, <section><header><h2>...) while dropping banners.
        if header.get("role") == "banner" or header.find("nav") is not None or header.find(_HEADING_TAGS) is None:
            header.decompose()

    for el in container.find_all(list(_UNWANTED_TAGS)):
        el.decompose()

    for el in container.select(", ".join(_UNWANTED_SELECTORS)):
        el.decompose()

    for heading in container.find_all(_HEADING_TAGS):
        for anchor in list(heading.find_all("a")):
            if _HEADING_ANCHOR_TEXT_RE.match(anchor.get_text()):
                anchor.decompose()
            elif str(anchor.get("href") or "").startswith("#"):
                # MDN wraps heading text in `<a class="heading-anchor" href="#...">Title</a>`; unwrap self-links.
                anchor.unwrap()

    # Icon-only anchors lose their content above and would otherwise render as empty `[](...)` links.
    for anchor in list(container.find_all("a")):
        if (
            anchor.find_parent("pre") is None
            and anchor.find("img") is None
            and not anchor.get_text().strip("\u200b \t\r\n")
        ):
            anchor.decompose()


def _normalize_admonitions(container: Tag, soup: BeautifulSoup) -> None:
    # Covers Docusaurus, MkDocs / Sphinx, VitePress, MDN, and Starlight (which marks callouts up as <aside>).
    for admonition in list(
        container.select(".theme-admonition, .admonition, .custom-block, .notecard, .starlight-aside")
    ):
        if admonition.find_parent("blockquote") is not None:
            continue

        heading = admonition.select_one(
            '[class*="admonitionHeading" i], .admonition-heading, .admonition-title, .custom-block-title, '
            ".starlight-aside__title"
        )
        if heading is not None:
            heading_text = re.sub(r"\s+", " ", heading.get_text()).strip()
            if heading_text:
                heading.replace_with(_new_bold_paragraph(soup, heading_text))
            else:
                heading.decompose()

        for content in list(
            admonition.select('[class*="admonitionContent" i], .admonition-content, .starlight-aside__content')
        ):
            content.unwrap()

        admonition.name = "blockquote"


def _normalize_anchor_newlines(container: Tag) -> None:
    for anchor in container.find_all("a"):
        for node in list(anchor.descendants):
            if isinstance(node, NavigableString) and ("\n" in node or "\r" in node):
                if node.find_parent("pre") is not None:
                    continue
                node.replace_with(re.sub(r"\s*\r?\n\s*", " ", str(node)))


def _pick_image_src(el: Tag) -> str:
    srcset = el.get("srcset") or el.get("data-srcset")
    first_srcset_url = srcset.split(",")[0].split()[0] if isinstance(srcset, str) and srcset.strip() else None
    candidates = [
        value.strip()
        for value in (el.get("src"), el.get("data-src"), el.get("data-lazy-src"), first_srcset_url)
        if isinstance(value, str) and value.strip()
    ]
    # Lazy-loading scripts park a `data:` placeholder in `src` and keep the real URL in another attribute.
    return next((src for src in candidates if not src.startswith("data:")), candidates[0] if candidates else "")


def _code_text(node: PageElement) -> str:
    # Rebuild <pre> text the way a browser lays it out: <br> and block-level line wrappers
    # (Docusaurus `div.token-line`, Expressive Code `div.ec-line`) each end a line exactly once.
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name == "br":
        return "\n"
    text = "".join(_code_text(child) for child in node.children)
    if node.name in _CODE_LINE_WRAPPER_TAGS and text and not text.endswith("\n"):
        text += "\n"
    return text


def _inline_code(text: str) -> str:
    longest = max((len(match.group(0)) for match in _BACKTICK_RUN_RE.finditer(text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


class _DomMarkdownConverter(MarkdownConverter):
    def __init__(self, *, base_url: str = "", **options: Any) -> None:
        super().__init__(**options)
        self._base_url = base_url if base_url.startswith(("http://", "https://")) else ""

    def convert_pre(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        code = _PRE_LEADING_BLANK_RE.sub("", _code_text(el)).rstrip(" \n")
        if not code:
            return ""
        if "td" in parent_tags or "th" in parent_tags:
            # Fenced code blocks break Markdown table rows, so render lines as inline code separated by <br>.
            return "<br>".join(_inline_code(line) if line else "" for line in code.split("\n"))
        # Code that itself contains ``` needs a longer fence, otherwise the block would end early.
        longest_run = max((len(run) for run in _BACKTICK_FENCE_RUN_RE.findall(code)), default=2)
        fence = "`" * (longest_run + 1)
        return f"\n\n{fence}{_detect_code_language(el)}\n{code}\n{fence}\n\n"

    def _convert_table_cell(self, el: Tag, text: str) -> str:
        colspan = 1
        raw_colspan = el.get("colspan")
        if isinstance(raw_colspan, str) and raw_colspan.isdigit():
            colspan = max(1, min(1000, int(raw_colspan)))
        cell_text = _UNESCAPED_PIPE_RE.sub(r"\|", text.strip().replace("\n", " "))
        return f" {cell_text}" + " |" * colspan

    def convert_td(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        return self._convert_table_cell(el, text)

    def convert_th(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        return self._convert_table_cell(el, text)

    def convert_img(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        src = _pick_image_src(el)
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


def _postprocess_markdown(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "")

    # Whitespace cleanup applies to prose only; code blocks must come through unchanged.
    lines: list[str] = []
    for line, in_code_block in iter_lines_with_code_flag(text):
        if not in_code_block:
            line = line.rstrip()
            if not line and lines and not lines[-1]:
                continue
        lines.append(line)
    return "\n".join(lines).strip()


def _resolve_base_url(soup: BeautifulSoup, page_url: str) -> str:
    # HTML honors the first <base> element that carries an href attribute.
    base_tag = soup.find("base", href=True)
    if isinstance(base_tag, Tag):
        raw_href = base_tag.get("href")
        if isinstance(raw_href, str) and (href := raw_href.strip()):
            resolved = urljoin(page_url, href) if page_url else href
            if resolved.startswith(("http://", "https://")):
                return resolved
    return page_url


def extract_base_url(html: str, page_url: str = "") -> str:
    """Return the effective base URL for resolving relative links, honoring HTML `<base href>`."""
    if not html.strip():
        return page_url
    return _resolve_base_url(BeautifulSoup(html, "lxml"), page_url)


def _select_main_container(soup: BeautifulSoup) -> Tag:
    for selector in _MAIN_SELECTORS:
        if selector == "article":
            top_articles = [el for el in soup.select("article") if el.find_parent("article") is None]
            if len(top_articles) == 1:
                return top_articles[0]
            continue
        if (el := soup.select_one(selector)) is not None:
            return el
    return soup


def extract_markdown(html: str, url: str = "") -> str:
    """Convert the main content of an HTML page into cleaned Markdown, resolving image URLs against `url`."""
    if not html.strip():
        return ""

    soup = BeautifulSoup(html, "lxml")
    effective_url = _resolve_base_url(soup, url)
    target = _select_main_container(soup)
    # Tab labels and <aside> callouts must be rewritten before the generic <button>/<aside> removal.
    _label_tab_panels(target, soup)
    _normalize_admonitions(target, soup)
    _strip_unwanted_dom_elements(target)
    _normalize_anchor_newlines(target)
    converter = _DomMarkdownConverter(
        base_url=effective_url,
        heading_style="ATX",
        bullets="-",
        # Trailing-space line breaks would be lost to whitespace cleanup, so <br> becomes a backslash break.
        newline_style="BACKSLASH",
        # Disable <href> shortcut links so relative URLs are not misparsed as HTML tags and remain rewritable.
        autolinks=False,
        sub_symbol="<sub>",
        sup_symbol="<sup>",
    )
    return _postprocess_markdown(converter.convert(str(target)))


def _to_plain_text(inline_markdown: str) -> str:
    text = _HTML_IMG_TAG_RE.sub("", inline_markdown)
    text = _SUB_SUP_TAG_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_FORMAT_RE.sub("", text)
    text = _MD_ESCAPE_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_first_h1_from_markdown(markdown: str) -> str:
    for line, in_code_block in iter_lines_with_code_flag(markdown):
        stripped = line.strip()
        if not in_code_block and stripped.startswith("# "):
            return _to_plain_text(stripped[2:])
    return ""


def _is_paragraph_line(stripped: str) -> bool:
    return not (
        not stripped
        or stripped.startswith(("- ", "* ", "+ ", ">", "|", "![", "<img"))
        or _ATX_HEADING_RE.match(stripped)
        or _THEMATIC_BREAK_RE.match(stripped)
        or _ORDERED_LIST_ITEM_RE.match(stripped)
    )


def _extract_first_paragraph(markdown: str) -> str:
    paragraph_lines: list[str] = []
    for line, in_code_block in iter_lines_with_code_flag(markdown):
        stripped = line.strip()
        if not in_code_block and _is_paragraph_line(stripped):
            paragraph_lines.append(stripped)
        elif paragraph_lines:
            break
    return _to_plain_text(" ".join(paragraph_lines))


def _truncate_text(text: str, max_length: int = 150) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_length:
        return clean
    return clean[: max_length - 3].rstrip() + "..."


def extract_first_paragraph_description(markdown: str) -> str:
    """Extract and truncate the first prose paragraph of `markdown` for use as a page description."""
    if first_para := _extract_first_paragraph(markdown):
        return _truncate_text(first_para)
    return ""


def extract_page_metadata(html: str, markdown: str, fallback_title: str = "") -> PageMetadata:
    """Extract page title and description from HTML metadata and rendered Markdown."""
    soup = BeautifulSoup(html, "lxml") if html.strip() else BeautifulSoup("", "lxml")

    title = _extract_first_h1_from_markdown(markdown)
    # Look for <h1> in the content area only; a site-name <h1> in the page header would title every page alike.
    if not title and (h1 := _select_main_container(soup).find("h1")) is not None:
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

    if not description:
        description = extract_first_paragraph_description(markdown)

    return PageMetadata(title=title, description=description or title)


def _tag_classes_str(tag: Tag) -> str:
    raw_classes = tag.get("class")
    if isinstance(raw_classes, list):
        return " ".join(str(c) for c in raw_classes)
    return str(raw_classes or "")


def _is_active_leaf_nav_item(li: Tag) -> bool:
    if li.find(["ul", "ol"]) is not None or li.find("a", href=True) is not None:
        return False
    for node in (li, *li.find_all(True)):
        if str(node.get("aria-current") or "").lower() == "page":
            return True
        if _ACTIVE_NAV_CLASS_RE.search(_tag_classes_str(node)):
            return True
    return False


def extract_sidebar_links(html: str, base_url: str) -> list[str]:
    """Extract ordered, same-host document URLs from sidebar navigation DOM."""
    if not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    effective_base = _resolve_base_url(soup, base_url)
    base_host = urlparse(base_url).netloc.lower() if base_url else ""
    clean_base_url = (
        urlparse(base_url)._replace(fragment="").geturl() if base_url.startswith(("http://", "https://")) else ""
    )

    candidate_links: list[str] = []
    seen: set[str] = set()

    for selector in _SIDEBAR_SELECTORS:
        for container in soup.select(selector):
            aria_label = str(container.get("aria-label") or "").lower()
            classes = _tag_classes_str(container).lower()
            if "breadcrumb" in aria_label or "pagination" in classes or "table-of-contents" in classes:
                continue

            for node in container.find_all(["a", "li"]):
                if node.name == "li":
                    # Themes such as mkdocs-terminal render the active page in the sidebar as `<span class="...--active">`
                    # without an `<a>` tag; record `base_url` at that slot so it keeps its sidebar position in `index.md`.
                    if clean_base_url and clean_base_url not in seen and _is_active_leaf_nav_item(node):
                        seen.add(clean_base_url)
                        candidate_links.append(clean_base_url)
                    continue
                if not node.has_attr("href"):
                    continue
                href = str(node["href"]).strip()
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                abs_url = urljoin(effective_base, href) if effective_base else href
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
