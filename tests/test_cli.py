from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import crwl2md
from crwl2md import CrawlConfig, CrawlSummary, FailedPage
from crwl2md.cli import main

_SAMPLE_HTML = "<html><head><title>Local</title></head><body><main><h1>Hello</h1><p>World</p></main></body></html>"


def _write_sample_html(tmp_path: Path) -> Path:
    html_file = tmp_path / "sample.html"
    html_file.write_text(_SAMPLE_HTML, encoding="utf-8")
    return html_file


def test_cli_convert_local_file_to_output(tmp_path: Path):
    html_file = _write_sample_html(tmp_path)
    out_file = tmp_path / "out.md"

    exit_code = main(["convert", str(html_file), "-o", str(out_file), "--frontmatter"])

    assert exit_code == 0
    content = out_file.read_text(encoding="utf-8")
    assert 'title: "Hello"' in content
    assert "# Hello" in content
    assert "World" in content


def test_cli_convert_local_file_with_frontmatter_fields(tmp_path: Path):
    html_file = _write_sample_html(tmp_path)
    out_file = tmp_path / "out.md"

    exit_code = main(["convert", str(html_file), "-o", str(out_file), "--frontmatter-fields", "title,timestamp"])

    assert exit_code == 0
    content = out_file.read_text(encoding="utf-8")
    assert 'title: "Hello"' in content
    assert "timestamp: " in content
    assert "description:" not in content
    assert "# Hello" in content


def test_cli_convert_writes_utf8_markdown_to_stdout(tmp_path: Path, capfdbinary: pytest.CaptureFixture[bytes]):
    html_file = tmp_path / "sample.html"
    html_file.write_text("<html><body><main><h1>見出し</h1></main></body></html>", encoding="utf-8")

    exit_code = main(["convert", str(html_file)])

    assert exit_code == 0
    assert capfdbinary.readouterr().out == "# 見出し\n".encode()


def test_cli_convert_missing_file_returns_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    missing = tmp_path / "does_not_exist.html"

    exit_code = main(["convert", str(missing)])

    assert exit_code == 1
    assert "HTML file not found" in capsys.readouterr().err


def test_cli_convert_reports_unwritable_output_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    html_file = _write_sample_html(tmp_path)

    exit_code = main(["convert", str(html_file), "-o", str(tmp_path)])

    assert exit_code == 1
    assert capsys.readouterr().err.startswith("Error: ")


def test_cli_convert_forwards_browser_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured: list[dict[str, object]] = []
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")

    async def fake_convert_single(source: object, **kwargs: object) -> str:
        captured.append({"source": source, **kwargs})
        return "# Title\n"

    monkeypatch.setattr("crwl2md.cli.convert_single", fake_convert_single)
    out_file = tmp_path / "out.md"

    exit_code = main(
        [
            "convert",
            "https://example.com/docs/intro",
            *("-o", str(out_file)),
            *("--header", "X-Token: abc"),
            *("--storage-state", str(state_file)),
            *("--proxy", "127.0.0.1:8080"),
            "--stealth",
            "--headed",
            *("--wait-for", ".content"),
            *("--wait-for-timeout", "25"),
            "--scan-full-page",
            "--flatten-shadow-dom",
        ]
    )

    assert exit_code == 0
    assert captured[0]["source"] == "https://example.com/docs/intro"
    assert captured[0]["headers"] == ["X-Token: abc"]
    assert captured[0]["storage_state"] == state_file
    assert captured[0]["proxy"] == "127.0.0.1:8080"
    assert captured[0]["stealth"] is True
    assert captured[0]["headed"] is True
    assert captured[0]["wait_for"] == ".content"
    assert captured[0]["wait_for_timeout"] == 25.0
    assert captured[0]["scan_full_page"] is True
    assert captured[0]["flatten_shadow_dom"] is True


def test_cli_crawl_formats_validation_error_cleanly_and_redacts_proxy_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    exit_code = main(["crawl", "https://example.com/docs/", "-o", str(tmp_path), "--proxy", "http://user:s3cr3t@:8080"])

    stderr = capsys.readouterr().err
    assert exit_code == 1
    assert stderr.startswith("Error: Invalid proxy:")
    assert "s3cr3t" not in stderr
    assert "errors.pydantic.dev" not in stderr


def test_cli_crawl_prints_summary_with_failed_and_skipped_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from crawl4ai import CrawlResult

    received: list[CrawlConfig] = []

    async def fake_crawl_site(config: CrawlConfig, *, on_progress: object = None) -> CrawlSummary:
        received.append(config)
        if callable(on_progress):
            on_progress(CrawlResult(url="https://example.com/docs/", html="ok", success=True, status_code=200), 1)
            on_progress(
                CrawlResult(
                    url="https://example.com/docs/gone",
                    html="",
                    success=False,
                    status_code=500,
                    error_message="Failed on navigating ACS-GOTO:\nPage.goto: net::ERR_FAILED\nCall log:\n  - navigating",
                ),
                1,
            )
            on_progress(
                CrawlResult(
                    url="https://example.com/docs/sso",
                    redirected_url="https://example.com/login",
                    html="ok",
                    success=True,
                    status_code=302,
                    redirected_status_code=200,
                    metadata={"out_of_scope": True},
                ),
                1,
            )
        return CrawlSummary(
            seed_url=config.url,
            output_dir=config.output_dir,
            page_count=2,
            toc_count=1,
            failed_pages=[FailedPage(url="https://example.com/docs/gone", status_code=404, reason="HTTP 404")],
            skipped_urls=["https://example.com/login"],
            seed_redirected_to="https://www.example.com/docs/",
            files=["a.md", "index.md", "overview.md"],
        )

    monkeypatch.setattr("crwl2md.cli.crawl_site", fake_crawl_site)

    exit_code = main(
        [
            "crawl",
            "https://example.com/docs/",
            *("-o", str(tmp_path)),
            *("--max-depth", "3"),
            *("--include", "/docs/**"),
            "--respect-robots",
            "--force",
            *("--delay", "1.5"),
            *("--concurrency", "2"),
            *("--header", "Authorization: Bearer tok"),
            *("--proxy", "127.0.0.1:8080"),
            "--stealth",
            "--headed",
            *("--wait-for", ".content"),
            *("--wait-for-timeout", "20"),
            "--scan-full-page",
            "--flatten-shadow-dom",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (received[0].max_depth, received[0].include_patterns, received[0].respect_robots, received[0].force) == (
        3,
        ["/docs/**"],
        True,
        True,
    )
    assert (received[0].delay, received[0].concurrency) == (1.5, 2)
    assert received[0].headers == {"Authorization": "Bearer tok"}
    assert received[0].proxy == "127.0.0.1:8080"
    assert (
        received[0].stealth,
        received[0].headed,
        received[0].wait_for,
        received[0].wait_for_timeout,
        received[0].scan_full_page,
        received[0].flatten_shadow_dom,
    ) == (
        True,
        True,
        ".content",
        20.0,
        True,
        True,
    )
    assert "Crawled 2 pages and generated 1 index files" in captured.out
    assert "Crawl scope: /docs/**" in captured.err
    assert "[1/100] https://example.com/docs/" in captured.err
    assert (
        "[failed] https://example.com/docs/gone (Failed on navigating ACS-GOTO: Page.goto: net::ERR_FAILED)\n"
        in captured.err
    )
    assert "Call log:" not in captured.err
    assert "[skipped] https://example.com/login (outside crawl scope)\n" in captured.err
    assert "  - https://example.com/docs/gone: HTTP 404" in captured.err
    assert "  - https://example.com/login" in captured.err
    assert "Warning: the seed URL was redirected to https://www.example.com/docs/" in captured.err


def test_cli_crawl_no_progress_disables_progress_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    received_callbacks: list[object] = []

    async def fake_crawl_site(config: CrawlConfig, *, on_progress: object = None) -> CrawlSummary:
        received_callbacks.append(on_progress)
        return CrawlSummary(
            seed_url=config.url,
            output_dir=config.output_dir,
            page_count=1,
            toc_count=1,
            failed_pages=[],
            skipped_urls=[],
            files=["index.md", "overview.md"],
        )

    monkeypatch.setattr("crwl2md.cli.crawl_site", fake_crawl_site)

    exit_code = main(["crawl", "https://example.com/docs/", "-o", str(tmp_path), "--no-progress"])

    assert exit_code == 0
    assert received_callbacks == [None]
    assert "[1/" not in capsys.readouterr().err


@pytest.mark.parametrize("bad_url", ["docs.example.com/intro", "ftp://example.com/docs", "https://"])
def test_cli_crawl_rejects_url_without_http_scheme(tmp_path: Path, bad_url: str, capsys: pytest.CaptureFixture[str]):
    exit_code = main(["crawl", bad_url, "-o", str(tmp_path)])

    stderr = capsys.readouterr().err
    assert exit_code == 1
    assert stderr.startswith("Error: Invalid URL:")
    assert "http://" in stderr
    assert "Crawl scope:" not in stderr


@pytest.mark.parametrize(
    ("extra_args", "summary_kwargs", "expected_fragment"),
    [
        (
            ["--max-pages", "10"],
            {"unfetched_in_scope_links": 5, "hit_max_pages": True},
            "Warning: 5 in-scope links were not fetched (stopped at --max-pages 10).",
        ),
        (
            ["--max-depth", "2"],
            {"unfetched_in_scope_links": 1, "hit_max_depth": True},
            "Warning: 1 in-scope link was not fetched (stopped at --max-depth 2).",
        ),
        (
            ["--max-depth", "2", "--max-pages", "10"],
            {"unfetched_in_scope_links": 7, "hit_max_depth": True, "hit_max_pages": True},
            "Warning: 7 in-scope links were not fetched (stopped at --max-depth 2 and --max-pages 10).",
        ),
    ],
)
def test_cli_crawl_warns_when_in_scope_links_were_not_fetched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra_args: list[str],
    summary_kwargs: dict[str, object],
    expected_fragment: str,
):
    async def fake_crawl_site(config: CrawlConfig, **_kwargs: object) -> CrawlSummary:
        return CrawlSummary(
            seed_url=config.url,
            output_dir=config.output_dir,
            page_count=1,
            toc_count=1,
            failed_pages=[],
            skipped_urls=[],
            files=["index.md", "overview.md"],
            **summary_kwargs,  # type: ignore[arg-type]
        )

    monkeypatch.setattr("crwl2md.cli.crawl_site", fake_crawl_site)

    exit_code = main(["crawl", "https://example.com/docs/", "-o", str(tmp_path), *extra_args])

    assert exit_code == 0
    assert expected_fragment in capsys.readouterr().err


def test_cli_crawl_prints_top_level_directory_breakdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    async def fake_crawl_site(config: CrawlConfig, **_kwargs: object) -> CrawlSummary:
        return CrawlSummary(
            seed_url=config.url,
            output_dir=config.output_dir,
            page_count=4,
            toc_count=3,
            failed_pages=[],
            skipped_urls=[],
            files=[
                "2.x/a.md",
                "2.x/b.md",
                "2.x/index.md",
                "guides/intro.md",
                "guides/index.md",
                "index.md",
                "overview.md",
            ],
        )

    monkeypatch.setattr("crwl2md.cli.crawl_site", fake_crawl_site)

    exit_code = main(["crawl", "https://example.com/docs/", "-o", str(tmp_path)])

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert "Pages by top-level directory:\n  - 2.x/: 2 pages\n  - (root): 1 page\n  - guides/: 1 page\n" in stdout


def test_cli_crawl_reports_invalid_regex_pattern(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    exit_code = main(["crawl", "https://example.com/docs/", "-o", str(tmp_path), "--include", "^("])

    assert exit_code == 1
    assert "\nError: " in capsys.readouterr().err


@pytest.mark.parametrize(
    "option",
    [
        ["--max-depth", "-1"],
        ["--max-pages", "0"],
        ["--delay", "-0.5"],
        ["--concurrency", "0"],
        ["--wait-for-timeout", "0"],
    ],
)
def test_cli_crawl_rejects_out_of_range_limits(tmp_path: Path, option: list[str], capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        main(["crawl", "https://example.com/docs/", "-o", str(tmp_path), *option])

    assert exc_info.value.code == 2
    assert f"argument {option[0]}: must be" in capsys.readouterr().err


@pytest.mark.parametrize(("argv", "expected_with_deps"), [(["setup"], False), (["setup", "--with-deps"], True)])
def test_cli_setup_downloads_browser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_with_deps: bool,
):
    calls: list[bool] = []
    monkeypatch.setattr("crwl2md.cli.install_browser", lambda *, with_deps=False: calls.append(with_deps))

    exit_code = main(argv)

    assert exit_code == 0
    assert calls == [expected_with_deps]
    assert "ready" in capsys.readouterr().out


def test_cli_setup_reports_failed_download(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    def fail(*, with_deps: bool = False) -> None:
        raise RuntimeError("Browser download failed (playwright exited with code 1).")

    monkeypatch.setattr("crwl2md.cli.install_browser", fail)

    exit_code = main(["setup"])

    assert exit_code == 1
    assert capsys.readouterr().err == "Error: Browser download failed (playwright exited with code 1).\n"


def test_cli_version_prints_package_version(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"crwl2md {crwl2md.__version__}"


def test_importing_package_and_cli_defers_heavy_crawler_dependencies():
    code = (
        "import sys, crwl2md, crwl2md.cli; "
        "loaded = [m for m in ('crawl4ai', 'playwright') if m in sys.modules]; "
        "assert not loaded, f'eagerly imported: {loaded}'"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
