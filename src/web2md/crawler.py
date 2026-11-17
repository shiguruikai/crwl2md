"""Web ページの取得、単一ページ変換、およびサイトクロール処理モジュール。"""

from __future__ import annotations

import asyncio
import posixpath
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any
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
    CrawledPageDoc,
    compute_relative_paths,
    format_frontmatter,
    generate_toc_files,
    normalize_url_key,
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


def convert_single(
    source: str,
    method: ExtractorType = "dom-markdownify",
    frontmatter: bool = False,
) -> str:
    """単一の URL またはローカル HTML ファイルを Markdown 文字列へ変換する。"""
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
    if frontmatter:
        meta = extract_page_metadata(html, md)
        fm = format_frontmatter(meta.title, meta.description, final_url)
        md = f"{fm}\n\n{md}" if md else fm

    return md.rstrip() + "\n" if md else ""


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

    if parsed.netloc:
        filters.append(DomainFilter(allowed_domains=[parsed.netloc]))

    filters.append(URLPatternFilter(patterns=[_NON_HTML_ASSET_RE], reverse=True))

    if not config.allow_all_paths:
        scope_pattern = _build_path_scope_regex(config.url)
        if scope_pattern is not None:
            filters.append(URLPatternFilter(patterns=[scope_pattern]))

    if config.include_patterns:
        filters.append(URLPatternFilter(patterns=list(config.include_patterns)))

    if config.exclude_patterns:
        filters.append(URLPatternFilter(patterns=list(config.exclude_patterns), reverse=True))

    return FilterChain(filters)


def _flatten_crawl_results(raw_result: Any) -> list[CrawlResult]:
    if isinstance(raw_result, CrawlResult):
        return [raw_result]
    if isinstance(raw_result, Iterable):
        return [item for item in raw_result if isinstance(item, CrawlResult)]
    return []


async def crawl_site(config: CrawlConfig, crawler: Any | None = None) -> CrawlSummary:
    """ドキュメントサイトをクロールし、リンク解決済みの Markdown と目次群を出力する。"""
    filter_chain = build_filter_chain(config)
    run_config = CrawlerRunConfig(
        stream=False,
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

        if config.frontmatter:
            fm = format_frontmatter(meta.title, meta.description, final_url)
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
