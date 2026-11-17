"""Web ページの取得、単一ページ変換、およびサイトクロール処理モジュール。"""

from __future__ import annotations

import asyncio
import posixpath
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, overload
from urllib.parse import unquote, urlparse

import httpx
from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CrawlResult,
    DomainFilter,
    FilterChain,
    URLPatternFilter,
)
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from pydantic import BaseModel, Field

from web2md.extractors import (
    ExtractorType,
    extract_markdown,
    extract_page_metadata,
    extract_sidebar_links,
)
from web2md.site_builder import (
    FRONTMATTER_FIELDS,
    CrawledPageDoc,
    FrontmatterField,
    compute_relative_paths,
    format_frontmatter,
    generate_toc_files,
    normalize_url_key,
    parse_frontmatter_fields,
    rewrite_markdown_links,
)

_NON_HTML_ASSET_RE = re.compile(
    r"\.(?:js|mjs|css|png|jpe?g|gif|svg|webp|ico|pdf|zip|tar|gz|woff2?|ttf|eot|mp4|mp3|json|xml)(\?.*)?$",
    re.IGNORECASE,
)


class CrawlConfig(BaseModel):
    """サイトクロール実行時の設定。"""

    url: str
    output_dir: Path
    max_depth: int = Field(default=2, ge=0)
    max_pages: int = Field(default=100, ge=1)
    method: ExtractorType = "dom-markdownify"
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    allow_all_paths: bool = False
    frontmatter: bool = False
    frontmatter_fields: list[FrontmatterField] | None = None
    verbose: bool = False


class CrawlSummary(BaseModel):
    """サイトクロールの実行結果サマリー。"""

    seed_url: str
    output_dir: Path
    page_count: int
    toc_count: int
    failed_urls: list[str]
    files: list[str]


def _resolve_local_path(source: str) -> Path:
    if source.startswith("file://"):
        parsed = urlparse(source)
        raw_path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", raw_path):
            raw_path = raw_path[1:]
        return Path(raw_path)
    return Path(source)


async def _fetch_single_with_crawl4ai(url: str) -> tuple[str, str, str | None]:
    run_config = CrawlerRunConfig(scraping_strategy=LXMLWebScrapingStrategy(), verbose=False)
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as crawler:
        raw_result: Any = await crawler.arun(url, config=run_config)
        results = _flatten_crawl_results(raw_result)
        if not results or not results[0].success:
            err = results[0].error_message if results else "Unknown error"
            raise RuntimeError(f"Failed to crawl {url}: {err}")
        first = results[0]
        final_url = first.redirected_url or first.url
        raw_md = str(first.markdown) if first.markdown is not None else None
        return first.html, final_url, raw_md


def fetch_html(url: str, timeout: float = 30.0) -> tuple[str, str]:
    """HTTP(S) で単一ページの HTML と最終 URL を取得する。"""
    response = httpx.get(url, follow_redirects=True, timeout=timeout)
    response.raise_for_status()
    return response.text, str(response.url)


def _resolve_frontmatter_fields(
    frontmatter: bool,
    frontmatter_fields: Sequence[FrontmatterField] | str | None,
) -> list[FrontmatterField] | None:
    if frontmatter_fields is not None:
        return parse_frontmatter_fields(frontmatter_fields)
    if frontmatter:
        return list(FRONTMATTER_FIELDS)
    return None


def convert_single(
    source: str,
    method: ExtractorType = "dom-markdownify",
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
) -> str:
    """単一の URL またはローカル HTML ファイルを Markdown 文字列へ変換する。"""
    resolved_fields = _resolve_frontmatter_fields(frontmatter, frontmatter_fields)

    crawl4ai_markdown: str | None = None
    if source.startswith(("http://", "https://")):
        if method == "crawl4ai":
            html, final_url, crawl4ai_markdown = asyncio.run(_fetch_single_with_crawl4ai(source))
        else:
            html, final_url = fetch_html(source)
    else:
        local_path = _resolve_local_path(source)
        if not local_path.is_file():
            raise FileNotFoundError(f"HTML file not found: {source}")
        html = local_path.read_text(encoding="utf-8")
        final_url = ""

    md = extract_markdown(html, url=final_url, method=method, crawl4ai_markdown=crawl4ai_markdown)
    if resolved_fields is not None:
        meta = extract_page_metadata(html, md)
        fm = format_frontmatter(meta.title, meta.description, final_url, fields=resolved_fields)
        md = f"{fm}\n\n{md}" if md else fm

    return md.rstrip() + "\n" if md else ""


def _glob_to_regex(pattern: str, *, leading_star_any: bool = False) -> str:
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append(".*" if (i == 0 and leading_star_any) else "[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return "".join(parts)


def compile_url_pattern(pattern: str | re.Pattern[str]) -> re.Pattern[str]:
    """Glob（`*` / `**`）または正規表現文字列を `re.Pattern` へ変換する。"""
    if isinstance(pattern, re.Pattern):
        return pattern

    raw = pattern.strip()
    if raw.startswith("^") or raw.endswith("$"):
        return re.compile(raw)

    if raw.endswith("/**"):
        base = raw[:-3]
        if "://" in base:
            return re.compile(rf"^{_glob_to_regex(base)}(?:/.*|\?.*)?$")
        if base.startswith("/"):
            return re.compile(rf"^https?://[^/]+{_glob_to_regex(base)}(?:/.*|\?.*)?$")
        return re.compile(rf"^{_glob_to_regex(base, leading_star_any=True)}(?:/.*|\?.*)?$")

    if "://" in raw:
        return re.compile(rf"^{_glob_to_regex(raw)}$")
    if raw.startswith("/"):
        return re.compile(rf"^https?://[^/]+{_glob_to_regex(raw)}$")
    if "*" in raw or "?" in raw:
        return re.compile(rf"^{_glob_to_regex(raw, leading_star_any=True)}$")
    return re.compile(re.escape(raw))


def _build_path_scope_regex(seed_url: str) -> re.Pattern[str] | None:
    parsed = urlparse(seed_url)
    path = parsed.path or "/"
    dir_path = posixpath.dirname(path) if not path.endswith("/") else path.rstrip("/")
    if not dir_path or dir_path == "/":
        return None
    escaped_host = re.escape(parsed.netloc)
    escaped_prefix = re.escape(dir_path.rstrip("/"))
    return re.compile(rf"^https?://{escaped_host}{escaped_prefix}(?:/.*)?$")


def build_filter_chain(config: CrawlConfig) -> FilterChain:
    """クロール設定から Crawl4AI 用の URL フィルターチェーンを構築する。"""
    parsed = urlparse(config.url)
    filters: list[Any] = []

    allowed_domains: list[str] = []
    if parsed.netloc:
        allowed_domains.append(parsed.netloc)
    for pat in config.include_patterns:
        if "://" in pat:
            pat_host = urlparse(pat.replace("*", "x")).netloc
            if pat_host and "*" not in pat.split("://", 1)[1].split("/", 1)[0] and pat_host not in allowed_domains:
                allowed_domains.append(pat_host)
    if allowed_domains:
        filters.append(DomainFilter(allowed_domains=allowed_domains))

    filters.append(URLPatternFilter(patterns=[_NON_HTML_ASSET_RE], reverse=True))

    if not config.allow_all_paths and not config.include_patterns:
        scope_pattern = _build_path_scope_regex(config.url)
        if scope_pattern is not None:
            filters.append(URLPatternFilter(patterns=[scope_pattern]))

    if config.include_patterns:
        compiled_includes: list[str | re.Pattern[str]] = [compile_url_pattern(pat) for pat in config.include_patterns]
        filters.append(URLPatternFilter(patterns=compiled_includes))

    if config.exclude_patterns:
        compiled_excludes: list[str | re.Pattern[str]] = [compile_url_pattern(pat) for pat in config.exclude_patterns]
        filters.append(URLPatternFilter(patterns=compiled_excludes, reverse=True))

    return FilterChain(filters)


def _flatten_crawl_results(raw_result: Any) -> list[CrawlResult]:
    if isinstance(raw_result, CrawlResult):
        return [raw_result]
    if isinstance(raw_result, (str, bytes, Mapping)):
        return []
    if isinstance(raw_result, Iterable):
        results: list[CrawlResult] = []
        for item in raw_result:
            results.extend(_flatten_crawl_results(item))
        return results
    return []


def _resolve_crawl_config(
    url_or_config: CrawlConfig | str,
    output_dir: str | Path | None = None,
    *,
    max_depth: int = 2,
    max_pages: int = 100,
    method: ExtractorType = "dom-markdownify",
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
    allow_all_paths: bool = False,
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
    verbose: bool = False,
) -> CrawlConfig:
    if isinstance(url_or_config, CrawlConfig):
        return url_or_config
    if output_dir is None:
        raise ValueError("output_dir is required when calling crawl_site with a URL string.")
    resolved_fields = parse_frontmatter_fields(frontmatter_fields) if frontmatter_fields is not None else None
    return CrawlConfig(
        url=url_or_config,
        output_dir=Path(output_dir),
        max_depth=max_depth,
        max_pages=max_pages,
        method=method,
        include_patterns=list(include_patterns),
        exclude_patterns=list(exclude_patterns),
        allow_all_paths=allow_all_paths,
        frontmatter=frontmatter or resolved_fields is not None,
        frontmatter_fields=resolved_fields,
        verbose=verbose,
    )


@overload
async def crawl_site(url_or_config: CrawlConfig, *, crawler: Any | None = None) -> CrawlSummary: ...


@overload
async def crawl_site(
    url_or_config: str,
    output_dir: str | Path,
    *,
    max_depth: int = 2,
    max_pages: int = 100,
    method: ExtractorType = "dom-markdownify",
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
    allow_all_paths: bool = False,
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
    verbose: bool = False,
    crawler: Any | None = None,
) -> CrawlSummary: ...


async def crawl_site(
    url_or_config: CrawlConfig | str,
    output_dir: str | Path | None = None,
    *,
    max_depth: int = 2,
    max_pages: int = 100,
    method: ExtractorType = "dom-markdownify",
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
    allow_all_paths: bool = False,
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
    verbose: bool = False,
    crawler: Any | None = None,
) -> CrawlSummary:
    """ドキュメントサイトをクロールし、リンク解決済みの Markdown と目次群を出力する。"""
    config = _resolve_crawl_config(
        url_or_config,
        output_dir,
        max_depth=max_depth,
        max_pages=max_pages,
        method=method,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        allow_all_paths=allow_all_paths,
        frontmatter=frontmatter,
        frontmatter_fields=frontmatter_fields,
        verbose=verbose,
    )
    filter_chain = build_filter_chain(config)
    run_config = CrawlerRunConfig(
        stream=False,
        target_elements=["main"],
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=config.max_depth,
            max_pages=config.max_pages,
            filter_chain=filter_chain,
            include_external=False,
        ),
        scraping_strategy=LXMLWebScrapingStrategy(),
        max_retries=1,
        verbose=config.verbose,
    )

    if crawler is not None:
        raw_results = await crawler.arun(config.url, config=run_config)
    else:
        browser_config = BrowserConfig(headless=True, verbose=config.verbose)
        async with AsyncWebCrawler(config=browser_config) as active_crawler:
            raw_results = await active_crawler.arun(config.url, config=run_config)

    all_results = _flatten_crawl_results(raw_results)

    failed_urls: list[str] = []
    deduped_results: list[CrawlResult] = []
    seen_keys: set[str] = set()

    for res in all_results:
        final_url = res.redirected_url or res.url
        if not res.success:
            failed_urls.append(final_url)
            continue
        key = normalize_url_key(final_url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_results.append(res)

    if not deduped_results:
        raise RuntimeError(f"No pages were successfully crawled from {config.url}")

    page_urls = [res.redirected_url or res.url for res in deduped_results]
    url_to_relpath = compute_relative_paths(page_urls, config.url)

    seed_key = normalize_url_key(config.url)
    seed_result = next(
        (res for res in deduped_results if normalize_url_key(res.redirected_url or res.url) == seed_key),
        deduped_results[0],
    )
    seed_final_url = seed_result.redirected_url or seed_result.url
    nav_order = extract_sidebar_links(seed_result.html or "", seed_final_url)

    resolved_fields = _resolve_frontmatter_fields(config.frontmatter, config.frontmatter_fields)
    crawl_timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    pages: list[CrawledPageDoc] = []
    for res in deduped_results:
        final_url = res.redirected_url or res.url
        relpath = url_to_relpath[final_url]
        crawl4ai_md = str(res.markdown) if res.markdown is not None else None
        raw_md = extract_markdown(
            res.html or "",
            url=final_url,
            method=config.method,
            crawl4ai_markdown=crawl4ai_md,
        )
        fallback_title = str((res.metadata or {}).get("title") or "")
        meta = extract_page_metadata(res.html or "", raw_md, fallback_title=fallback_title)
        rewritten = rewrite_markdown_links(raw_md, final_url, relpath, url_to_relpath)

        if resolved_fields is not None:
            fm = format_frontmatter(
                meta.title,
                meta.description,
                final_url,
                timestamp=crawl_timestamp,
                fields=resolved_fields,
            )
            final_md = f"{fm}\n\n{rewritten}".strip() + "\n"
        else:
            final_md = rewritten.strip() + "\n" if rewritten.strip() else ""

        pages.append(
            CrawledPageDoc(
                url=final_url,
                relpath=relpath,
                title=meta.title,
                description=meta.description,
                markdown=final_md,
            )
        )

    seed_host = urlparse(seed_final_url).netloc
    root_title = f"{seed_host} Documentation" if seed_host else "Documentation Index"
    toc_files = generate_toc_files(pages, nav_order=nav_order, root_title=root_title)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []

    for page in pages:
        dest = config.output_dir / page.relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page.markdown, encoding="utf-8", newline="\n")
        written_files.append(page.relpath)

    for toc_relpath, toc_content in toc_files.items():
        dest = config.output_dir / toc_relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(toc_content, encoding="utf-8", newline="\n")
        written_files.append(toc_relpath)

    return CrawlSummary(
        seed_url=config.url,
        output_dir=config.output_dir,
        page_count=len(pages),
        toc_count=len(toc_files),
        failed_urls=failed_urls,
        files=sorted(written_files),
    )


@overload
def crawl_site_sync(url_or_config: CrawlConfig, *, crawler: Any | None = None) -> CrawlSummary: ...


@overload
def crawl_site_sync(
    url_or_config: str,
    output_dir: str | Path,
    *,
    max_depth: int = 2,
    max_pages: int = 100,
    method: ExtractorType = "dom-markdownify",
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
    allow_all_paths: bool = False,
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
    verbose: bool = False,
    crawler: Any | None = None,
) -> CrawlSummary: ...


def crawl_site_sync(
    url_or_config: CrawlConfig | str,
    output_dir: str | Path | None = None,
    *,
    max_depth: int = 2,
    max_pages: int = 100,
    method: ExtractorType = "dom-markdownify",
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
    allow_all_paths: bool = False,
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
    verbose: bool = False,
    crawler: Any | None = None,
) -> CrawlSummary:
    """`crawl_site` の同期版ラッパー。"""
    config = _resolve_crawl_config(
        url_or_config,
        output_dir,
        max_depth=max_depth,
        max_pages=max_pages,
        method=method,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        allow_all_paths=allow_all_paths,
        frontmatter=frontmatter,
        frontmatter_fields=frontmatter_fields,
        verbose=verbose,
    )
    return asyncio.run(crawl_site(config, crawler=crawler))
