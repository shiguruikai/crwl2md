from __future__ import annotations

import asyncio
import os
import posixpath
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urljoin, urlparse

from bs4.dammit import UnicodeDammit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from crawl4ai import BrowserConfig, CrawlResult, FilterChain

from crwl2md.extractors import (
    extract_base_url,
    extract_first_paragraph_description,
    extract_markdown,
    extract_page_metadata,
    extract_sidebar_links,
)
from crwl2md.site_builder import (
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

# Wait until the main content container has meaningful text so client-rendered pages finish hydrating.
# Crawl4AI's `csp_compliant_wait` returns False on timeout without failing the page, so short pages still succeed.
_CONTENT_READY_JS = (
    "js:() => {"
    " const selectors = ['.theme-doc-markdown', '.md-content', '.vp-doc', 'main', '[role=\"main\"]'];"
    " for (const sel of selectors) {"
    "  const el = document.querySelector(sel);"
    "  if (el) return (el.innerText || '').trim().length >= 200;"
    " }"
    " const articles = document.querySelectorAll('article');"
    " const target = articles.length === 1 ? articles[0] : document.body;"
    " return Boolean(target && (target.innerText || '').trim().length >= 200);"
    "}"
)
_CONTENT_WAIT_TIMEOUT_MS = 5000


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


def parse_headers(raw: Mapping[str, str] | Sequence[str] | None) -> dict[str, str]:
    """Parse HTTP headers from a mapping or a sequence of `'Name: Value'` strings."""
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        parsed: dict[str, str] = {}
        for key, value in raw.items():
            name = str(key).strip()
            if not name:
                raise ValueError("HTTP header name must not be empty.")
            parsed[name] = str(value).strip()
        return parsed
    if isinstance(raw, (str, bytes)):
        raise ValueError("HTTP headers must be a mapping or a sequence of 'Name: Value' strings.")
    parsed = {}
    for item in raw:
        name, sep, value = str(item).partition(":")
        cleaned_name = name.strip()
        if not sep or not cleaned_name:
            raise ValueError(f"Invalid HTTP header: {item!r}. Expected 'Name: Value' format.")
        parsed[cleaned_name] = value.strip()
    return parsed


@dataclass(frozen=True)
class _ParsedProxy:
    server: str
    username: str | None = None
    password: str | None = None


def _redact_proxy_for_error(proxy: str) -> str:
    cleaned = proxy.strip()
    if "://" in cleaned and "@" in cleaned:
        scheme, rest = cleaned.split("://", 1)
        _, host_part = rest.rsplit("@", 1)
        return f"{scheme}://***@{host_part}"
    parts = cleaned.split(":")
    if "://" not in cleaned and len(parts) == 4:
        return f"{parts[0]}:{parts[1]}:***"
    return cleaned


def _parse_proxy(proxy: str) -> _ParsedProxy:
    cleaned = proxy.strip()
    if not cleaned:
        raise ValueError("Proxy URL must not be empty.")
    safe_repr = repr(_redact_proxy_for_error(cleaned))
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(f"Invalid proxy port in {safe_repr}.") from exc
        if parsed.scheme not in ("http", "https", "socks5") or not parsed.hostname:
            raise ValueError(
                f"Invalid proxy: {safe_repr}. Expected 'http://host:port', 'https://host:port', or 'socks5://host:port'."
            )
        if port is not None and not (1 <= port <= 65535):
            raise ValueError(f"Invalid proxy port in {safe_repr}: port must be between 1 and 65535.")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        server = f"{parsed.scheme}://{host}:{port}" if port is not None else f"{parsed.scheme}://{host}"
        username = unquote(parsed.username) if parsed.username is not None else None
        password = unquote(parsed.password) if parsed.password is not None else None
        return _ParsedProxy(server=server, username=username, password=password)
    parts = cleaned.split(":")
    if len(parts) in (2, 4) and all(parts) and parts[1].isdigit():
        port_num = int(parts[1])
        if not (1 <= port_num <= 65535):
            raise ValueError(f"Invalid proxy port in {safe_repr}: port must be between 1 and 65535.")
        server = f"http://{parts[0]}:{port_num}"
        if len(parts) == 4:
            return _ParsedProxy(server=server, username=parts[2], password=parts[3])
        return _ParsedProxy(server=server)
    raise ValueError(
        f"Invalid proxy: {safe_repr}. Expected 'http://host:port', 'socks5://host:port', 'host:port', or 'host:port:user:pass'."
    )


def _validate_proxy(proxy: str | None) -> str | None:
    if proxy is None:
        return None
    _parse_proxy(proxy)
    return proxy.strip()


def _build_proxy_config(proxy: str | None) -> Any:
    if not proxy:
        return None
    from crawl4ai import ProxyConfig

    parsed = _parse_proxy(proxy)
    return ProxyConfig(server=parsed.server, username=parsed.username, password=parsed.password)


def _validate_storage_and_profile(
    storage_state: Path | None,
    user_data_dir: Path | None,
) -> None:
    if storage_state is not None and user_data_dir is not None:
        raise ValueError("Cannot specify both storage_state (--storage-state) and user_data_dir (--user-data-dir).")
    if storage_state is not None and not storage_state.is_file():
        raise FileNotFoundError(f"Storage state file not found: {storage_state}")
    if user_data_dir is not None and user_data_dir.exists() and not user_data_dir.is_dir():
        raise ValueError(f"User data path exists and is not a directory: {user_data_dir}")


@dataclass(frozen=True)
class _BrowserFetchOptions:
    headers: dict[str, str] = field(default_factory=dict)
    storage_state: Path | None = None
    user_data_dir: Path | None = None
    proxy: str | None = None
    stealth: bool = False
    wait_for: str | None = None
    scan_full_page: bool = False
    flatten_shadow_dom: bool = False
    verbose: bool = False


class CrawlConfig(BaseModel):
    """Configuration for crawling a documentation website."""

    # Avoid echoing sensitive fields (`headers`, `proxy`) in Pydantic validation tracebacks.
    model_config = ConfigDict(hide_input_in_errors=True)

    url: str
    output_dir: Path
    max_depth: int | None = Field(default=None, ge=0)
    max_pages: int = Field(default=100, ge=1)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    allow_all_paths: bool = False
    respect_robots: bool = False
    # Seconds to wait before each batch of up to `concurrency` requests. Crawl4AI adds up to 0.3 s of jitter
    # and lengthens the wait by itself after HTTP 429 / 503 responses.
    delay: float = Field(default=0.1, ge=0)
    concurrency: int = Field(default=5, ge=1)
    headers: dict[str, str] = Field(default_factory=dict)
    storage_state: Path | None = None
    user_data_dir: Path | None = None
    proxy: str | None = None
    stealth: bool = False
    wait_for: str | None = None
    scan_full_page: bool = False
    flatten_shadow_dom: bool = False
    frontmatter: bool = False
    frontmatter_fields: list[FrontmatterField] | None = None
    force: bool = False
    verbose: bool = False

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return validate_http_url(value)

    @field_validator("headers", mode="before")
    @classmethod
    def _validate_headers(cls, value: Any) -> dict[str, str]:
        return parse_headers(value)

    @field_validator("proxy")
    @classmethod
    def _validate_proxy_field(cls, value: str | None) -> str | None:
        return _validate_proxy(value)

    @field_validator("wait_for")
    @classmethod
    def _validate_wait_for(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("wait_for must not be empty.")
        return cleaned

    @model_validator(mode="after")
    def _check_storage_and_profile(self) -> CrawlConfig:
        _validate_storage_and_profile(self.storage_state, self.user_data_dir)
        return self


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
    unfetched_in_scope_links: int = 0
    hit_max_pages: bool = False
    hit_max_depth: bool = False
    files: list[str]


class BrowserNotInstalledError(RuntimeError):
    """Raised when the headless browser that crawling needs has not been downloaded."""


def install_browser(*, with_deps: bool = False) -> None:
    """Download the headless Chromium build that the installed Playwright version requires.

    Set `with_deps=True` on Linux to also install missing OS libraries (may prompt for sudo).
    """
    # Playwright pins one browser build per release, so the download must go through this environment's Playwright.
    command = [sys.executable, "-m", "playwright", "install"]
    if with_deps:
        command.append("--with-deps")
    command.extend(["chromium", "--only-shell"])
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


async def _arun_with_browser(
    url: str,
    run_config: Any,
    *,
    options: _BrowserFetchOptions | None = None,
    crawler: Any | None = None,
) -> Any:
    if crawler is not None:
        return await crawler.arun(url, config=run_config)

    from crawl4ai import BrowserConfig
    from playwright.async_api import Error as PlaywrightError

    opts = options or _BrowserFetchOptions()
    # Crawl4AI prints a promotional banner unless told otherwise; an explicit user setting still wins.
    os.environ.setdefault("CRAWL4AI_NO_CLOUD_NOTICE", "1")
    proxy_cfg = _build_proxy_config(opts.proxy)
    # text_mode skips image/font requests in normal crawls, but disables WebGL and blocks assets that anti-bot
    # checks inspect, so keep full rendering enabled when stealth mode is active.
    browser_kwargs: dict[str, Any] = {
        "headless": True,
        "text_mode": not opts.stealth,
        "user_agent": await _get_desktop_chrome_user_agent(),
        "headers": dict(opts.headers),
        "storage_state": str(opts.storage_state) if opts.storage_state is not None else None,
        "use_persistent_context": opts.user_data_dir is not None,
        "proxy_config": proxy_cfg,
        "enable_stealth": opts.stealth,
        "verbose": opts.verbose,
    }
    if opts.user_data_dir is not None:
        browser_kwargs["user_data_dir"] = str(opts.user_data_dir)
    browser_config = BrowserConfig(**browser_kwargs)
    try:
        async with _create_browser_crawler(browser_config) as active_crawler:
            return await active_crawler.arun(url, config=run_config)
    except PlaywrightError as exc:
        msg = str(exc)
        if "Executable doesn't exist" in msg:
            raise BrowserNotInstalledError(
                "The headless browser is not installed, or it does not match the installed Playwright version. "
                "Run `crwl2md setup` (or call `crwl2md.install_browser()`) to download it."
            ) from exc
        if "Host system is missing dependencies" in msg or "error while loading shared libraries" in msg:
            raise BrowserNotInstalledError(
                "System libraries required by the headless browser are missing. "
                "Run `crwl2md setup --with-deps` (or call `crwl2md.install_browser(with_deps=True)`) to install them."
            ) from exc
        raise


def _build_crawler_run_config(
    options: _BrowserFetchOptions,
    *,
    deep_crawl_strategy: Any | None = None,
    check_robots_txt: bool = False,
    mean_delay: float = 0.1,
    semaphore_count: int = 5,
) -> Any:
    from crawl4ai import CrawlerRunConfig

    proxy_cfg = _build_proxy_config(options.proxy)
    wait_for = options.wait_for if options.wait_for is not None else _CONTENT_READY_JS
    # `prefetch=True` returns raw HTML and links without running Crawl4AI's own HTML cleaner or html2text converter.
    # Anti-bot sensors often run after `domcontentloaded`, so stealth mode waits for the `load` event.
    run_kwargs: dict[str, Any] = {
        "stream": False,
        "prefetch": True,
        "deep_crawl_strategy": deep_crawl_strategy,
        "proxy_config": proxy_cfg,
        "wait_until": "load" if options.stealth else "domcontentloaded",
        "wait_for": wait_for,
        "scan_full_page": options.scan_full_page,
        "flatten_shadow_dom": options.flatten_shadow_dom,
        "simulate_user": options.stealth,
        "override_navigator": options.stealth,
        "max_retries": 1,
        "check_robots_txt": check_robots_txt,
        "mean_delay": mean_delay,
        "semaphore_count": semaphore_count,
        "verbose": options.verbose,
    }
    if options.wait_for is None:
        run_kwargs["wait_for_timeout"] = _CONTENT_WAIT_TIMEOUT_MS
    return CrawlerRunConfig(**run_kwargs)


async def _fetch_html_with_browser(
    url: str,
    *,
    options: _BrowserFetchOptions | None = None,
    crawler: Any | None = None,
) -> tuple[str, str]:
    opts = options or _BrowserFetchOptions()
    run_config = _build_crawler_run_config(opts)
    raw = await _arun_with_browser(url, run_config, options=opts, crawler=crawler)
    results = _flatten_crawl_results(raw)
    if not results:
        raise RuntimeError(f"Failed to fetch {url}: no result returned by crawler")
    res = results[0]
    final_url = _final_url(res)
    status_code = _effective_status_code(res)
    http_error = status_code is not None and status_code >= 400
    if not res.success or http_error:
        reason = res.error_message or (f"HTTP {status_code}" if http_error else "Unknown error")
        raise RuntimeError(f"Failed to fetch {final_url}: {reason}")
    return res.html or "", final_url


def _resolve_frontmatter_fields(
    frontmatter: bool,
    frontmatter_fields: Sequence[FrontmatterField] | str | None,
) -> list[FrontmatterField] | None:
    if frontmatter_fields is not None:
        return parse_frontmatter_fields(frontmatter_fields)
    if frontmatter:
        return list(FRONTMATTER_FIELDS)
    return None


async def convert_single(
    source: str | PathLike[str],
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
    *,
    headers: Mapping[str, str] | Sequence[str] | None = None,
    storage_state: str | PathLike[str] | None = None,
    user_data_dir: str | PathLike[str] | None = None,
    proxy: str | None = None,
    stealth: bool = False,
    wait_for: str | None = None,
    scan_full_page: bool = False,
    flatten_shadow_dom: bool = False,
    crawler: Any | None = None,
) -> str:
    """Convert a single HTTP(S) URL, `file://` URI, or local HTML file path into Markdown.

    HTTP(S) URLs are rendered with the headless browser; `crawler` replaces it for tests.
    """
    resolved_fields = _resolve_frontmatter_fields(frontmatter, frontmatter_fields)
    parsed_headers = parse_headers(headers)
    resolved_storage = Path(storage_state) if storage_state is not None else None
    resolved_profile = Path(user_data_dir) if user_data_dir is not None else None
    _validate_storage_and_profile(resolved_storage, resolved_profile)
    validated_proxy = _validate_proxy(proxy)
    cleaned_wait_for: str | None = None
    if wait_for is not None:
        cleaned_wait_for = wait_for.strip()
        if not cleaned_wait_for:
            raise ValueError("wait_for must not be empty.")

    if isinstance(source, str) and source.startswith(("http://", "https://")):
        options = _BrowserFetchOptions(
            headers=parsed_headers,
            storage_state=resolved_storage,
            user_data_dir=resolved_profile,
            proxy=validated_proxy,
            stealth=stealth,
            wait_for=cleaned_wait_for,
            scan_full_page=scan_full_page,
            flatten_shadow_dom=flatten_shadow_dom,
        )
        html, final_url = await _fetch_html_with_browser(source, options=options, crawler=crawler)
        md = extract_markdown(html, url=final_url)
        if not md.strip():
            raise RuntimeError(f"Empty page content for {final_url}")
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


def convert_single_sync(
    source: str | PathLike[str],
    frontmatter: bool = False,
    frontmatter_fields: Sequence[FrontmatterField] | str | None = None,
    *,
    headers: Mapping[str, str] | Sequence[str] | None = None,
    storage_state: str | PathLike[str] | None = None,
    user_data_dir: str | PathLike[str] | None = None,
    proxy: str | None = None,
    stealth: bool = False,
    wait_for: str | None = None,
    scan_full_page: bool = False,
    flatten_shadow_dom: bool = False,
    crawler: Any | None = None,
) -> str:
    """Synchronous wrapper around `convert_single` for callers without a running event loop."""
    return asyncio.run(
        convert_single(
            source,
            frontmatter=frontmatter,
            frontmatter_fields=frontmatter_fields,
            headers=headers,
            storage_state=storage_state,
            user_data_dir=user_data_dir,
            proxy=proxy,
            stealth=stealth,
            wait_for=wait_for,
            scan_full_page=scan_full_page,
            flatten_shadow_dom=flatten_shadow_dom,
            crawler=crawler,
        )
    )


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
def _link_following_bfs_strategy_cls() -> Any:
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
    from crawl4ai.utils import normalize_url_for_deep_crawl

    class _LinkFollowingBFSStrategy(BFSDeepCrawlStrategy):
        """BFS strategy fixing Crawl4AI 0.9.5 traversal quirks and streaming per-page completion callbacks."""

        def __init__(
            self,
            *args: Any,
            on_page_fetched: Callable[[CrawlResult, int], None] | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(*args, **kwargs)
            self._on_page_fetched = on_page_fetched

        async def can_process_url(self, url: str, depth: int) -> bool:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return False
            return depth == 0 or await self.filter_chain.apply(url)

        async def link_discovery(
            self,
            result: CrawlResult,
            source_url: str,
            current_depth: int,
            visited: set[str],
            next_level: list[tuple[str, str | None]],
            depths: dict[str, int],
        ) -> None:
            next_depth = current_depth + 1
            if next_depth > self.max_depth:
                return

            remaining_capacity = self.max_pages - self._pages_crawled - len(next_level)
            if remaining_capacity <= 0:
                return

            links_map = result.links if isinstance(result.links, Mapping) else {}
            links: list[Any] = list(links_map.get("internal", []) or [])
            if self.include_external:
                links.extend(links_map.get("external", []) or [])

            queued_urls = {u for u, _ in next_level}
            valid_links: list[str] = []
            seen_in_page: set[str] = set()
            for link in links:
                href = link.get("href") if isinstance(link, Mapping) else None
                if not isinstance(href, str):
                    continue
                base_url = normalize_url_for_deep_crawl(href, source_url)
                if not base_url or base_url in visited or base_url in queued_urls or base_url in seen_in_page:
                    continue
                if not await self.can_process_url(base_url, next_depth):
                    self.stats.urls_skipped += 1
                    continue
                seen_in_page.add(base_url)
                valid_links.append(base_url)

            # Register only URLs that actually enter `next_level` so links truncated by `remaining_capacity`
            # remain discoverable if earlier URLs in the level return HTTP 4xx/5xx or redirect out of scope.
            if len(valid_links) > remaining_capacity:
                valid_links = valid_links[: int(remaining_capacity)]

            for url in valid_links:
                visited.add(url)
                next_level.append((url, source_url))
                depths[url] = next_depth

        async def _arun_batch(
            self,
            start_url: str,
            crawler: Any,
            config: Any,
        ) -> list[CrawlResult]:
            self._cancel_event = asyncio.Event()
            visited: set[str] = set()
            current_level: list[tuple[str, str | None]] = [(start_url, None)]
            depths: dict[str, int] = {start_url: 0}
            self._pages_crawled = 0
            results: list[CrawlResult] = []

            while current_level and not self._cancel_event.is_set():
                if self._pages_crawled >= self.max_pages or await self._check_cancellation():
                    break

                next_level: list[tuple[str, str | None]] = []
                remaining = self.max_pages - self._pages_crawled
                if remaining < len(current_level):
                    current_level = current_level[: max(int(remaining), 0)]
                urls = [url for url, _ in current_level]
                url_order = {u: idx for idx, u in enumerate(urls)}
                parents = dict(reversed(current_level))
                for u in urls:
                    visited.add(u)
                    if normalized := normalize_url_for_deep_crawl(u, u):
                        visited.add(normalized)

                # Stream results within each BFS level so progress is reported as soon as each page finishes.
                level_config = config.clone(deep_crawl_strategy=None, stream=True)
                raw_level = await crawler.arun_many(urls=urls, config=level_config)
                level_results: list[CrawlResult] = []
                if hasattr(raw_level, "__aiter__"):
                    async for item in raw_level:
                        for result in _flatten_crawl_results(item):
                            level_results.append(result)
                            await self._record_fetched_page(result, depths, parents, visited)
                else:
                    for result in _flatten_crawl_results(raw_level):
                        level_results.append(result)
                        await self._record_fetched_page(result, depths, parents, visited)

                # Restore BFS URL order before appending results and discovering links so crawl results are deterministic.
                level_results.sort(key=lambda res: url_order.get(res.url, len(urls)))
                results.extend(level_results)

                for result in level_results:
                    depth = depths.get(result.url, 0)
                    status_code = _effective_status_code(result)
                    out_of_scope = bool((result.metadata or {}).get("out_of_scope"))
                    # Follow links from the seed URL even if it returns HTTP 404: a section directory URL such as
                    # `/advanced/` often has no index page of its own while still rendering the site's sidebar links.
                    if result.success and not out_of_scope and (depth == 0 or status_code is None or status_code < 400):
                        await self.link_discovery(result, _final_url(result), depth, visited, next_level, depths)

                current_level = next_level

            return results

        async def _record_fetched_page(
            self,
            result: CrawlResult,
            depths: Mapping[str, int],
            parents: Mapping[str, str | None],
            visited: set[str],
        ) -> None:
            url = result.url
            depth = depths.get(url, 0)
            result.metadata = result.metadata or {}
            result.metadata["depth"] = depth
            result.metadata["parent_url"] = parents.get(url)

            final_url = _final_url(result)
            visited.add(final_url)
            if normalized := normalize_url_for_deep_crawl(final_url, url):
                visited.add(normalized)

            status_code = _effective_status_code(result)
            is_ok = result.success and (status_code is None or status_code < 400)
            out_of_scope = is_ok and depth > 0 and not await self.filter_chain.apply(final_url)
            if out_of_scope:
                result.metadata["out_of_scope"] = True
            elif is_ok:
                self._pages_crawled += 1
            if self._on_page_fetched is not None:
                self._on_page_fetched(result, self._pages_crawled)

    return _LinkFollowingBFSStrategy


_DESKTOP_CHROME_UA: str | None = None


async def _get_desktop_chrome_user_agent() -> str:
    global _DESKTOP_CHROME_UA
    if _DESKTOP_CHROME_UA is None:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            _DESKTOP_CHROME_UA = str(playwright.devices["Desktop Chrome"]["user_agent"])
    return _DESKTOP_CHROME_UA


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
    description_from_meta: bool = False


def _final_url(result: CrawlResult) -> str:
    return result.redirected_url or result.url


def _effective_status_code(result: CrawlResult) -> int | None:
    # Crawl4AI stores the first redirect hop's status (301/302) in `status_code` and the final page's status in
    # `redirected_status_code`.
    return result.redirected_status_code if result.redirected_status_code is not None else result.status_code


async def _triage_results(results: Iterable[CrawlResult], seed_url: str, filter_chain: FilterChain) -> _TriagedResults:
    triaged = _TriagedResults()
    seed_key = normalize_url_key(seed_url)
    seen_keys: set[str] = set()

    for res in results:
        final_url = _final_url(res)
        status_code = _effective_status_code(res)
        # Crawl4AI reports HTTP error pages (404, 500, ...) as successful fetches.
        http_error = status_code is not None and status_code >= 400
        if not res.success or http_error:
            reason = res.error_message or (f"HTTP {status_code}" if http_error else "Unknown error")
            triaged.failed.append(FailedPage(url=final_url, status_code=status_code, reason=reason))
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


async def _analyze_unfetched_links(
    all_results: Sequence[CrawlResult],
    extracted_pages: Sequence[_ExtractedPage],
    config: CrawlConfig,
    filter_chain: FilterChain,
) -> tuple[int, bool, bool]:
    fetched_keys: set[str] = set()
    for res in all_results:
        fetched_keys.add(normalize_url_key(res.url))
        fetched_keys.add(normalize_url_key(_final_url(res)))

    unfetched_keys: set[str] = set()
    has_unfetched_at_max_depth = False

    for item in extracted_pages:
        links_map = item.result.links
        if not isinstance(links_map, Mapping):
            continue
        raw_depth = (item.result.metadata or {}).get("depth")
        page_depth = raw_depth if isinstance(raw_depth, int) else None

        for group in ("internal", "external"):
            entries = links_map.get(group)
            if not isinstance(entries, Iterable) or isinstance(entries, (str, bytes)):
                continue
            for entry in entries:
                href = entry.get("href") if isinstance(entry, Mapping) else None
                if not isinstance(href, str):
                    continue
                cleaned_href = href.strip()
                if not cleaned_href or cleaned_href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                    continue
                abs_url = urljoin(item.link_base_url, cleaned_href)
                parsed = urlparse(abs_url)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    continue
                clean_url = parsed._replace(fragment="").geturl()
                key = normalize_url_key(clean_url)
                if key in fetched_keys or key in unfetched_keys:
                    continue
                if await filter_chain.apply(clean_url):
                    unfetched_keys.add(key)
                    if config.max_depth is not None and page_depth is not None and page_depth >= config.max_depth:
                        has_unfetched_at_max_depth = True

    if not unfetched_keys:
        return 0, False, False

    successful_fetches = sum(
        1
        for res in all_results
        if res.success
        and ((sc := _effective_status_code(res)) is None or sc < 400)
        and not (res.metadata or {}).get("out_of_scope")
    )
    hit_max_pages = successful_fetches >= config.max_pages
    hit_max_depth = config.max_depth is not None and has_unfetched_at_max_depth
    return len(unfetched_keys), hit_max_pages, hit_max_depth


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


async def crawl_site(
    config: CrawlConfig,
    *,
    crawler: Any | None = None,
    on_progress: Callable[[CrawlResult, int], None] | None = None,
) -> CrawlSummary:
    """Crawl a documentation site and write link-rewritten Markdown files and `index.md` TOCs.

    `crawler` replaces the Crawl4AI browser crawler and exists for tests.
    `on_progress` is called with `(result, successful_page_count)` as each page fetch finishes.
    """
    _ensure_output_dir_writable(config.output_dir, force=config.force)

    filter_chain = build_filter_chain(config)
    include_external = len(_allowed_domains(config)) > 1
    strategy_cls = _link_following_bfs_strategy_cls()
    effective_max_depth = config.max_depth if config.max_depth is not None else sys.maxsize
    progress_reported = False

    def handle_page_fetched(result: CrawlResult, pages_crawled: int) -> None:
        nonlocal progress_reported
        progress_reported = True
        if on_progress is not None:
            on_progress(result, pages_crawled)

    options = _BrowserFetchOptions(
        headers=dict(config.headers),
        storage_state=config.storage_state,
        user_data_dir=config.user_data_dir,
        proxy=config.proxy,
        stealth=config.stealth,
        wait_for=config.wait_for,
        scan_full_page=config.scan_full_page,
        flatten_shadow_dom=config.flatten_shadow_dom,
        verbose=config.verbose,
    )
    run_config = _build_crawler_run_config(
        options,
        deep_crawl_strategy=strategy_cls(
            max_depth=effective_max_depth,
            max_pages=config.max_pages,
            filter_chain=filter_chain,
            include_external=include_external,
            on_page_fetched=handle_page_fetched,
        ),
        check_robots_txt=config.respect_robots,
        mean_delay=config.delay,
        semaphore_count=config.concurrency,
    )

    raw_results = await _arun_with_browser(config.url, run_config, options=options, crawler=crawler)

    all_results = _flatten_crawl_results(raw_results)
    if on_progress is not None and not progress_reported:
        crawled_so_far = 0
        for res in all_results:
            status_code = _effective_status_code(res)
            if (
                res.success
                and (status_code is None or status_code < 400)
                and not (res.metadata or {}).get("out_of_scope")
            ):
                crawled_so_far += 1
            on_progress(res, crawled_so_far)
    triaged = await _triage_results(all_results, config.url, filter_chain)

    extracted: list[_ExtractedPage] = []
    for res in triaged.pages:
        final_url = _final_url(res)
        status_code = _effective_status_code(res)
        html = res.html or ""
        try:
            raw_md = extract_markdown(html, url=final_url)
            if not raw_md.strip():
                triaged.failed.append(FailedPage(url=final_url, status_code=status_code, reason="Empty page content"))
                continue
            fallback_title = str((res.metadata or {}).get("title") or "")
            meta = extract_page_metadata(html, raw_md, fallback_title=fallback_title)
            link_base_url = extract_base_url(html, final_url)
        except Exception as exc:
            triaged.failed.append(
                FailedPage(url=final_url, status_code=status_code, reason=f"Conversion failed: {exc}")
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
                description_from_meta=meta.description_from_meta,
            )
        )

    if not extracted:
        reasons = "; ".join(f"{page.url}: {page.reason}" for page in triaged.failed[:3])
        raise RuntimeError(
            f"No pages were successfully crawled from {config.url}" + (f" ({reasons})" if reasons else "")
        )

    # Many doc generators repeat a site-wide `<meta name="description">` on every page; fall back to each page's
    # opening paragraph when the same meta description appears on more than one crawled page.
    meta_description_counts = Counter(
        item.description for item in extracted if item.description_from_meta and item.description
    )
    for item in extracted:
        if item.description_from_meta and meta_description_counts[item.description] >= 2:
            item.description = extract_first_paragraph_description(item.raw_markdown) or item.title

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
                    status_code=_effective_status_code(item.result),
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

    unfetched_count, hit_max_pages, hit_max_depth = await _analyze_unfetched_links(
        all_results, extracted, config, filter_chain
    )

    return CrawlSummary(
        seed_url=config.url,
        output_dir=config.output_dir,
        page_count=len(pages),
        toc_count=len(toc_files),
        failed_pages=triaged.failed,
        skipped_urls=triaged.skipped,
        seed_redirected_to=triaged.seed_redirected_to,
        unfetched_in_scope_links=unfetched_count,
        hit_max_pages=hit_max_pages,
        hit_max_depth=hit_max_depth,
        files=sorted(files),
    )


def crawl_site_sync(
    config: CrawlConfig,
    *,
    crawler: Any | None = None,
    on_progress: Callable[[CrawlResult, int], None] | None = None,
) -> CrawlSummary:
    """Synchronous wrapper around `crawl_site` for callers without a running event loop."""
    return asyncio.run(crawl_site(config, crawler=crawler, on_progress=on_progress))
