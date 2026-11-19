from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import takewhile
from typing import Literal, cast
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse

from pydantic import BaseModel

from web2md.markdown_code import iter_lines_with_code_flag, sub_outside_code_spans

FrontmatterField = Literal["title", "description", "source", "timestamp"]
FRONTMATTER_FIELDS: tuple[FrontmatterField, ...] = ("title", "description", "source", "timestamp")
_FRONTMATTER_FIELD_SET = frozenset(FRONTMATTER_FIELDS)

# Includes "/" because a percent-decoded segment ("a%2Fb") must stay a single path component.
_UNSAFE_SEGMENT_RE = re.compile(r'[<>:"|?*\x00-\x1f\\/]')
# Characters that are legal in file names but would end or alter a Markdown link destination.
_LINK_TARGET_UNSAFE_RE = re.compile(r"[\s%#()]")
# The destination may contain one level of balanced parentheses, as in `/wiki/Python_(language)`.
_MD_INLINE_LINK_RE = re.compile(r'(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(((?:[^()\s]|\([^()\s]*\))+)(\s+"[^"]*")?\)')
_HTML_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)("[^>]*>)', re.IGNORECASE)


class CrawledPageDoc(BaseModel):
    """Document metadata and Markdown content for a single crawled output file."""

    url: str
    relpath: str
    title: str
    description: str
    markdown: str


# Matches Crawl4AI's `normalize_url_for_deep_crawl` tracking-parameter list so links resolve to crawled pages.
_TRACKING_QUERY_PARAMS = frozenset({"utm_source", "utm_medium", "utm_campaign", "ref", "fbclid"})
_DEFAULT_PORTS = {"http": ":80", "https": ":443"}


def normalize_url_key(url: str) -> str:
    """Normalize a URL by resolving dot segments, stripping default ports, tracking queries, fragments, and index names."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    default_port = _DEFAULT_PORTS.get(scheme)
    if default_port and netloc.endswith(default_port):
        netloc = netloc[: -len(default_port)]
    # normpath resolves "." / ".." the way browsers do, so "/docs/x/../../etc" can never escape the output root.
    path = posixpath.normpath(re.sub(r"/+", "/", parsed.path or "/"))
    if path.endswith(("/index.html", "/index.htm")):
        path = posixpath.dirname(path)
    query = ""
    if parsed.query:
        kept_params = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key not in _TRACKING_QUERY_PARAMS
        ]
        if kept_params:
            query = f"?{urlencode(sorted(kept_params))}"
    return f"{scheme}://{netloc}{path}{query}"


def _sanitize_segment(segment: str) -> str:
    # Trailing dots and spaces are dropped because Windows silently removes them; this also neutralizes "." and "..".
    return _UNSAFE_SEGMENT_RE.sub("_", segment).strip().rstrip(". ") or "page"


def _strip_doc_extension(name: str) -> str:
    lower = name.lower()
    for ext in (".html", ".htm", ".md"):
        if lower.endswith(ext) and len(name) > len(ext):
            return name[: -len(ext)]
    return name


def _allocate_unique_path(candidate: str, used: set[str]) -> str:
    # `used` holds case-folded paths because Windows and macOS treat `API.md` and `api.md` as the same file.
    stem = candidate.removesuffix(".md")
    unique = candidate
    suffix = 1
    while unique.casefold() in used:
        suffix += 1
        unique = f"{stem}-{suffix}.md"
    used.add(unique.casefold())
    return unique


def compute_relative_paths(urls: Sequence[str], seed_url: str) -> dict[str, str]:
    """Map crawled URLs to collision-free relative `.md` file paths under the output root."""
    if not urls:
        return {}

    unique_keys: list[str] = []
    key_to_originals: dict[str, list[str]] = {}
    for url in urls:
        key = normalize_url_key(url)
        if key not in key_to_originals:
            unique_keys.append(key)
            key_to_originals[key] = []
        key_to_originals[key].append(url)

    parsed_by_key = {key: urlparse(key) for key in unique_keys}
    hosts = {parsed.netloc for parsed in parsed_by_key.values() if parsed.netloc}
    seed_host = urlparse(normalize_url_key(seed_url)).netloc
    multi_host = len(hosts) > 1 or (bool(seed_host) and hosts != {seed_host})

    # Segments are percent-decoded so that non-ASCII pages get readable file names ("はじめに.md").
    segs_by_key = {
        key: [unquote(seg) for seg in parsed_by_key[key].path.strip("/").split("/") if seg] for key in unique_keys
    }

    # URLs that have descendant pages become directory overviews (overview.md) to avoid colliding with generated index.md.
    ancestor_dirs = {
        (parsed_by_key[key].netloc, *segs_by_key[key][:depth])
        for key in unique_keys
        for depth in range(len(segs_by_key[key]))
    }
    dir_parent_keys = {
        key
        for key in unique_keys
        if not segs_by_key[key] or (parsed_by_key[key].netloc, *segs_by_key[key]) in ancestor_dirs
    }

    common_prefix: list[str] = []
    if not multi_host:
        parent_lists = [segs_by_key[k] if k in dir_parent_keys else segs_by_key[k][:-1] for k in unique_keys]
        common_prefix = [col[0] for col in takewhile(lambda col: len(set(col)) == 1, zip(*parent_lists, strict=False))]

    used_paths: set[str] = set()
    result: dict[str, str] = {}

    for key in unique_keys:
        parsed = parsed_by_key[key]
        rel_segs = list(segs_by_key[key][len(common_prefix) :] if not multi_host else segs_by_key[key])

        if multi_host and parsed.netloc:
            rel_segs = [_sanitize_segment(parsed.netloc.replace(":", "_")), *rel_segs]

        if key in dir_parent_keys or not rel_segs:
            dir_parts = [_sanitize_segment(s) for s in rel_segs]
            leaf = "overview"
        else:
            dir_parts = [_sanitize_segment(s) for s in rel_segs[:-1]]
            leaf = _sanitize_segment(_strip_doc_extension(rel_segs[-1]))
            if leaf.lower() == "index":
                leaf = "overview"

        if parsed.query:
            query_hash = hashlib.sha1(parsed.query.encode("utf-8")).hexdigest()[:6]
            leaf = f"{leaf}-{query_hash}"

        relpath = "/".join([*dir_parts, f"{leaf}.md"]) if dir_parts else f"{leaf}.md"
        unique_relpath = _allocate_unique_path(relpath, used_paths)
        for orig_url in key_to_originals[key]:
            result[orig_url] = unique_relpath

    return result


def _link_target(relpath: str) -> str:
    return _LINK_TARGET_UNSAFE_RE.sub(lambda match: quote(match.group()), relpath)


def _without_doc_extension(url_key: str) -> str:
    parsed = urlparse(url_key)
    return parsed._replace(path=_strip_doc_extension(parsed.path)).geturl()


def build_link_lookup(url_to_relpath: Mapping[str, str]) -> dict[str, str]:
    """Index page URLs by normalized key so that `rewrite_markdown_links` can resolve links to local `.md` paths."""
    lookup = {normalize_url_key(url): relpath for url, relpath in url_to_relpath.items()}
    # `/guide.html` and `/guide` usually name the same page; exact keys registered above keep priority.
    for key, relpath in list(lookup.items()):
        lookup.setdefault(_without_doc_extension(key), relpath)
    return lookup


def rewrite_markdown_links(
    markdown: str,
    source_url: str,
    source_relpath: str,
    link_lookup: Mapping[str, str],
) -> str:
    """Rewrite links to crawled pages into relative `.md` paths and other relative links into absolute URLs.

    `link_lookup` comes from `build_link_lookup`; pass an empty mapping to only absolutize relative links.
    """
    source_dir = posixpath.dirname(source_relpath) or "."
    has_http_source = source_url.startswith(("http://", "https://"))

    def replace_match(match: re.Match[str]) -> str:
        bang, text, raw_href, title_suffix = match.groups()
        title_part = title_suffix or ""

        if raw_href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            return match.group(0)

        abs_url = urljoin(source_url, raw_href) if has_http_source else raw_href

        if bang == "!":
            if has_http_source and not raw_href.startswith(("http://", "https://")):
                return f"![{text}]({abs_url}{title_part})"
            return match.group(0)

        if not abs_url.startswith(("http://", "https://")):
            return match.group(0)

        parsed = urlparse(abs_url)
        frag = f"#{parsed.fragment}" if parsed.fragment else ""
        target_key = normalize_url_key(abs_url)
        target_relpath = link_lookup.get(target_key) or link_lookup.get(_without_doc_extension(target_key))

        if target_relpath is not None:
            if target_relpath == source_relpath and frag:
                return f"[{text}]({frag}{title_part})"
            rel = _link_target(posixpath.relpath(target_relpath, start=source_dir))
            return f"[{text}]({rel}{frag}{title_part})"

        if not raw_href.startswith(("http://", "https://")):
            return f"[{text}]({abs_url}{title_part})"
        return match.group(0)

    def replace_html_img_src(match: re.Match[str]) -> str:
        prefix, raw_src, suffix = match.groups()
        if not has_http_source or raw_src.startswith(("http://", "https://", "data:", "#")):
            return match.group(0)
        return f"{prefix}{urljoin(source_url, raw_src)}{suffix}"

    output_lines: list[str] = []
    for line, in_code_block in iter_lines_with_code_flag(markdown):
        if not in_code_block:
            line = sub_outside_code_spans(_MD_INLINE_LINK_RE, replace_match, line)
            line = sub_outside_code_spans(_HTML_IMG_SRC_RE, replace_html_img_src, line)
        output_lines.append(line)

    return "\n".join(output_lines)


def parse_frontmatter_fields(raw: str | Sequence[str] | None) -> list[FrontmatterField]:
    """Validate and deduplicate requested YAML frontmatter fields while preserving order."""
    if raw is None:
        return list(FRONTMATTER_FIELDS)

    items = [part.strip() for part in (raw.split(",") if isinstance(raw, str) else raw) if part.strip()]
    if not items:
        raise ValueError("At least one frontmatter field must be specified.")

    validated: list[FrontmatterField] = []
    seen: set[str] = set()
    for item in items:
        if item not in _FRONTMATTER_FIELD_SET:
            valid = ", ".join(FRONTMATTER_FIELDS)
            raise ValueError(f"Unsupported frontmatter field: {item}. Valid fields: {valid}")
        if item not in seen:
            seen.add(item)
            validated.append(cast(FrontmatterField, item))
    return validated


def format_frontmatter(
    title: str,
    description: str,
    source_url: str = "",
    *,
    timestamp: str | None = None,
    fields: Sequence[FrontmatterField] = FRONTMATTER_FIELDS,
) -> str:
    """Render a YAML frontmatter block with the selected fields, or an empty string when none has a value."""
    resolved_fields = parse_frontmatter_fields(fields)
    ts_value = timestamp if timestamp is not None else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # JSON strings are valid YAML double-quoted scalars, which keeps ":" and "#" in values from being misparsed.
    lines: list[str] = []
    for field in resolved_fields:
        if field == "title":
            lines.append(f"title: {json.dumps(title, ensure_ascii=False)}")
        elif field == "description":
            lines.append(f"description: {json.dumps(description, ensure_ascii=False)}")
        elif field == "source" and source_url:
            lines.append(f"source: {json.dumps(source_url, ensure_ascii=False)}")
        elif field == "timestamp":
            lines.append(f"timestamp: {ts_value}")
    return "\n".join(["---", *lines, "---"]) if lines else ""


def _link_label(title: str) -> str:
    # Unescaped brackets or line breaks in a title would break the surrounding `[label](target)` syntax.
    return re.sub(r"([\[\]])", r"\\\1", " ".join(title.split()))


def _humanize_dir_name(dir_path: str) -> str:
    name = posixpath.basename(dir_path)
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", name) if part) or name


def generate_toc_files(
    pages: Sequence[CrawledPageDoc],
    nav_order: Sequence[str] = (),
    root_title: str = "Documentation Index",
) -> dict[str, str]:
    """Generate hierarchical `index.md` table-of-contents files ordered by sidebar navigation."""
    nav_rank: dict[str, int] = {}
    for idx, nav_url in enumerate(nav_order):
        nav_rank.setdefault(normalize_url_key(nav_url), idx)

    all_dirs: set[str] = {""}
    pages_by_dir: dict[str, list[CrawledPageDoc]] = {"": []}
    overview_by_dir: dict[str, CrawledPageDoc] = {}

    for page in pages:
        rel_dir = posixpath.dirname(page.relpath)
        all_dirs.add(rel_dir)
        pages_by_dir.setdefault(rel_dir, []).append(page)
        if posixpath.basename(page.relpath) == "overview.md":
            overview_by_dir[rel_dir] = page

        parent = rel_dir
        while parent:
            parent = posixpath.dirname(parent)
            all_dirs.add(parent)
            pages_by_dir.setdefault(parent, [])

    def page_sort_key(page: CrawledPageDoc) -> tuple[int, str]:
        return (nav_rank.get(normalize_url_key(page.url), sys.maxsize), page.relpath)

    def dir_rank(dir_path: str) -> tuple[int, str]:
        prefix = f"{dir_path}/" if dir_path else ""
        ranks = [nav_rank.get(normalize_url_key(p.url), sys.maxsize) for p in pages if p.relpath.startswith(prefix)]
        return (min(ranks, default=sys.maxsize), dir_path)

    toc_files: dict[str, str] = {}

    for current_dir in sorted(all_dirs):
        child_dirs = sorted((d for d in all_dirs if d and posixpath.dirname(d) == current_dir), key=dir_rank)
        direct_pages = sorted(pages_by_dir.get(current_dir, []), key=page_sort_key)
        dir_overview = overview_by_dir.get(current_dir)

        if current_dir == "":
            dir_title = root_title
        elif dir_overview is not None:
            dir_title = dir_overview.title
        else:
            dir_title = _humanize_dir_name(current_dir)

        lines: list[str] = [f"# {dir_title}", ""]

        if dir_overview is not None and dir_overview.description != dir_title:
            lines.extend([dir_overview.description, ""])

        if child_dirs:
            lines.extend(["## Subcategories", ""])
            for sub_dir in child_dirs:
                sub_name = posixpath.basename(sub_dir)
                sub_overview = overview_by_dir.get(sub_dir)
                sub_title = sub_overview.title if sub_overview is not None else _humanize_dir_name(sub_dir)
                sub_desc = (
                    f" - {sub_overview.description}"
                    if sub_overview is not None and sub_overview.description != sub_title
                    else ""
                )
                lines.append(f"- [{_link_label(sub_title)}]({_link_target(sub_name)}/index.md){sub_desc}")
            lines.append("")

        if direct_pages:
            lines.extend(["## Documents" if child_dirs else "## Index", ""])
            for page in direct_pages:
                filename = posixpath.basename(page.relpath)
                desc_part = f" - {page.description}" if page.description and page.description != page.title else ""
                lines.append(f"- [{_link_label(page.title)}]({_link_target(filename)}){desc_part}")
            lines.append("")

        toc_relpath = f"{current_dir}/index.md" if current_dir else "index.md"
        toc_files[toc_relpath] = "\n".join(lines).rstrip() + "\n"

    return toc_files
