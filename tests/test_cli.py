"""crawler および CLI モジュールのテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest
from crawl4ai import CrawlResult
from crawl4ai.models import CrawlResultContainer

from web2md import CrawlConfig, crawl_site, crawl_site_sync
from web2md.cli import main
from web2md.crawler import build_filter_chain, compile_url_pattern


class _FakeCrawler:
    """ネットワーク通信なしで crawl_site をテストするためのフェイククローラー。"""

    def __init__(self, results: list[CrawlResult] | list[CrawlResultContainer[CrawlResult]]) -> None:
        self._results = results

    async def arun(
        self, url: str, config: object = None
    ) -> list[CrawlResult] | list[CrawlResultContainer[CrawlResult]]:
        return self._results


def test_cli_convert_local_file_to_output(tmp_path: Path):
    # Arrange
    html_file = tmp_path / "sample.html"
    html_file.write_text(
        "<html><head><title>Local</title></head><body><main><h1>Hello</h1><p>World</p></main></body></html>",
        encoding="utf-8",
    )
    out_file = tmp_path / "out.md"

    # Act
    exit_code = main(["convert", str(html_file), "-o", str(out_file), "--frontmatter"])

    # Assert
    assert exit_code == 0
    content = out_file.read_text(encoding="utf-8")
    assert 'title: "Hello"' in content
    assert "# Hello" in content
    assert "World" in content


def test_cli_convert_missing_file_returns_error(tmp_path: Path):
    # Arrange
    missing = tmp_path / "does_not_exist.html"

    # Act
    exit_code = main(["convert", str(missing)])

    # Assert
    assert exit_code == 1


@pytest.mark.asyncio
async def test_crawl_site_writes_markdown_and_toc(tmp_path: Path):
    # Arrange
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
    start_html = """
    <html><head><title>Start</title></head><body>
      <main>
        <h1>Start</h1>
        <p>Begin here and inspect <a href="../sdk/api#auth">API auth</a>.</p>
      </main>
    </body></html>
    """
    api_html = """
    <html><head><title>API</title></head><body>
      <main>
        <h1>API</h1>
        <h2 id="auth">Auth</h2>
        <p>Authentication guide.</p>
      </main>
    </body></html>
    """

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
        CrawlResult(url="https://example.com/docs/sdk/broken", html="", success=False, error_message="404"),
    ]
    fake_crawler = _FakeCrawler(fake_results)
    out_dir = tmp_path / "site_out"
    config = CrawlConfig(
        url="https://example.com/docs/sdk",
        output_dir=out_dir,
        max_depth=1,
        frontmatter=True,
    )

    # Act
    summary = await crawl_site(config, crawler=fake_crawler)

    # Assert
    assert summary.page_count == 3
    assert summary.toc_count == 1
    assert summary.failed_urls == ["https://example.com/docs/sdk/broken"]
    assert (out_dir / "index.md").is_file()
    assert (out_dir / "overview.md").is_file()
    assert (out_dir / "start.md").is_file()
    assert (out_dir / "api.md").is_file()

    overview_text = (out_dir / "overview.md").read_text(encoding="utf-8")
    assert "[Start](start.md)" in overview_text
    assert 'title: "SDK Overview"' in overview_text

    start_text = (out_dir / "start.md").read_text(encoding="utf-8")
    assert "[API auth](api.md#auth)" in start_text

    toc_text = (out_dir / "index.md").read_text(encoding="utf-8")
    assert toc_text.index("start.md") < toc_text.index("api.md")


def test_compile_url_pattern_glob_double_star():
    # Arrange
    pattern = compile_url_pattern("https://docs.elgato.com/streamdeck/cli/**")
    path_pattern = compile_url_pattern("/streamdeck/cli/**")
    suffix_pattern = compile_url_pattern("*.pdf")

    # Act / Assert
    assert pattern.search("https://docs.elgato.com/streamdeck/cli")
    assert pattern.search("https://docs.elgato.com/streamdeck/cli/")
    assert pattern.search("https://docs.elgato.com/streamdeck/cli/intro")
    assert pattern.search("https://docs.elgato.com/streamdeck/cli/commands/create")
    assert not pattern.search("https://docs.elgato.com/streamdeck/sdk/intro")
    assert not pattern.search("https://docs.elgato.com/streamdeck/cli-other/intro")

    assert path_pattern.search("https://docs.elgato.com/streamdeck/cli/commands/create")
    assert not path_pattern.search("https://docs.elgato.com/streamdeck/sdk/intro")

    assert suffix_pattern.search("https://example.com/files/manual.pdf")
    assert not suffix_pattern.search("https://example.com/files/manual.html")


@pytest.mark.asyncio
async def test_build_filter_chain_uses_include_patterns(tmp_path: Path):
    # Arrange
    config = CrawlConfig(
        url="https://docs.elgato.com/streamdeck/cli/commands/create",
        output_dir=tmp_path / "out",
        include_patterns=["https://docs.elgato.com/streamdeck/cli/**"],
    )
    chain = build_filter_chain(config)

    # Act / Assert
    assert await chain.apply("https://docs.elgato.com/streamdeck/cli/intro")
    assert await chain.apply("https://docs.elgato.com/streamdeck/cli/commands/pack")
    assert not await chain.apply("https://docs.elgato.com/streamdeck/sdk/actions")
    assert not await chain.apply("https://docs.elgato.com/streamdeck/cli/asset.js")


def test_python_api_crawl_site_sync_with_direct_args(tmp_path: Path):
    # Arrange
    html = "<html><body><main><h1>Intro</h1><p>Welcome.</p></main></body></html>"
    fake_crawler = _FakeCrawler(
        [CrawlResultContainer(CrawlResult(url="https://docs.elgato.com/streamdeck/cli/intro", html=html, success=True))]
    )
    out_dir = tmp_path / "cli_out"

    # Act
    summary = crawl_site_sync(
        "https://docs.elgato.com/streamdeck/cli/intro",
        out_dir,
        include_patterns=["https://docs.elgato.com/streamdeck/cli/**"],
        crawler=fake_crawler,
    )

    # Assert
    assert summary.page_count == 1
    assert (out_dir / "intro.md").is_file()
    assert (out_dir / "index.md").is_file()
