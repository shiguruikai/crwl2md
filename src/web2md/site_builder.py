"""クロール済みページ群のファイル配置・相対リンク解決・目次生成モジュール。"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sys
from collections.abc import Mapping, Sequence
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel

_UNSAFE_SEGMENT_RE = re.compile(r'[<>:"|?*\x00-\x1f\\]')
_MD_INLINE_LINK_RE = re.compile(r'(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)(\s+"[^"]*")?\)')


class CrawledPageDoc(BaseModel):
    """出力サイトを構成する1ページ分のドキュメント情報。"""

    url: str
    relpath: str
    title: str
    description: str
    markdown: str


def normalize_url_key(url: str) -> str:
    """フラグメントを除き末尾スラッシュ・既定ファイル名を正規化した URL キーを返す。"""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path.endswith(("/index.html", "/index.htm")):
        path = path.rsplit("/", 1)[0] + "/"
    path = path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def _path_segments(url: str) -> list[str]:
    parsed = urlparse(normalize_url_key(url))
    return [seg for seg in parsed.path.strip("/").split("/") if seg]


def _sanitize_segment(segment: str) -> str:
    cleaned = _UNSAFE_SEGMENT_RE.sub("_", segment).strip()
    return cleaned or "page"


def _strip_doc_extension(name: str) -> str:
    lower = name.lower()
    for ext in (".html", ".htm", ".md"):
        if lower.endswith(ext) and len(name) > len(ext):
            return name[: -len(ext)]
    return name


def _longest_common_prefix(paths: Sequence[list[str]]) -> list[str]:
    if not paths:
        return []
    prefix = list(paths[0])
    for path in paths[1:]:
        limit = min(len(prefix), len(path))
        idx = 0
        while idx < limit and prefix[idx] == path[idx]:
            idx += 1
        prefix = prefix[:idx]
        if not prefix:
            break
    return prefix


def _allocate_unique_path(candidate: str, used: set[str]) -> str:
    if candidate not in used:
        used.add(candidate)
        return candidate
    stem = candidate[:-3] if candidate.endswith(".md") else candidate
    suffix = 2
    while f"{stem}-{suffix}.md" in used:
        suffix += 1
    unique = f"{stem}-{suffix}.md"
    used.add(unique)
    return unique


def compute_relative_paths(urls: Sequence[str], seed_url: str) -> dict[str, str]:
    """クロール済み URL 群を出力先ディレクトリ内の相対パス（`.md`）へマッピングする。"""
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

    segs_by_key = {key: _path_segments(key) for key in unique_keys}

    # クエリなしのパスが他のページの祖先になっている場合はディレクトリルートとみなす。
    dir_parent_keys: set[str] = set()
    for key in unique_keys:
        segs = segs_by_key[key]
        if not segs:
            dir_parent_keys.add(key)
            continue
        for other_key in unique_keys:
            if other_key == key:
                continue
            other_segs = segs_by_key[other_key]
            if (
                parsed_by_key[key].netloc == parsed_by_key[other_key].netloc
                and len(other_segs) > len(segs)
                and other_segs[: len(segs)] == segs
            ):
                dir_parent_keys.add(key)
                break

    common_prefix: list[str] = []
    if not multi_host:
        parent_lists = [segs_by_key[k] if k in dir_parent_keys else segs_by_key[k][:-1] for k in unique_keys]
        common_prefix = _longest_common_prefix(parent_lists)

    used_paths: set[str] = set()
    result: dict[str, str] = {}

    for key in unique_keys:
        parsed = parsed_by_key[key]
        segs = segs_by_key[key]
        rel_segs = list(segs[len(common_prefix) :] if not multi_host else segs)

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


def _build_lookup_map(url_to_relpath: Mapping[str, str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for url, relpath in url_to_relpath.items():
        key = normalize_url_key(url)
        lookup[key] = relpath
        parsed = urlparse(key)
        stripped_path = _strip_doc_extension(parsed.path)
        if stripped_path != parsed.path:
            alt_key = parsed._replace(path=stripped_path).geturl()
            lookup.setdefault(alt_key, relpath)
    return lookup


def rewrite_markdown_links(
    markdown: str,
    source_url: str,
    source_relpath: str,
    url_to_relpath: Mapping[str, str],
) -> str:
    """Markdown 内のリンクを出力先ファイル間の相対パス（対象外は絶対 URL）へ変換する。"""
    lookup = _build_lookup_map(url_to_relpath)
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
        target_relpath = lookup.get(target_key)

        if target_relpath is not None:
            if target_relpath == source_relpath and frag:
                return f"[{text}]({frag}{title_part})"
            rel = posixpath.relpath(target_relpath, start=source_dir)
            return f"[{text}]({rel}{frag}{title_part})"

        if not raw_href.startswith(("http://", "https://")):
            return f"[{text}]({abs_url}{title_part})"
        return match.group(0)

    output_lines: list[str] = []
    in_code_block = False
    for line in markdown.splitlines():
        if line.strip().startswith(("```", "~~~")):
            in_code_block = not in_code_block
            output_lines.append(line)
            continue
        if in_code_block:
            output_lines.append(line)
        else:
            output_lines.append(_MD_INLINE_LINK_RE.sub(replace_match, line))

    return "\n".join(output_lines)


def format_frontmatter(title: str, description: str, source_url: str) -> str:
    """ドキュメント先頭に付与する YAML フロントマッターを生成する。"""
    safe_title = json.dumps(title, ensure_ascii=False)
    safe_desc = json.dumps(description, ensure_ascii=False)
    lines = [
        "---",
        f"title: {safe_title}",
        f"description: {safe_desc}",
    ]
    if source_url:
        lines.append(f"source: {source_url}")
    lines.append("---")
    return "\n".join(lines)


def _humanize_dir_name(dir_path: str) -> str:
    name = posixpath.basename(dir_path)
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", name) if part) or name


def generate_toc_files(
    pages: Sequence[CrawledPageDoc],
    nav_order: Sequence[str] = (),
    root_title: str = "Documentation Index",
) -> dict[str, str]:
    """ルートおよび各サブディレクトリ用の目次ファイル（`index.md`）を生成する。"""
    nav_rank: dict[str, int] = {}
    for idx, nav_url in enumerate(nav_order):
        key = normalize_url_key(nav_url)
        if key not in nav_rank:
            nav_rank[key] = idx

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
        child_dirs = [d for d in all_dirs if d and posixpath.dirname(d) == current_dir]
        child_dirs.sort(key=dir_rank)

        direct_pages = sorted(pages_by_dir.get(current_dir, []), key=page_sort_key)

        if current_dir == "":
            dir_title = root_title
        elif current_dir in overview_by_dir:
            dir_title = overview_by_dir[current_dir].title
        else:
            dir_title = _humanize_dir_name(current_dir)

        lines: list[str] = [f"# {dir_title}", ""]

        if current_dir in overview_by_dir and overview_by_dir[current_dir].description != dir_title:
            lines.extend([overview_by_dir[current_dir].description, ""])

        if child_dirs:
            lines.extend(["## Subcategories", ""])
            for sub_dir in child_dirs:
                sub_name = posixpath.basename(sub_dir)
                sub_title = (
                    overview_by_dir[sub_dir].title if sub_dir in overview_by_dir else _humanize_dir_name(sub_dir)
                )
                sub_desc = (
                    f" - {overview_by_dir[sub_dir].description}"
                    if sub_dir in overview_by_dir and overview_by_dir[sub_dir].description != sub_title
                    else ""
                )
                lines.append(f"- [{sub_title}]({sub_name}/index.md){sub_desc}")
            lines.append("")

        if direct_pages:
            section_heading = "## Documents" if child_dirs else "## Index"
            lines.extend([section_heading, ""])
            for page in direct_pages:
                filename = posixpath.basename(page.relpath)
                desc_part = f" - {page.description}" if page.description and page.description != page.title else ""
                lines.append(f"- [{page.title}]({filename}){desc_part}")
            lines.append("")

        toc_relpath = f"{current_dir}/index.md" if current_dir else "index.md"
        toc_files[toc_relpath] = "\n".join(lines).rstrip() + "\n"

    return toc_files
