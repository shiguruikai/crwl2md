from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from crawl4ai import CrawlResult
from crawl4ai.models import CrawlResultContainer
from playwright.async_api import Error as PlaywrightError

from crwl2md import (
    BrowserNotInstalledError,
    CrawlConfig,
    convert_single,
    convert_single_sync,
    crawl_site,
    crawl_site_sync,
    extract_markdown,
    install_browser,
)
from crwl2md.crawler import (
    _FLATTEN_SHADOW_DOM_JS,
    _FORCE_OPEN_SHADOW_DOM_JS,
    _create_browser_crawler,
    _link_following_bfs_strategy_cls,
    _resolve_output_path,
    _shadow_dom_crawler_strategy_cls,
    build_filter_chain,
    compile_url_pattern,
    describe_crawl_scope,
    parse_headers,
)


class _FakeCrawler:
    def __init__(self, results: list[CrawlResult] | list[CrawlResultContainer[CrawlResult]]) -> None:
        self._results = results
        self.run_config: Any = None

    async def arun(self, url: str, config: Any = None) -> list[CrawlResult] | list[CrawlResultContainer[CrawlResult]]:
        self.run_config = config
        return self._results


def _page(title: str, body: str = "<p>Body.</p>") -> str:
    return f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1>{body}</main></body></html>"


async def test_crawl_site_writes_markdown_and_toc(tmp_path: Path):
    seed_html = """
    <html><head><title>SDK Overview</title></head><body>
      <aside><nav>
        <a href="/docs/sdk/start">Start</a>
        <a href="/docs/sdk/api">API</a>
      </nav></aside>
      <main>
        <h1>SDK Overview</h1>
        <p>Overview paragraph.</p>
        <p>Read <a href="/docs/sdk/start">Start</a> next.</p>
      </main>
    </body></html>
    """
    start_html = _page("Start", '<p>Begin here and inspect <a href="../sdk/api#auth">API auth</a>.</p>')
    api_html = _page("API", '<h2 id="auth">Auth</h2><p>Authentication guide.</p>')
    fake_results = [
        CrawlResult(url="https://example.com/docs/sdk", html=seed_html, success=True),
        CrawlResult(
            url="https://example.com/docs/sdk/",
            redirected_url="https://example.com/docs/sdk",
            html=seed_html,
            success=True,
        ),
        CrawlResult(url="https://example.com/docs/sdk/start", html=start_html, success=True),
        CrawlResult(url="https://example.com/docs/sdk/api", html=api_html, success=True),
        CrawlResult(url="https://example.com/docs/sdk/broken", html="", success=False, error_message="Timeout"),
    ]
    out_dir = tmp_path / "site_out"
    config = CrawlConfig(url="https://example.com/docs/sdk", output_dir=out_dir, max_depth=1, frontmatter=True)

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.page_count == 3
    assert summary.toc_count == 1
    assert [(page.url, page.reason) for page in summary.failed_pages] == [
        ("https://example.com/docs/sdk/broken", "Timeout")
    ]
    assert summary.files == ["api.md", "index.md", "overview.md", "start.md"]

    overview_text = (out_dir / "overview.md").read_text(encoding="utf-8")
    assert "[Start](start.md)" in overview_text
    assert 'title: "SDK Overview"' in overview_text

    start_text = (out_dir / "start.md").read_text(encoding="utf-8")
    assert "[API auth](api.md#auth)" in start_text

    toc_text = (out_dir / "index.md").read_text(encoding="utf-8")
    assert toc_text.index("start.md") < toc_text.index("api.md")


async def test_crawl_site_replaces_duplicate_site_wide_meta_descriptions_with_first_paragraph(tmp_path: Path):
    def page_with_shared_meta(title: str, paragraph: str) -> str:
        return (
            "<html><head>"
            f"<title>{title}</title>"
            '<meta name="description" content="Site-wide slogan repeated on every page">'
            f"</head><body><main><h1>{title}</h1>{paragraph}</main></body></html>"
        )

    fake_results = [
        CrawlResult(
            url="https://example.com/docs/intro",
            html=page_with_shared_meta("Intro", "<p>Learn how to install the CLI.</p>"),
            success=True,
        ),
        CrawlResult(
            url="https://example.com/docs/proxy",
            html=page_with_shared_meta("Proxy", "<p>Configure HTTP and SOCKS5 proxies.</p>"),
            success=True,
        ),
        CrawlResult(
            url="https://example.com/docs/empty-para",
            html=page_with_shared_meta("Code Only", "<pre><code>crwl2md --help</code></pre>"),
            success=True,
        ),
    ]
    out_dir = tmp_path / "out"
    config = CrawlConfig(url="https://example.com/docs/intro", output_dir=out_dir, frontmatter=True)

    await crawl_site(config, crawler=_FakeCrawler(fake_results))

    toc_text = (out_dir / "index.md").read_text(encoding="utf-8")
    assert "Site-wide slogan repeated on every page" not in toc_text
    assert "- [Intro](intro.md) - Learn how to install the CLI." in toc_text
    assert "- [Proxy](proxy.md) - Configure HTTP and SOCKS5 proxies." in toc_text
    assert "- [Code Only](empty-para.md)\n" in toc_text
    assert 'description: "Learn how to install the CLI."' in (out_dir / "intro.md").read_text(encoding="utf-8")
    assert 'description: "Configure HTTP and SOCKS5 proxies."' in (out_dir / "proxy.md").read_text(encoding="utf-8")


async def test_crawl_site_preserves_unique_meta_description_matching_fallback_text(tmp_path: Path):
    fake_results = [
        CrawlResult(
            url="https://example.com/docs/config",
            html=(
                '<html><head><meta name="description" content="Configuration"></head>'
                "<body><main><h1>Config</h1><p>Detailed configuration guide.</p></main></body></html>"
            ),
            success=True,
        ),
        CrawlResult(
            url="https://example.com/docs/other",
            html="<html><body><main><h1>Configuration</h1><pre><code>x = 1</code></pre></main></body></html>",
            success=True,
        ),
    ]
    out_dir = tmp_path / "out"
    config = CrawlConfig(url="https://example.com/docs/config", output_dir=out_dir, frontmatter=True)

    await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert 'description: "Configuration"' in (out_dir / "config.md").read_text(encoding="utf-8")


async def test_crawl_site_reports_http_error_pages_as_failed(tmp_path: Path):
    fake_results = [
        CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True, status_code=200),
        CrawlResult(url="https://example.com/docs/gone", html=_page("Not Found"), success=True, status_code=404),
        CrawlResult(
            url="https://example.com/docs/moved-to-404",
            redirected_url="https://example.com/docs/missing",
            html=_page("Not Found"),
            success=True,
            status_code=302,
            redirected_status_code=404,
        ),
    ]
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.page_count == 1
    assert [(page.url, page.status_code, page.reason) for page in summary.failed_pages] == [
        ("https://example.com/docs/gone", 404, "HTTP 404"),
        ("https://example.com/docs/missing", 404, "HTTP 404"),
    ]
    assert not (tmp_path / "out" / "gone.md").exists()
    assert not (tmp_path / "out" / "missing.md").exists()


async def test_crawl_site_skips_pages_that_end_up_outside_the_scope(tmp_path: Path):
    fake_results = [
        CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True),
        CrawlResult(url="https://example.com/docs/a", html=_page("A"), success=True),
        CrawlResult(
            url="https://example.com/docs/account",
            redirected_url="https://login.example.com/signin",
            html=_page("Sign in"),
            success=True,
        ),
        CrawlResult(
            url="https://example.com/docs/x/../../private/notes",
            redirected_url="https://example.com/private/notes",
            html=_page("Private"),
            success=True,
        ),
    ]
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.skipped_urls == ["https://login.example.com/signin", "https://example.com/private/notes"]
    assert summary.files == ["a.md", "index.md", "overview.md"]


async def test_crawl_site_keeps_seed_page_redirected_to_another_host(tmp_path: Path):
    fake_results = [
        CrawlResult(
            url="https://example.com/docs/",
            redirected_url="https://www.example.com/docs/",
            html=_page("Docs"),
            success=True,
        ),
    ]
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.page_count == 1
    assert summary.skipped_urls == []
    assert summary.seed_redirected_to == "https://www.example.com/docs/"


async def test_crawl_site_does_not_flag_seed_redirected_within_scope(tmp_path: Path):
    fake_results = [
        CrawlResult(
            url="https://example.com/docs",
            redirected_url="https://example.com/docs/latest/",
            html=_page("Docs"),
            success=True,
        ),
    ]
    config = CrawlConfig(url="https://example.com/docs", output_dir=tmp_path / "out")

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.seed_redirected_to is None


async def test_crawl_site_honors_base_href_when_rewriting_links(tmp_path: Path):
    seed_html = (
        '<html><head><base href="https://example.com/docs/v2/"></head>'
        '<body><main><h1>Docs</h1><p><a href="guide">Guide</a></p></main></body></html>'
    )
    fake_results = [
        CrawlResult(url="https://example.com/docs/intro", html=seed_html, success=True),
        CrawlResult(url="https://example.com/docs/v2/guide", html=_page("Guide"), success=True),
    ]
    out_dir = tmp_path / "out"
    config = CrawlConfig(url="https://example.com/docs/intro", output_dir=out_dir)

    await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert "[Guide](v2/guide.md)" in (out_dir / "intro.md").read_text(encoding="utf-8")


async def test_crawl_site_localizes_links_to_pre_redirect_urls(tmp_path: Path):
    fake_results = [
        CrawlResult(
            url="https://example.com/docs/",
            html=_page("Docs", '<p><a href="/docs/old-name">Renamed page</a></p>'),
            success=True,
        ),
        CrawlResult(
            url="https://example.com/docs/old-name",
            redirected_url="https://example.com/docs/new-name",
            html=_page("New"),
            success=True,
        ),
    ]
    out_dir = tmp_path / "out"
    config = CrawlConfig(url="https://example.com/docs/", output_dir=out_dir)

    await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert "[Renamed page](new-name.md)" in (out_dir / "overview.md").read_text(encoding="utf-8")


async def test_crawl_site_reports_empty_extracted_pages_as_failed(tmp_path: Path):
    fake_results = [
        CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True, status_code=200),
        CrawlResult(
            url="https://example.com/docs/empty",
            html="<html><body><main></main></body></html>",
            success=True,
            status_code=200,
        ),
    ]
    out_dir = tmp_path / "out"
    config = CrawlConfig(url="https://example.com/docs/", output_dir=out_dir)

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.page_count == 1
    assert summary.files == ["docs.md", "index.md"]
    assert [(page.url, page.status_code, page.reason) for page in summary.failed_pages] == [
        ("https://example.com/docs/empty", 200, "Empty page content")
    ]
    assert not (out_dir / "empty.md").exists()


async def test_crawl_site_configures_content_ready_wait(tmp_path: Path):
    fake_crawler = _FakeCrawler([CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)])
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    await crawl_site(config, crawler=fake_crawler)

    assert fake_crawler.run_config.prefetch is True
    assert fake_crawler.run_config.wait_for.startswith("js:")
    assert "document.readyState !== 'complete'" in fake_crawler.run_config.wait_for
    assert fake_crawler.run_config.wait_for_timeout == 5000


async def test_crawl_site_saves_other_pages_when_one_page_fails_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def flaky_extract(html: str, url: str = "") -> str:
        if url.endswith("/bad"):
            raise ValueError("malformed DOM")
        return extract_markdown(html, url=url)

    monkeypatch.setattr("crwl2md.crawler.extract_markdown", flaky_extract)
    fake_results = [
        CrawlResult(
            url="https://example.com/docs/",
            html=_page("Docs", '<p><a href="/docs/good">Good</a> and <a href="/docs/bad">Bad</a></p>'),
            success=True,
            status_code=200,
        ),
        CrawlResult(url="https://example.com/docs/good", html=_page("Good"), success=True, status_code=200),
        CrawlResult(url="https://example.com/docs/bad", html=_page("Bad"), success=True, status_code=200),
    ]
    out_dir = tmp_path / "out"
    config = CrawlConfig(url="https://example.com/docs/", output_dir=out_dir)

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.page_count == 2
    assert summary.files == ["good.md", "index.md", "overview.md"]
    assert [(p.url, p.reason) for p in summary.failed_pages] == [
        ("https://example.com/docs/bad", "Conversion failed: malformed DOM")
    ]
    overview = (out_dir / "overview.md").read_text(encoding="utf-8")
    assert "[Good](good.md)" in overview
    assert "[Bad](https://example.com/docs/bad)" in overview


async def test_crawl_site_raises_when_every_page_fails_conversion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def always_fail(html: str, url: str = "") -> str:
        raise ValueError("broken html")

    monkeypatch.setattr("crwl2md.crawler.extract_markdown", always_fail)
    fake_results = [CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)]
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    with pytest.raises(RuntimeError, match=r"No pages were successfully crawled.*Conversion failed: broken html"):
        await crawl_site(config, crawler=_FakeCrawler(fake_results))


async def test_crawl_site_raises_with_reason_when_no_page_succeeds(tmp_path: Path):
    fake_results = [CrawlResult(url="https://example.com/docs/", html="", success=False, error_message="DNS failure")]
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    with pytest.raises(RuntimeError, match=r"No pages were successfully crawled.*DNS failure"):
        await crawl_site(config, crawler=_FakeCrawler(fake_results))


async def test_crawl_site_refuses_non_empty_output_dir_without_force(tmp_path: Path):
    out_dir = tmp_path / "existing"
    out_dir.mkdir()
    existing = out_dir / "notes.md"
    existing.write_text("keep me", encoding="utf-8")

    class NeverCalledCrawler:
        async def arun(self, url: str, config: Any = None) -> list[CrawlResult]:
            raise AssertionError("crawler should not be invoked when output_dir is non-empty")

    config = CrawlConfig(url="https://example.com/docs/", output_dir=out_dir)

    with pytest.raises(FileExistsError, match="--force"):
        await crawl_site(config, crawler=NeverCalledCrawler())

    assert existing.read_text(encoding="utf-8") == "keep me"


async def test_crawl_site_overwrites_non_empty_output_dir_with_force(tmp_path: Path):
    out_dir = tmp_path / "existing"
    out_dir.mkdir()
    (out_dir / "index.md").write_text("old", encoding="utf-8")
    fake_results = [CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)]
    config = CrawlConfig(url="https://example.com/docs/", output_dir=out_dir, force=True)

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.page_count == 1
    assert "Docs" in (out_dir / "index.md").read_text(encoding="utf-8")


async def test_crawl_site_rejects_file_as_output_dir(tmp_path: Path):
    out_file = tmp_path / "not_a_dir"
    out_file.write_text("x", encoding="utf-8")
    config = CrawlConfig(url="https://example.com/docs/", output_dir=out_file, force=True)

    with pytest.raises(ValueError, match="not a directory"):
        await crawl_site(config, crawler=_FakeCrawler([]))


def test_crawl_config_rejects_url_without_http_scheme(tmp_path: Path):
    with pytest.raises(ValueError, match="http://"):
        CrawlConfig(url="docs.example.com/intro", output_dir=tmp_path / "out")


def test_resolve_output_path_rejects_paths_outside_output_dir(tmp_path: Path):
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="outside the output directory"):
        _resolve_output_path(out_dir, "x/../../evil.md")


def test_resolve_output_path_accepts_nested_paths(tmp_path: Path):
    out_dir = tmp_path / "out"

    dest = _resolve_output_path(out_dir, "sdk/intro.md")

    assert dest == (out_dir / "sdk" / "intro.md").resolve()


@pytest.mark.parametrize(
    ("pattern", "url", "expected"),
    [
        # Absolute glob with a trailing "/**" covers the directory itself and everything below.
        ("https://docs.example.com/cli/**", "https://docs.example.com/cli", True),
        ("https://docs.example.com/cli/**", "https://docs.example.com/cli/", True),
        ("https://docs.example.com/cli/**", "https://docs.example.com/cli/commands/create", True),
        ("https://docs.example.com/cli/**", "https://docs.example.com/cli?tab=1", True),
        ("https://docs.example.com/cli/**", "https://docs.example.com/sdk/intro", False),
        ("https://docs.example.com/cli/**", "https://docs.example.com/cli-other/intro", False),
        # "*" stays within one path segment.
        ("https://docs.example.com/cli/*", "https://docs.example.com/cli/intro", True),
        ("https://docs.example.com/cli/*", "https://docs.example.com/cli/commands/create", False),
        # "/**/" in the middle also matches zero directories.
        ("https://docs.example.com/docs/**/intro", "https://docs.example.com/docs/intro", True),
        ("https://docs.example.com/docs/**/intro", "https://docs.example.com/docs/a/b/intro", True),
        ("https://docs.example.com/docs/**/intro", "https://docs.example.com/docs/a/other", False),
        # Host-relative glob.
        ("/cli/**", "https://docs.example.com/cli/commands/create", True),
        ("/cli/**", "https://docs.example.com/sdk/cli/intro", False),
        # Relative glob matches at any directory boundary.
        ("cli/**", "https://docs.example.com/cli/intro", True),
        ("cli/**", "https://docs.example.com/v2/cli/intro", True),
        ("cli/**", "https://docs.example.com/v2/not-cli/intro", False),
        ("api/*.html", "https://docs.example.com/api/auth.html", True),
        ("*.pdf", "https://example.com/files/manual.pdf", True),
        ("*.pdf", "https://example.com/files/manual.html", False),
        # Plain text matches anywhere; anchored text is a regular expression.
        ("blog", "https://example.com/docs/blog/post", True),
        (r"^https://example\.com/v\d+/", "https://example.com/v2/intro", True),
        (r"/v\d+/intro$", "https://example.com/v2/intro", True),
    ],
)
def test_compile_url_pattern(pattern: str, url: str, expected: bool):
    compiled = compile_url_pattern(pattern)

    assert bool(compiled.search(url)) is expected


async def test_build_filter_chain_uses_include_patterns(tmp_path: Path):
    config = CrawlConfig(
        url="https://docs.elgato.com/streamdeck/cli/commands/create",
        output_dir=tmp_path / "out",
        include_patterns=["https://docs.elgato.com/streamdeck/cli/**"],
    )

    chain = build_filter_chain(config)

    assert await chain.apply("https://docs.elgato.com/streamdeck/cli/intro")
    assert await chain.apply("https://docs.elgato.com/streamdeck/cli/commands/pack")
    assert not await chain.apply("https://docs.elgato.com/streamdeck/sdk/actions")
    assert not await chain.apply("https://docs.elgato.com/streamdeck/cli/asset.js")


@pytest.mark.parametrize(
    ("seed_url", "url", "expected"),
    [
        ("https://example.com/docs/intro", "https://example.com/docs/guide", True),
        ("https://example.com/docs/intro", "https://example.com/docs?page=2", True),
        ("https://example.com/docs/intro", "https://example.com/blog/post", False),
        ("https://example.com/docs/intro", "https://other.example.org/docs/guide", False),
        ("https://Example.com/docs/intro", "https://example.com/docs/guide", True),
        ("http://127.0.0.1:8000/docs/", "http://127.0.0.1:8000/docs/guide", True),
        ("http://localhost:3000/docs/", "http://localhost:3000/docs/guide", True),
        ("http://localhost:3000/docs/", "http://localhost:3000/blog/post", False),
        # A single-segment seed is scoped to itself rather than to the whole host.
        ("https://example.com/docs", "https://example.com/docs/guide", True),
        ("https://example.com/docs", "https://example.com/blog/post", False),
        # Root-level seeds cover the whole host.
        ("https://example.com/", "https://example.com/blog/post", True),
        ("https://example.com/index.html", "https://example.com/blog/post", True),
    ],
)
async def test_build_filter_chain_limits_crawl_to_seed_host_and_directory(
    tmp_path: Path, seed_url: str, url: str, expected: bool
):
    config = CrawlConfig(url=seed_url, output_dir=tmp_path / "out")

    chain = build_filter_chain(config)

    assert await chain.apply(url) is expected


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"url": "https://example.com/docs/intro"}, "https://example.com/docs/**"),
        ({"url": "https://example.com/docs/v2/"}, "https://example.com/docs/v2/**"),
        ({"url": "https://example.com/docs"}, "https://example.com/docs/**"),
        ({"url": "https://example.com/"}, "https://example.com/**"),
        ({"url": "http://localhost:3000/docs/intro", "allow_all_paths": True}, "http://localhost:3000/**"),
        (
            {"url": "https://example.com/docs/intro", "include_patterns": ["/docs/**", "/api/**"]},
            "/docs/**, /api/**",
        ),
        (
            {"url": "https://example.com/docs/intro", "exclude_patterns": ["*/changelog"]},
            "https://example.com/docs/** (excluding */changelog)",
        ),
    ],
)
def test_describe_crawl_scope(tmp_path: Path, options: dict[str, Any], expected: str):
    config = CrawlConfig(output_dir=tmp_path / "out", **options)

    description = describe_crawl_scope(config)

    assert description == expected


async def test_bfs_strategy_follows_links_on_hosts_without_a_dot(tmp_path: Path):
    config = CrawlConfig(url="http://localhost:3000/docs/", output_dir=tmp_path / "out")
    strategy = _link_following_bfs_strategy_cls()(max_depth=1, filter_chain=build_filter_chain(config))

    in_scope = await strategy.can_process_url("http://localhost:3000/docs/guide", 1)
    out_of_scope = await strategy.can_process_url("http://localhost:3000/blog/post", 1)
    not_http = await strategy.can_process_url("mailto:docs@example.com", 1)

    assert (in_scope, out_of_scope, not_http) == (True, False, False)


async def test_bfs_strategy_streams_progress_deduplicates_redirects_and_ignores_404_links(tmp_path: Path):
    from crawl4ai import CrawlerRunConfig

    pages_by_url = {
        "https://example.com/docs/intro": CrawlResult(
            url="https://example.com/docs/intro",
            redirected_url="https://example.com/docs/intro/",
            html=_page("Intro"),
            success=True,
            status_code=301,
            redirected_status_code=200,
            links={
                "internal": [
                    {"href": "https://example.com/docs/intro/"},
                    {"href": "https://example.com/docs/missing"},
                    {"href": "https://example.com/docs/guide"},
                ],
                "external": [],
            },
        ),
        "https://example.com/docs/missing": CrawlResult(
            url="https://example.com/docs/missing",
            html=_page("404"),
            success=True,
            status_code=404,
            links={"internal": [{"href": "https://example.com/docs/from-404"}], "external": []},
        ),
        "https://example.com/docs/guide": CrawlResult(
            url="https://example.com/docs/guide",
            html=_page("Guide"),
            success=True,
            status_code=200,
            links={"internal": [{"href": "https://example.com/docs/next"}], "external": []},
        ),
        "https://example.com/docs/next": CrawlResult(
            url="https://example.com/docs/next",
            html=_page("Next"),
            success=True,
            status_code=200,
            links={"internal": [], "external": []},
        ),
    }

    class StreamingFakeCrawler:
        def __init__(self) -> None:
            self.requested_batches: list[list[str]] = []

        async def arun_many(self, urls: list[str], config: Any = None):
            self.requested_batches.append(list(urls))

            async def gen():
                for u in urls:
                    yield pages_by_url[u]

            return gen()

    progress_events: list[tuple[str, int]] = []
    config = CrawlConfig(url="https://example.com/docs/intro", output_dir=tmp_path / "out", max_pages=3)
    strategy = _link_following_bfs_strategy_cls()(
        max_depth=2,
        max_pages=3,
        filter_chain=build_filter_chain(config),
        on_page_fetched=lambda res, count: progress_events.append((res.redirected_url or res.url, count)),
    )
    fake_crawler = StreamingFakeCrawler()

    results = await strategy._arun_batch("https://example.com/docs/intro", fake_crawler, CrawlerRunConfig())

    assert fake_crawler.requested_batches == [
        ["https://example.com/docs/intro"],
        ["https://example.com/docs/missing", "https://example.com/docs/guide"],
        ["https://example.com/docs/next"],
    ]
    assert [r.url for r in results] == [
        "https://example.com/docs/intro",
        "https://example.com/docs/missing",
        "https://example.com/docs/guide",
        "https://example.com/docs/next",
    ]
    assert progress_events == [
        ("https://example.com/docs/intro/", 1),
        ("https://example.com/docs/missing", 1),
        ("https://example.com/docs/guide", 2),
        ("https://example.com/docs/next", 3),
    ]


async def test_bfs_strategy_discovers_links_from_404_seed_directory_page(tmp_path: Path):
    from crawl4ai import CrawlerRunConfig

    pages_by_url = {
        "https://example.com/docs/advanced/": CrawlResult(
            url="https://example.com/docs/advanced/",
            html=_page("404 with sidebar"),
            success=True,
            status_code=404,
            links={
                "internal": [
                    {"href": "https://example.com/docs/advanced/overview"},
                    {"href": "https://example.com/docs/advanced/broken"},
                ],
                "external": [],
            },
        ),
        "https://example.com/docs/advanced/overview": CrawlResult(
            url="https://example.com/docs/advanced/overview",
            html=_page("Overview"),
            success=True,
            status_code=200,
            links={"internal": [], "external": []},
        ),
        "https://example.com/docs/advanced/broken": CrawlResult(
            url="https://example.com/docs/advanced/broken",
            html=_page("Broken"),
            success=True,
            status_code=404,
            links={"internal": [{"href": "https://example.com/docs/advanced/from-broken"}], "external": []},
        ),
    }

    class FakeSectionCrawler:
        async def arun_many(self, urls: list[str], config: Any = None):
            return [pages_by_url[u] for u in urls]

    config = CrawlConfig(url="https://example.com/docs/advanced/", output_dir=tmp_path / "out", max_pages=5)
    strategy = _link_following_bfs_strategy_cls()(
        max_depth=2,
        max_pages=5,
        filter_chain=build_filter_chain(config),
    )

    results = await strategy._arun_batch("https://example.com/docs/advanced/", FakeSectionCrawler(), CrawlerRunConfig())

    assert [r.url for r in results] == [
        "https://example.com/docs/advanced/",
        "https://example.com/docs/advanced/overview",
        "https://example.com/docs/advanced/broken",
    ]


async def test_bfs_strategy_restores_url_order_keeps_truncated_links_and_excludes_out_of_scope_redirects(
    tmp_path: Path,
):
    from crawl4ai import CrawlerRunConfig

    pages_by_url = {
        "https://example.com/docs/": CrawlResult(
            url="https://example.com/docs/",
            html=_page("Docs"),
            success=True,
            status_code=200,
            links={
                "internal": [
                    {"href": "https://example.com/docs/first"},
                    {"href": "https://example.com/docs/out-redirect"},
                    {"href": "https://example.com/docs/deferred"},
                ],
                "external": [],
            },
        ),
        "https://example.com/docs/first": CrawlResult(
            url="https://example.com/docs/first",
            html=_page("First"),
            success=True,
            status_code=200,
            links={"internal": [{"href": "https://example.com/docs/deferred"}], "external": []},
        ),
        "https://example.com/docs/out-redirect": CrawlResult(
            url="https://example.com/docs/out-redirect",
            redirected_url="https://example.com/login",
            html=_page("Login"),
            success=True,
            status_code=302,
            redirected_status_code=200,
            links={"internal": [{"href": "https://example.com/docs/from-login"}], "external": []},
        ),
        "https://example.com/docs/deferred": CrawlResult(
            url="https://example.com/docs/deferred",
            html=_page("Deferred"),
            success=True,
            status_code=200,
            links={"internal": [], "external": []},
        ),
    }

    class OutOfOrderStreamingCrawler:
        async def arun_many(self, urls: list[str], config: Any = None):
            async def gen():
                # Emit in reverse order to simulate concurrent completions finishing out of order.
                for u in reversed(urls):
                    yield pages_by_url[u]

            return gen()

    progress_events: list[tuple[str, int, bool]] = []
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", max_pages=3)
    strategy = _link_following_bfs_strategy_cls()(
        max_depth=3,
        max_pages=3,
        filter_chain=build_filter_chain(config),
        on_page_fetched=lambda res, count: progress_events.append(
            (res.redirected_url or res.url, count, bool((res.metadata or {}).get("out_of_scope")))
        ),
    )

    results = await strategy._arun_batch("https://example.com/docs/", OutOfOrderStreamingCrawler(), CrawlerRunConfig())

    # Results are restored to BFS URL order despite reverse streaming completion,
    # the out-of-scope redirect does not consume a max_pages slot or spawn links,
    # and `/docs/deferred` (truncated at depth 0) remains discoverable at depth 1.
    assert [r.url for r in results] == [
        "https://example.com/docs/",
        "https://example.com/docs/first",
        "https://example.com/docs/out-redirect",
        "https://example.com/docs/deferred",
    ]
    assert progress_events == [
        ("https://example.com/docs/", 1, False),
        ("https://example.com/login", 1, True),
        ("https://example.com/docs/first", 2, False),
        ("https://example.com/docs/deferred", 3, False),
    ]


async def test_crawl_site_invokes_on_progress_fallback_when_crawler_bypasses_strategy(tmp_path: Path):
    fake_results = [
        CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True, status_code=200),
        CrawlResult(url="https://example.com/docs/missing", html=_page("404"), success=True, status_code=404),
        CrawlResult(url="https://example.com/docs/guide", html=_page("Guide"), success=True, status_code=200),
    ]
    progress_events: list[tuple[str, int]] = []
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    await crawl_site(
        config,
        crawler=_FakeCrawler(fake_results),
        on_progress=lambda res, count: progress_events.append((res.url, count)),
    )

    assert progress_events == [
        ("https://example.com/docs/", 1),
        ("https://example.com/docs/missing", 1),
        ("https://example.com/docs/guide", 2),
    ]


@pytest.mark.parametrize(
    ("include_patterns", "expected"),
    [
        ([], False),
        (["https://example.com/api/**"], False),
        (["https://api.example.com/v1/**"], True),
    ],
)
async def test_crawl_site_enables_external_links_only_when_include_adds_another_host(
    tmp_path: Path, include_patterns: list[str], expected: bool
):
    fake_crawler = _FakeCrawler([CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)])
    config = CrawlConfig(
        url="https://example.com/docs/",
        output_dir=tmp_path / "out",
        include_patterns=include_patterns,
    )

    await crawl_site(config, crawler=fake_crawler)

    assert fake_crawler.run_config.deep_crawl_strategy.include_external is expected


@pytest.mark.parametrize("respect_robots", [False, True])
async def test_crawl_site_checks_robots_txt_only_on_request(tmp_path: Path, respect_robots: bool):
    fake_crawler = _FakeCrawler([CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)])
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", respect_robots=respect_robots)

    await crawl_site(config, crawler=fake_crawler)

    assert fake_crawler.run_config.check_robots_txt is respect_robots


async def test_crawl_site_disables_image_loading_in_browser_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured: list[Any] = []

    class FakeBrowserCrawler(_FakeCrawler):
        async def __aenter__(self) -> FakeBrowserCrawler:
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    results = [CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)]

    def fake_crawler_factory(config: Any) -> FakeBrowserCrawler:
        captured.append(config)
        return FakeBrowserCrawler(results)

    monkeypatch.setattr("crwl2md.crawler._create_browser_crawler", fake_crawler_factory)
    monkeypatch.setenv("CRAWL4AI_NO_CLOUD_NOTICE", "1")
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    await crawl_site(config)

    assert len(captured) == 1
    assert captured[0].headless is True
    assert captured[0].text_mode is True
    assert "Chrome/" in captured[0].user_agent
    assert "HeadlessChrome" not in captured[0].user_agent
    assert "Chrome/116.0.0.0" not in captured[0].user_agent


@pytest.mark.parametrize(("preset", "expected"), [(None, "1"), ("0", "0")])
async def test_crawl_site_hides_crawl4ai_banner_unless_user_set_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preset: str | None, expected: str
):
    class FakeBrowserCrawler(_FakeCrawler):
        async def __aenter__(self) -> FakeBrowserCrawler:
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    results = [CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)]
    monkeypatch.setattr("crwl2md.crawler._create_browser_crawler", lambda config: FakeBrowserCrawler(results))
    # setenv first so that monkeypatch restores the original state even though crawl_site sets the variable.
    monkeypatch.setenv("CRAWL4AI_NO_CLOUD_NOTICE", preset or "")
    if preset is None:
        monkeypatch.delenv("CRAWL4AI_NO_CLOUD_NOTICE")
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    await crawl_site(config)

    assert os.environ["CRAWL4AI_NO_CLOUD_NOTICE"] == expected


def _fail_browser_launch(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    class UnlaunchableCrawler:
        async def __aenter__(self) -> UnlaunchableCrawler:
            raise PlaywrightError(message)

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr("crwl2md.crawler._create_browser_crawler", lambda config: UnlaunchableCrawler())
    monkeypatch.setenv("CRAWL4AI_NO_CLOUD_NOTICE", "1")


async def test_crawl_site_explains_how_to_install_missing_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _fail_browser_launch(monkeypatch, "BrowserType.launch: Executable doesn't exist at C:\\ms-playwright\\chrome.exe")
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    with pytest.raises(BrowserNotInstalledError, match="crwl2md setup"):
        await crawl_site(config)


@pytest.mark.parametrize(
    "error_message",
    [
        "BrowserType.launch: Host system is missing dependencies to run browsers.",
        "BrowserType.launch: chrome-headless-shell: error while loading shared libraries: libnss3.so",
    ],
)
async def test_crawl_site_explains_how_to_install_missing_system_libraries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_message: str
):
    _fail_browser_launch(monkeypatch, error_message)
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    with pytest.raises(BrowserNotInstalledError, match="crwl2md setup --with-deps"):
        await crawl_site(config)


async def test_crawl_site_propagates_other_browser_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _fail_browser_launch(monkeypatch, "BrowserType.launch: Target page, context or browser has been closed")
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    with pytest.raises(PlaywrightError, match="has been closed"):
        await crawl_site(config)


@pytest.mark.parametrize(
    ("with_deps", "expected_args"),
    [
        (False, ["install", "chromium"]),
        (True, ["install", "--with-deps", "chromium"]),
    ],
)
def test_install_browser_downloads_chromium_with_this_environments_playwright(
    monkeypatch: pytest.MonkeyPatch, with_deps: bool, expected_args: list[str]
):
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    install_browser(with_deps=with_deps)

    assert commands == [[sys.executable, "-m", "playwright", *expected_args]]


def test_install_browser_reports_failed_download(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(subprocess, "run", lambda command, **_: subprocess.CompletedProcess(command, returncode=1))

    with pytest.raises(RuntimeError, match="Browser download failed"):
        install_browser()


async def test_crawl_site_defaults_to_unlimited_depth(tmp_path: Path):
    fake_crawler = _FakeCrawler([CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)])
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out")

    await crawl_site(config, crawler=fake_crawler)

    assert config.max_depth is None
    assert fake_crawler.run_config.deep_crawl_strategy.max_depth == sys.maxsize


async def test_crawl_site_reports_unfetched_in_scope_links_when_hit_max_pages(tmp_path: Path):
    fake_results = [
        CrawlResult(
            url="https://example.com/docs/",
            html=_page("Docs"),
            success=True,
            metadata={"depth": 0},
            links={
                "internal": [
                    {"href": "https://example.com/docs/a"},
                    {"href": "https://example.com/docs/b"},
                    {"href": "https://example.com/docs/b#section"},
                    {"href": "https://example.com/docs/c"},
                    {"href": "https://example.com/blog/out-of-scope"},
                    {"href": "https://example.com/docs/file.pdf"},
                ],
                "external": [{"href": "https://other.example.org/docs/x"}],
            },
        ),
        CrawlResult(
            url="https://example.com/docs/a",
            html=_page("A"),
            success=True,
            metadata={"depth": 1},
            links={"internal": [], "external": []},
        ),
    ]
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", max_pages=2)

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.unfetched_in_scope_links == 2
    assert summary.hit_max_pages is True
    assert summary.hit_max_depth is False


async def test_crawl_site_reports_unfetched_in_scope_links_when_hit_max_depth(tmp_path: Path):
    fake_results = [
        CrawlResult(
            url="https://example.com/docs/",
            html=_page("Docs"),
            success=True,
            metadata={"depth": 0},
            links={"internal": [{"href": "/docs/child"}], "external": []},
        ),
    ]
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", max_depth=0, max_pages=10)

    summary = await crawl_site(config, crawler=_FakeCrawler(fake_results))

    assert summary.unfetched_in_scope_links == 1
    assert summary.hit_max_pages is False
    assert summary.hit_max_depth is True


async def test_crawl_site_passes_pacing_options_to_crawl4ai(tmp_path: Path):
    fake_crawler = _FakeCrawler([CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)])
    config = CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", delay=2.0, concurrency=1)

    await crawl_site(config, crawler=fake_crawler)

    assert (fake_crawler.run_config.mean_delay, fake_crawler.run_config.semaphore_count) == (2.0, 1)


def test_crawl_site_sync_runs_crawl_without_event_loop(tmp_path: Path):
    fake_crawler = _FakeCrawler(
        [
            CrawlResultContainer(
                CrawlResult(url="https://docs.elgato.com/streamdeck/cli/intro", html=_page("Intro"), success=True)
            )
        ]
    )
    out_dir = tmp_path / "cli_out"
    config = CrawlConfig(
        url="https://docs.elgato.com/streamdeck/cli/intro",
        output_dir=out_dir,
        include_patterns=["https://docs.elgato.com/streamdeck/cli/**"],
        frontmatter_fields=["title", "timestamp"],
    )

    summary = crawl_site_sync(config, crawler=fake_crawler)

    assert summary.page_count == 1
    assert (out_dir / "index.md").is_file()
    intro_text = (out_dir / "intro.md").read_text(encoding="utf-8")
    assert 'title: "Intro"' in intro_text
    assert "timestamp: " in intro_text
    assert "description:" not in intro_text


async def test_convert_single_url_resolves_relative_links_to_absolute_urls():
    html = _page("Page", '<p>See <a href="/docs/next">next</a> and <a href="other.html#x">other</a>.</p>')
    fake_crawler = _FakeCrawler(
        [
            CrawlResult(
                url="https://example.com/old",
                redirected_url="https://example.com/docs/page",
                html=html,
                success=True,
                status_code=200,
            )
        ]
    )

    md = await convert_single("https://example.com/old", frontmatter_fields=["source"], crawler=fake_crawler)

    assert "[next](https://example.com/docs/next)" in md
    assert "[other](https://example.com/docs/other.html#x)" in md
    assert 'source: "https://example.com/docs/page"' in md
    assert fake_crawler.run_config.wait_for.startswith("js:")


async def test_convert_single_url_honors_base_href_for_links_and_images():
    html = (
        '<html><head><base href="https://cdn.example.com/v2/"></head>'
        '<body><main><h1>Page</h1><p><a href="guide.html">Guide</a> <img src="img/a.png" alt="A"></p></main></body></html>'
    )
    fake_crawler = _FakeCrawler(
        [CrawlResult(url="https://example.com/docs/page", html=html, success=True, status_code=200)]
    )

    md = await convert_single("https://example.com/docs/page", frontmatter_fields=["source"], crawler=fake_crawler)

    assert "[Guide](https://cdn.example.com/v2/guide.html)" in md
    assert '<img src="https://cdn.example.com/v2/img/a.png" alt="A">' in md
    assert 'source: "https://example.com/docs/page"' in md


async def test_convert_single_url_raises_on_http_error_or_empty_page():
    http_404 = _FakeCrawler(
        [CrawlResult(url="https://example.com/missing", html=_page("Not Found"), success=True, status_code=404)]
    )
    redirected_404 = _FakeCrawler(
        [
            CrawlResult(
                url="https://example.com/old",
                redirected_url="https://example.com/missing",
                html=_page("Not Found"),
                success=True,
                status_code=302,
                redirected_status_code=404,
            )
        ]
    )
    empty_page = _FakeCrawler(
        [
            CrawlResult(
                url="https://example.com/empty",
                html="<html><body><main></main></body></html>",
                success=True,
                status_code=200,
            )
        ]
    )

    with pytest.raises(RuntimeError, match="HTTP 404"):
        await convert_single("https://example.com/missing", crawler=http_404)
    with pytest.raises(RuntimeError, match="HTTP 404"):
        await convert_single("https://example.com/old", crawler=redirected_404)
    with pytest.raises(RuntimeError, match="Empty page content"):
        await convert_single("https://example.com/empty", crawler=empty_page)


def test_convert_single_sync_runs_without_event_loop(tmp_path: Path):
    html_file = tmp_path / "page.html"
    html_file.write_text(_page("Local"), encoding="utf-8")

    md = convert_single_sync(html_file)

    assert md.startswith("# Local\n")


async def test_convert_single_local_file_detects_non_utf8_encoding(tmp_path: Path):
    html_file = tmp_path / "sjis.html"
    html = '<html><head><meta charset="shift_jis"></head><body><main><h1>日本語の見出し</h1></main></body></html>'
    html_file.write_bytes(html.encode("shift_jis"))

    md = await convert_single(str(html_file))

    assert md == "# 日本語の見出し\n"


async def test_convert_single_accepts_path_object(tmp_path: Path):
    html_file = tmp_path / "page.html"
    html_file.write_text(_page("Local"), encoding="utf-8")

    md = await convert_single(html_file)

    assert md.startswith("# Local\n")


async def test_convert_single_accepts_file_uri(tmp_path: Path):
    html_file = tmp_path / "my page.html"
    html_file.write_text(_page("Local"), encoding="utf-8")

    md = await convert_single(html_file.as_uri())

    assert md.startswith("# Local\n")


async def test_convert_single_local_file_omits_frontmatter_without_values(tmp_path: Path):
    html_file = tmp_path / "page.html"
    html_file.write_text(_page("Local"), encoding="utf-8")

    md = await convert_single(str(html_file), frontmatter_fields=["source"])

    assert md.startswith("# Local\n")


async def test_crawl_site_forwards_auth_stealth_proxy_and_dynamic_page_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured_browser_configs: list[Any] = []
    captured_run_configs: list[Any] = []

    class FakeBrowserCrawler(_FakeCrawler):
        async def __aenter__(self) -> FakeBrowserCrawler:
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

        async def arun(
            self, url: str, config: Any = None
        ) -> list[CrawlResult] | list[CrawlResultContainer[CrawlResult]]:
            captured_run_configs.append(config)
            return await super().arun(url, config=config)

    state_file = tmp_path / "storage_state.json"
    state_file.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    results = [CrawlResult(url="https://example.com/docs/", html=_page("Docs"), success=True)]

    def fake_crawler_factory(browser_config: Any) -> FakeBrowserCrawler:
        captured_browser_configs.append(browser_config)
        return FakeBrowserCrawler(results)

    monkeypatch.setattr("crwl2md.crawler._create_browser_crawler", fake_crawler_factory)
    config = CrawlConfig(
        url="https://example.com/docs/",
        output_dir=tmp_path / "out",
        headers=parse_headers(["Authorization: Bearer secret", "Accept-Language: ja"]),
        storage_state=state_file,
        proxy="http://user:pass@proxy.example.com:8080",
        stealth=True,
        wait_for="css:.ready",
        scan_full_page=True,
        flatten_shadow_dom=True,
    )

    await crawl_site(config)

    b_cfg = captured_browser_configs[0]
    r_cfg = captured_run_configs[0]
    assert b_cfg.headers["Authorization"] == "Bearer secret"
    assert b_cfg.headers["Accept-Language"] == "ja"
    assert b_cfg.storage_state == str(state_file)
    assert b_cfg.headless is True
    assert b_cfg.enable_stealth is True
    assert b_cfg.text_mode is False
    assert b_cfg.proxy_config.server == "http://proxy.example.com:8080"
    assert b_cfg.proxy_config.username == "user"
    assert r_cfg.proxy_config.server == "http://proxy.example.com:8080"
    assert r_cfg.wait_until == "load"
    assert r_cfg.wait_for == "css:.ready"
    assert r_cfg.wait_for_timeout == 15000
    assert r_cfg.scan_full_page is True
    assert r_cfg.flatten_shadow_dom is True
    assert r_cfg.simulate_user is True
    assert r_cfg.override_navigator is True


async def test_convert_single_forwards_user_data_dir_to_persistent_browser_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured_browser_configs: list[Any] = []
    captured_run_configs: list[Any] = []
    profile_dir = tmp_path / "chrome-profile"
    profile_dir.mkdir()

    class FakeBrowserCrawler(_FakeCrawler):
        async def __aenter__(self) -> FakeBrowserCrawler:
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

        async def arun(
            self, url: str, config: Any = None
        ) -> list[CrawlResult] | list[CrawlResultContainer[CrawlResult]]:
            captured_run_configs.append(config)
            return await super().arun(url, config=config)

    results = [CrawlResult(url="https://example.com/docs/page", html=_page("Page"), success=True, status_code=200)]
    monkeypatch.setattr(
        "crwl2md.crawler._create_browser_crawler",
        lambda cfg: (captured_browser_configs.append(cfg), FakeBrowserCrawler(results))[1],
    )

    md = await convert_single(
        "https://example.com/docs/page",
        user_data_dir=profile_dir,
        headed=True,
        wait_for=".ready",
        wait_for_timeout=30.0,
    )

    assert md.startswith("# Page\n")
    assert captured_browser_configs[0].use_persistent_context is True
    assert captured_browser_configs[0].user_data_dir == str(profile_dir)
    assert captured_browser_configs[0].headless is False
    assert captured_browser_configs[0].text_mode is True
    assert captured_run_configs[0].wait_for == ".ready"
    assert captured_run_configs[0].wait_for_timeout == 30000


def test_build_proxy_config_parses_all_supported_formats():
    from crwl2md.crawler import _build_proxy_config

    with_user_only = _build_proxy_config("http://user@proxy.example.com:8080")
    with_at_password = _build_proxy_config("http://user:p@ss@proxy.example.com:8080")
    ipv6_proxy = _build_proxy_config("socks5://user:pass@[::1]:1080")
    colon_proxy = _build_proxy_config("127.0.0.1:8080:alice:secret")

    assert (with_user_only.server, with_user_only.username, with_user_only.password) == (
        "http://proxy.example.com:8080",
        "user",
        None,
    )
    assert (with_at_password.server, with_at_password.username, with_at_password.password) == (
        "http://proxy.example.com:8080",
        "user",
        "p@ss",
    )
    assert (ipv6_proxy.server, ipv6_proxy.username, ipv6_proxy.password) == (
        "socks5://[::1]:1080",
        "user",
        "pass",
    )
    assert (colon_proxy.server, colon_proxy.username, colon_proxy.password) == (
        "http://127.0.0.1:8080",
        "alice",
        "secret",
    )


def test_crawl_config_validates_headers_proxy_and_storage_options(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid HTTP header"):
        parse_headers(["MissingColon"])
    with pytest.raises(ValueError, match="must not be empty"):
        CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", headers={" ": "val"})
    with pytest.raises(ValueError, match="Invalid proxy"):
        CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", proxy="bad-proxy")
    with pytest.raises(ValueError, match="Invalid proxy port"):
        CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", proxy="http://host:abc")
    with pytest.raises(ValueError, match="Invalid proxy port"):
        CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", proxy="http://host:99999")
    with pytest.raises(ValueError, match="Invalid proxy port"):
        CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", proxy="127.0.0.1:99999")
    with pytest.raises(ValueError) as exc_info:
        CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", proxy="http://user:s3cr3t@:8080")
    assert "s3cr3t" not in str(exc_info.value)
    with pytest.raises(ValueError, match="Cannot specify both"):
        CrawlConfig(
            url="https://example.com/docs/",
            output_dir=tmp_path / "out",
            storage_state=state_file,
            user_data_dir=tmp_path / "profile",
        )
    with pytest.raises(FileNotFoundError, match="Storage state file not found"):
        CrawlConfig(
            url="https://example.com/docs/", output_dir=tmp_path / "out", storage_state=tmp_path / "missing.json"
        )
    with pytest.raises(ValueError, match="not a directory"):
        CrawlConfig(url="https://example.com/docs/", output_dir=tmp_path / "out", user_data_dir=not_a_dir)


async def test_convert_single_rejects_blank_wait_for(tmp_path: Path):
    html_file = tmp_path / "sample.html"
    html_file.write_text("<html><body><main><h1>Hi</h1></main></body></html>", encoding="utf-8")

    with pytest.raises(ValueError, match="wait_for must not be empty"):
        await convert_single(str(html_file), wait_for="   ")
    with pytest.raises(ValueError, match="wait_for_timeout must be greater than 0"):
        await convert_single(str(html_file), wait_for_timeout=0)


async def test_shadow_dom_strategy_replaces_crawl4ai_serializer_and_escapes_cleanly(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    from crawl4ai import BrowserConfig, CrawlerRunConfig
    from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
    from crawl4ai.models import AsyncCrawlResponse

    class FakeContext:
        def __init__(self) -> None:
            self.init_scripts: list[str] = []

        async def add_init_script(self, script: str) -> None:
            self.init_scripts.append(script)

    class FakeAdapter:
        def __init__(self, responses: dict[str, Any]) -> None:
            self.responses = responses
            self.calls: list[tuple[str, str]] = []

        async def evaluate(self, page: Any, expression: str, _arg: Any = None) -> Any:
            self.calls.append((page, expression))
            outcome = self.responses[page]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    seen_configs: list[CrawlerRunConfig] = []
    shared_context = FakeContext()

    async def fake_super_crawl(self: Any, url: str, config: Any = None, **_kwargs: Any) -> AsyncCrawlResponse:
        seen_configs.append(config)
        await self.execute_hook("on_page_context_created", url, context=shared_context, config=config)
        # Interleave concurrent tasks to verify ContextVar isolation across simultaneous crawls.
        await asyncio.sleep(0)
        await self.execute_hook(
            "before_return_html", page=url, html=f"<raw>{url}</raw>", context=shared_context, config=config
        )
        return AsyncCrawlResponse(html=f"<raw>{url}</raw>", response_headers={}, status_code=200)

    monkeypatch.setattr(AsyncPlaywrightCrawlerStrategy, "crawl", fake_super_crawl)
    adapter = FakeAdapter(
        {
            "https://example.com/shadow": "<!DOCTYPE html><html><body><code>&lt;button&gt;</code></body></html>",
            "https://example.com/plain": None,
            "https://example.com/error": RuntimeError("detached frame"),
        }
    )
    strategy = _shadow_dom_crawler_strategy_cls()(browser_config=BrowserConfig(), browser_adapter=adapter)
    flat_cfg = CrawlerRunConfig(flatten_shadow_dom=True)
    off_cfg = CrawlerRunConfig(flatten_shadow_dom=False)

    res_shadow, res_plain, res_error, res_off = await asyncio.gather(
        strategy.crawl("https://example.com/shadow", config=flat_cfg),
        strategy.crawl("https://example.com/plain", config=flat_cfg),
        strategy.crawl("https://example.com/error", config=flat_cfg),
        strategy.crawl("https://example.com/off", config=off_cfg),
    )

    assert all(cfg.flatten_shadow_dom is False for cfg in seen_configs)
    assert shared_context.init_scripts == [_FORCE_OPEN_SHADOW_DOM_JS]
    assert res_shadow.html == "<!DOCTYPE html><html><body><code>&lt;button&gt;</code></body></html>"
    assert res_plain.html == "<raw>https://example.com/plain</raw>"
    assert res_error.html == "<raw>https://example.com/error</raw>"
    assert res_off.html == "<raw>https://example.com/off</raw>"
    assert sorted(page for page, expr in adapter.calls if expr == _FLATTEN_SHADOW_DOM_JS) == [
        "https://example.com/error",
        "https://example.com/plain",
        "https://example.com/shadow",
    ]


def test_create_browser_crawler_wires_shadow_dom_strategy_and_shared_logger():
    from crawl4ai import BrowserConfig

    crawler = _create_browser_crawler(BrowserConfig(verbose=False))

    assert isinstance(crawler.crawler_strategy, _shadow_dom_crawler_strategy_cls())
    assert crawler.crawler_strategy.logger is crawler.logger
    assert crawler.crawler_strategy.browser_manager.logger is crawler.logger
