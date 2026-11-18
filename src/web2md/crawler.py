from __future__ import annotations

import asyncio
import posixpath
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4.dammit import UnicodeDammit
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
    build_link_lookup,
    compute_relative_paths,
    format_frontmatter,
    generate_toc_files,
    normalize_url_key,
    parse_frontmatter_fields,
    rewrite_markdown_links,
)

_NON_HTML_ASSET_RE = re.compile(
    r"\.(?:js|mjs|css|png|jpe?g|gif|svg|webp|avif|bmp|ico|pdf|zip|tar|gz|tgz|bz2|xz|7z|rar|exe|msi|dmg"
    r"|woff2?|ttf|eot|mp4|webm|mov|mp3|wav|json|xml|csv)(\?.*)?$",
    re.IGNORECASE,
)


class CrawlConfig(BaseModel):
    """Configuration for crawling a documentation website."""

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


class FailedPage(BaseModel):
    """A page that could not be fetched, with the HTTP status and the reason reported by the crawler."""

    url: str
    status_code: int | None = None
    reason: str = ""


class CrawlSummary(BaseModel):
    """Summary returned after completing a site crawl."""

    seed_url: str
    output_dir: Path
    page_count: int
    toc_count: int
    failed_pages: list[FailedPage]
    skipped_urls: list[str]
    files: list[str]


def _resolve_local_path(source: str) -> Path:
    return Path.from_uri(source) if source.startswith("file://") else Path(source)


def _decode_html(data: bytes, declared_encoding: str | None = None) -> str:
    # Falls back to <meta charset>, BOM, and content sniffing when no encoding was declared out of band.
    known_encodings = [declared_encoding] if declared_encoding else []
    return UnicodeDammit(data, known_definite_encodings=known_encodings, is_html=True).unicode_markup or ""


def _flatten_crawl_results(raw_result: Any) -> list[CrawlResult]:
    # CrawlResult is a Pydantic BaseModel (iterable of field tuples), so check it before Iterable,
    # and unwrap CrawlResultContainer objects yielded by Crawl4AI deep crawling.
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
    """Fetch HTML and the resolved final URL over HTTP(S)."""
    response = httpx.get(url, follow_redirects=True, timeout=timeout)
    response.raise_for_status()
    return _decode_html(response.content, response.charset_encoding), str(response.url)


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
    """Convert a single HTTP(S) URL or local HTML file into Markdown."""
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
        html = _decode_html(local_path.read_bytes())
        final_url = ""

    md = extract_markdown(html, url=final_url, method=method, crawl4ai_markdown=crawl4ai_markdown)
    if final_url:
        # A standalone file has no sibling pages, so every relative link must become an absolute URL.
        md = rewrite_markdown_links(md, final_url, "", {})
    if resolved_fields is not None:
        meta = extract_page_metadata(html, md)
        fm = format_frontmatter(meta.title, meta.description, final_url, fields=resolved_fields)
        md = "\n\n".join(part for part in (fm, md) if part)

    return md.rstrip() + "\n" if md else ""


def _glob_to_regex(pattern: str, *, leading_star_any: bool = False) -> str:
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("/**/", i):
            # "a/**/b" also matches "a/b", i.e. zero intermediate directories.
            parts.append("/(?:.*/)?")
            i += 4
        elif pattern.startswith("**", i):
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
    """Compile a URL pattern into a `re.Pattern`.

    - `^...` or `...$`: used as a regular expression as is.
    - Text without `*`, `?`, a scheme, or a leading `/`: matches anywhere in the URL.
    - Anything else is a glob matched against the whole URL (`*` stays within one path segment, `**` crosses them,
      and a trailing `/**` covers the directory itself and everything below). A glob starting with `/` is
      relative to the host; a glob such as `docs/**` matches at any directory boundary.
    """
    if isinstance(pattern, re.Pattern):
        return pattern

    # Pre-compile globs here because Crawl4AI's URLPatternFilter runs fnmatch.translate on `**` strings.
    raw = pattern.strip()
    if raw.startswith("^") or raw.endswith("$"):
        return re.compile(raw)
    if not ("*" in raw or "?" in raw or "://" in raw or raw.startswith("/")):
        return re.compile(re.escape(raw))

    covers_subtree = raw.endswith("/**")
    glob = raw.removesuffix("/**")
    if "://" in glob:
        body = _glob_to_regex(glob)
    elif glob.startswith("/"):
        body = rf"https?://[^/]+{_glob_to_regex(glob)}"
    elif glob.startswith("*"):
        body = _glob_to_regex(glob, leading_star_any=True)
    else:
        body = rf"https?://[^/]+/(?:.*/)?{_glob_to_regex(glob)}"
    subtree = r"(?:/.*|\?.*)?" if covers_subtree else ""
    return re.compile(rf"^{body}{subtree}$")


def _build_path_scope_regex(seed_url: str) -> re.Pattern[str] | None:
    parsed = urlparse(seed_url)
    path = parsed.path or "/"
    dir_path = posixpath.dirname(path) if not path.endswith("/") else path.rstrip("/")
    if not dir_path or dir_path == "/":
        return None
    escaped_host = re.escape(parsed.netloc.lower())
    escaped_prefix = re.escape(dir_path.rstrip("/"))
    return re.compile(rf"^https?://{escaped_host}{escaped_prefix}(?:[/?].*)?$")


def build_filter_chain(config: CrawlConfig) -> FilterChain:
    """Build a Crawl4AI `FilterChain` enforcing domain, asset, and path-scope rules."""
    parsed = urlparse(config.url)
    filters: list[Any] = []

    # Crawl4AI's DomainFilter compares port-less hostnames, so passing netloc would reject every "host:port" URL.
    allowed_domains: list[str] = [parsed.hostname] if parsed.hostname else []
    for pat in config.include_patterns:
        if "://" in pat:
            pat_host = urlparse(pat.replace("*", "x")).hostname
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


class _LinkFollowingBFSStrategy(BFSDeepCrawlStrategy):
    """BFS strategy without Crawl4AI's "host must contain a dot" rule, which rejects `localhost` and intranet hosts."""

    async def can_process_url(self, url: str, depth: int) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        return depth == 0 or await self.filter_chain.apply(url)


@dataclass
class _TriagedResults:
    pages: list[CrawlResult] = field(default_factory=list)
    # Requested URL -> final URL, for every result that was redirected.
    redirects: dict[str, str] = field(default_factory=dict)
    failed: list[FailedPage] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _final_url(result: CrawlResult) -> str:
    return result.redirected_url or result.url


async def _triage_results(results: Iterable[CrawlResult], seed_url: str, filter_chain: FilterChain) -> _TriagedResults:
    triaged = _TriagedResults()
    seed_key = normalize_url_key(seed_url)
    seen_keys: set[str] = set()

    for res in results:
        final_url = _final_url(res)
        # Crawl4AI reports HTTP error pages (404, 500, ...) as successful fetches.
        http_error = res.status_code is not None and res.status_code >= 400
        if not res.success or http_error:
            reason = res.error_message or (f"HTTP {res.status_code}" if http_error else "Unknown error")
            triaged.failed.append(FailedPage(url=final_url, status_code=res.status_code, reason=reason))
            continue

        # Filters only saw the requested URL; redirects and ".." links can still end up outside the crawl scope.
        is_seed = normalize_url_key(res.url) == seed_key
        if not is_seed and not await filter_chain.apply(final_url):
            triaged.skipped.append(final_url)
            continue

        if final_url != res.url:
            triaged.redirects[res.url] = final_url
        key = normalize_url_key(final_url)
        if key not in seen_keys:
            seen_keys.add(key)
            triaged.pages.append(res)

    return triaged


def _resolve_output_path(output_dir: Path, relpath: str) -> Path:
    root = output_dir.resolve()
    dest = (root / relpath).resolve()
    if not dest.is_relative_to(root):
        raise ValueError(f"Refusing to write outside the output directory: {relpath}")
    return dest


def _write_files(output_dir: Path, files: Mapping[str, str]) -> None:
    for relpath, content in files.items():
        dest = _resolve_output_path(output_dir, relpath)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")


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
    """Crawl a documentation site and write link-rewritten Markdown files and `index.md` TOCs."""
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
        deep_crawl_strategy=_LinkFollowingBFSStrategy(
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

    triaged = await _triage_results(_flatten_crawl_results(raw_results), config.url, filter_chain)
    if not triaged.pages:
        reasons = "; ".join(f"{page.url}: {page.reason}" for page in triaged.failed[:3])
        raise RuntimeError(
            f"No pages were successfully crawled from {config.url}" + (f" ({reasons})" if reasons else "")
        )

    url_to_relpath = compute_relative_paths([_final_url(res) for res in triaged.pages], config.url)
    link_lookup = build_link_lookup(url_to_relpath)
    # Links written against a pre-redirect URL should resolve to the page that the redirect led to.
    for requested_url, final_url in triaged.redirects.items():
        link_lookup.setdefault(normalize_url_key(requested_url), link_lookup[normalize_url_key(final_url)])

    seed_key = normalize_url_key(config.url)
    seed_result = next(
        (res for res in triaged.pages if seed_key in (normalize_url_key(res.url), normalize_url_key(_final_url(res)))),
        triaged.pages[0],
    )
    seed_final_url = _final_url(seed_result)
    nav_order = extract_sidebar_links(seed_result.html or "", seed_final_url)

    resolved_fields = _resolve_frontmatter_fields(config.frontmatter, config.frontmatter_fields)
    crawl_timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    pages: list[CrawledPageDoc] = []
    for res in triaged.pages:
        final_url = _final_url(res)
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
        rewritten = rewrite_markdown_links(raw_md, final_url, relpath, link_lookup)

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

    files = {page.relpath: page.markdown for page in pages} | toc_files
    _write_files(config.output_dir, files)

    return CrawlSummary(
        seed_url=config.url,
        output_dir=config.output_dir,
        page_count=len(pages),
        toc_count=len(toc_files),
        failed_pages=triaged.failed,
        skipped_urls=triaged.skipped,
        files=sorted(files),
    )


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
    """Synchronous wrapper around `crawl_site`."""
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
