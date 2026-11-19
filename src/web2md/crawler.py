from __future__ import annotations

import asyncio
import os
import posixpath
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from bs4.dammit import UnicodeDammit
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from crawl4ai import BrowserConfig, CrawlResult, FilterChain
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

from web2md.extractors import (
    extract_base_url,
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


def validate_http_url(url: str) -> str:
    """Validate that `url` is an absolute `http://` or `https://` URL with a host."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            f"Invalid URL: {url!r}. URL must start with 'http://' or 'https://' and include a host "
            "(for example, https://example.com/docs/)."
        )
    return cleaned


class CrawlConfig(BaseModel):
    """Configuration for crawling a documentation website."""

    url: str
    output_dir: Path
    max_depth: int = Field(default=2, ge=0)
    max_pages: int = Field(default=100, ge=1)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    allow_all_paths: bool = False
    respect_robots: bool = False
    # Seconds to wait before each batch of up to `concurrency` requests. Crawl4AI adds up to 0.3 s of jitter
    # and lengthens the wait by itself after HTTP 429 / 503 responses.
    delay: float = Field(default=0.1, ge=0)
    concurrency: int = Field(default=5, ge=1)
    frontmatter: bool = False
    frontmatter_fields: list[FrontmatterField] | None = None
    force: bool = False
    verbose: bool = False

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return validate_http_url(value)


class FailedPage(BaseModel):
    """A page that could not be fetched or converted, with the HTTP status and failure reason."""

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
    # Set when the seed was redirected outside the crawl scope, which leaves its links unfollowed.
    # Crawling again with this URL as the seed covers the site.
    seed_redirected_to: str | None = None
    files: list[str]


class BrowserNotInstalledError(RuntimeError):
    """Raised when the headless browser that crawling needs has not been downloaded."""


def install_browser() -> None:
    """Download the headless Chromium build that the installed Playwright version requires."""
    # Playwright pins one browser build per release, so the download must go through this environment's Playwright.
    command = [sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Browser download failed (playwright exited with code {result.returncode}).")


def _resolve_local_path(source: str | PathLike[str]) -> Path:
    if isinstance(source, str) and source.startswith("file://"):
        return Path.from_uri(source)
    return Path(source)


def _decode_html(data: bytes, declared_encoding: str | None = None) -> str:
    # Falls back to <meta charset>, BOM, and content sniffing when no encoding was declared out of band.
    known_encodings = [declared_encoding] if declared_encoding else []
    return UnicodeDammit(data, known_definite_encodings=known_encodings, is_html=True).unicode_markup or ""


def _flatten_crawl_results(raw_result: Any) -> list[CrawlResult]:
    from crawl4ai import CrawlResult

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


def fetch_html(url: str, timeout: float = 30.0) -> tuple[str, str]:
    """Fetch HTML and the resolved final URL over HTTP(S)."""
    import httpx

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
    source: str | PathLike[str],
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
) -> str:
    """Convert a single HTTP(S) URL, `file://` URI, or local HTML file path into Markdown."""
    resolved_fields = _resolve_frontmatter_fields(frontmatter, frontmatter_fields)

    if isinstance(source, str) and source.startswith(("http://", "https://")):
        html, final_url = fetch_html(source)
    else:
        local_path = _resolve_local_path(source)
        if not local_path.is_file():
            raise FileNotFoundError(f"HTML file not found: {source}")
        html = _decode_html(local_path.read_bytes())
        final_url = ""

    md = extract_markdown(html, url=final_url)
    link_base_url = extract_base_url(html, final_url)
    if link_base_url:
        # A standalone file has no sibling pages, so every relative link must become an absolute URL.
        md = rewrite_markdown_links(md, link_base_url, "", {})
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


def _seed_scope_dir(seed_url: str) -> str | None:
    """Return the directory that bounds the crawl by default, or None when the whole host is in scope."""
    path = urlparse(seed_url).path or "/"
    if path.endswith("/"):
        scope_dir = path
    else:
        # A page seed ("/docs/intro") is scoped to its directory so that sibling pages are crawled too.
        scope_dir = posixpath.dirname(path)
        # "/docs" has no parent directory to fall back on; scoping it to "/" would silently cover the whole host.
        # A root-level file such as "/index.html" still means the whole host.
        if scope_dir == "/" and "." not in posixpath.basename(path):
            scope_dir = path
    return scope_dir.rstrip("/") or None


def _build_path_scope_regex(seed_url: str) -> re.Pattern[str] | None:
    scope_dir = _seed_scope_dir(seed_url)
    if scope_dir is None:
        return None
    escaped_host = re.escape(urlparse(seed_url).netloc.lower())
    return re.compile(rf"^https?://{escaped_host}{re.escape(scope_dir)}(?:[/?].*)?$")


def describe_crawl_scope(config: CrawlConfig) -> str:
    """Describe in one line which URLs a crawl with `config` may visit beyond the seed page."""
    parsed = urlparse(config.url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if config.include_patterns:
        scope = ", ".join(config.include_patterns)
    else:
        scope_dir = None if config.allow_all_paths else _seed_scope_dir(config.url)
        scope = f"{origin}{scope_dir or ''}/**"
    if config.exclude_patterns:
        scope += f" (excluding {', '.join(config.exclude_patterns)})"
    return scope


def _allowed_domains(config: CrawlConfig) -> list[str]:
    # Crawl4AI's DomainFilter compares port-less hostnames, so passing netloc would reject every "host:port" URL.
    parsed = urlparse(config.url)
    allowed_domains: list[str] = [parsed.hostname] if parsed.hostname else []
    for pat in config.include_patterns:
        if "://" in pat:
            pat_host = urlparse(pat.replace("*", "x")).hostname
            if pat_host and "*" not in pat.split("://", 1)[1].split("/", 1)[0] and pat_host not in allowed_domains:
                allowed_domains.append(pat_host)
    return allowed_domains


def build_filter_chain(config: CrawlConfig) -> FilterChain:
    """Build a Crawl4AI `FilterChain` enforcing domain, asset, and path-scope rules."""
    from crawl4ai import DomainFilter, FilterChain, URLPatternFilter

    filters: list[Any] = []

    allowed_domains = _allowed_domains(config)
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


@cache
def _link_following_bfs_strategy_cls() -> type[BFSDeepCrawlStrategy]:
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

    class _LinkFollowingBFSStrategy(BFSDeepCrawlStrategy):
        """BFS strategy without Crawl4AI's "host must contain a dot" rule, which rejects `localhost` and intranet hosts."""

        async def can_process_url(self, url: str, depth: int) -> bool:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return False
            return depth == 0 or await self.filter_chain.apply(url)

    return _LinkFollowingBFSStrategy


def _create_browser_crawler(browser_config: BrowserConfig) -> Any:
    from crawl4ai import AsyncWebCrawler

    return AsyncWebCrawler(config=browser_config)


@dataclass
class _TriagedResults:
    pages: list[CrawlResult] = field(default_factory=list)
    # Requested URL -> final URL, for every result that was redirected.
    redirects: dict[str, str] = field(default_factory=dict)
    failed: list[FailedPage] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    seed_redirected_to: str | None = None


@dataclass
class _ExtractedPage:
    result: CrawlResult
    final_url: str
    raw_markdown: str
    title: str
    description: str
    link_base_url: str


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
        in_scope = await filter_chain.apply(final_url)
        if normalize_url_key(res.url) == seed_key:
            # The seed page is always kept, but its links were filtered against the scope of the original URL.
            if not in_scope and normalize_url_key(final_url) != seed_key:
                triaged.seed_redirected_to = final_url
        elif not in_scope:
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


def _ensure_output_dir_writable(output_dir: Path, *, force: bool) -> None:
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {output_dir}")
    if not force and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_dir}. "
            "Pass --force (or set force=True) to overwrite existing files."
        )


def _write_files(output_dir: Path, files: Mapping[str, str]) -> None:
    for relpath, content in files.items():
        dest = _resolve_output_path(output_dir, relpath)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")


async def crawl_site(config: CrawlConfig, *, crawler: Any | None = None) -> CrawlSummary:
    """Crawl a documentation site and write link-rewritten Markdown files and `index.md` TOCs.

    `crawler` replaces the Crawl4AI browser crawler and exists for tests.
    """
    _ensure_output_dir_writable(config.output_dir, force=config.force)
    from crawl4ai import BrowserConfig, CrawlerRunConfig
    from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
    from playwright.async_api import Error as PlaywrightError

    filter_chain = build_filter_chain(config)
    include_external = len(_allowed_domains(config)) > 1
    strategy_cls = _link_following_bfs_strategy_cls()
    run_config = CrawlerRunConfig(
        stream=False,
        deep_crawl_strategy=strategy_cls(
            max_depth=config.max_depth,
            max_pages=config.max_pages,
            filter_chain=filter_chain,
            include_external=include_external,
        ),
        scraping_strategy=LXMLWebScrapingStrategy(),
        max_retries=1,
        check_robots_txt=config.respect_robots,
        mean_delay=config.delay,
        semaphore_count=config.concurrency,
        verbose=config.verbose,
    )

    if crawler is not None:
        raw_results = await crawler.arun(config.url, config=run_config)
    else:
        # Crawl4AI prints a promotional banner unless told otherwise; an explicit user setting still wins.
        os.environ.setdefault("CRAWL4AI_NO_CLOUD_NOTICE", "1")
        # text_mode skips image requests since web2md only extracts HTML and keeps image URLs.
        browser_config = BrowserConfig(headless=True, text_mode=True, verbose=config.verbose)
        try:
            async with _create_browser_crawler(browser_config) as active_crawler:
                raw_results = await active_crawler.arun(config.url, config=run_config)
        except PlaywrightError as exc:
            if "Executable doesn't exist" not in str(exc):
                raise
            raise BrowserNotInstalledError(
                "The headless browser is not installed, or it does not match the installed Playwright version. "
                "Run `web2md setup` (or call `web2md.install_browser()`) to download it."
            ) from exc

    triaged = await _triage_results(_flatten_crawl_results(raw_results), config.url, filter_chain)

    extracted: list[_ExtractedPage] = []
    for res in triaged.pages:
        final_url = _final_url(res)
        html = res.html or ""
        try:
            raw_md = extract_markdown(html, url=final_url)
            fallback_title = str((res.metadata or {}).get("title") or "")
            meta = extract_page_metadata(html, raw_md, fallback_title=fallback_title)
            link_base_url = extract_base_url(html, final_url)
        except Exception as exc:
            triaged.failed.append(
                FailedPage(url=final_url, status_code=res.status_code, reason=f"Conversion failed: {exc}")
            )
            continue
        extracted.append(
            _ExtractedPage(
                result=res,
                final_url=final_url,
                raw_markdown=raw_md,
                title=meta.title,
                description=meta.description,
                link_base_url=link_base_url,
            )
        )

    if not extracted:
        reasons = "; ".join(f"{page.url}: {page.reason}" for page in triaged.failed[:3])
        raise RuntimeError(
            f"No pages were successfully crawled from {config.url}" + (f" ({reasons})" if reasons else "")
        )

    url_to_relpath = compute_relative_paths([page.final_url for page in extracted], config.url)
    link_lookup = build_link_lookup(url_to_relpath)
    # Links written against a pre-redirect URL should resolve to the page that the redirect led to.
    for requested_url, final_url in triaged.redirects.items():
        if (target := link_lookup.get(normalize_url_key(final_url))) is not None:
            link_lookup.setdefault(normalize_url_key(requested_url), target)

    seed_key = normalize_url_key(config.url)
    seed_result = next(
        (res for res in triaged.pages if seed_key in (normalize_url_key(res.url), normalize_url_key(_final_url(res)))),
        extracted[0].result,
    )
    seed_final_url = _final_url(seed_result)
    try:
        nav_order = extract_sidebar_links(seed_result.html or "", seed_final_url)
    except Exception:
        nav_order = []

    resolved_fields = _resolve_frontmatter_fields(config.frontmatter, config.frontmatter_fields)
    crawl_timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    pages: list[CrawledPageDoc] = []
    for item in extracted:
        relpath = url_to_relpath[item.final_url]
        try:
            rewritten = rewrite_markdown_links(item.raw_markdown, item.link_base_url, relpath, link_lookup)
            if resolved_fields is not None:
                fm = format_frontmatter(
                    item.title,
                    item.description,
                    item.final_url,
                    timestamp=crawl_timestamp,
                    fields=resolved_fields,
                )
                final_md = f"{fm}\n\n{rewritten}".strip() + "\n"
            else:
                final_md = rewritten.strip() + "\n" if rewritten.strip() else ""
        except Exception as exc:
            triaged.failed.append(
                FailedPage(
                    url=item.final_url,
                    status_code=item.result.status_code,
                    reason=f"Conversion failed: {exc}",
                )
            )
            continue

        pages.append(
            CrawledPageDoc(
                url=item.final_url,
                relpath=relpath,
                title=item.title,
                description=item.description,
                markdown=final_md,
            )
        )

    if not pages:
        reasons = "; ".join(f"{page.url}: {page.reason}" for page in triaged.failed[:3])
        raise RuntimeError(
            f"No pages were successfully crawled from {config.url}" + (f" ({reasons})" if reasons else "")
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
        seed_redirected_to=triaged.seed_redirected_to,
        files=sorted(files),
    )


def crawl_site_sync(config: CrawlConfig, *, crawler: Any | None = None) -> CrawlSummary:
    """Synchronous wrapper around `crawl_site` for callers without a running event loop."""
    return asyncio.run(crawl_site(config, crawler=crawler))
