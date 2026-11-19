from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import web2md
from web2md import CrawlConfig, CrawlSummary, FailedPage
from web2md.cli import main

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


def test_cli_crawl_prints_summary_with_failed_and_skipped_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    received: list[CrawlConfig] = []

    async def fake_crawl_site(config: CrawlConfig) -> CrawlSummary:
        received.append(config)
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

    monkeypatch.setattr("web2md.cli.crawl_site", fake_crawl_site)

    exit_code = main(
        [
            "crawl",
            "https://example.com/docs/",
            *("-o", str(tmp_path)),
            *("--max-depth", "3"),
            *("--include", "/docs/**"),
            "--respect-robots",
            *("--delay", "1.5"),
            *("--concurrency", "2"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (received[0].max_depth, received[0].include_patterns, received[0].respect_robots) == (3, ["/docs/**"], True)
    assert (received[0].delay, received[0].concurrency) == (1.5, 2)
    assert "Crawled 2 pages and generated 1 index files" in captured.out
    assert "Crawl scope: /docs/**" in captured.err
    assert "  - https://example.com/docs/gone: HTTP 404" in captured.err
    assert "  - https://example.com/login" in captured.err
    assert "Warning: the seed URL was redirected to https://www.example.com/docs/" in captured.err


def test_cli_crawl_reports_invalid_regex_pattern(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    exit_code = main(["crawl", "https://example.com/docs/", "-o", str(tmp_path), "--include", "^("])

    assert exit_code == 1
    assert "\nError: " in capsys.readouterr().err


@pytest.mark.parametrize(
    "option", [["--max-depth", "-1"], ["--max-pages", "0"], ["--delay", "-0.5"], ["--concurrency", "0"]]
)
def test_cli_crawl_rejects_out_of_range_limits(tmp_path: Path, option: list[str], capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        main(["crawl", "https://example.com/docs/", "-o", str(tmp_path), *option])

    assert exc_info.value.code == 2
    assert f"argument {option[0]}: must be" in capsys.readouterr().err


def test_cli_setup_downloads_browser(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    calls: list[str] = []
    monkeypatch.setattr("web2md.cli.install_browser", lambda: calls.append("install"))

    exit_code = main(["setup"])

    assert exit_code == 0
    assert calls == ["install"]
    assert "ready" in capsys.readouterr().out


def test_cli_setup_reports_failed_download(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    def fail() -> None:
        raise RuntimeError("Browser download failed (playwright exited with code 1).")

    monkeypatch.setattr("web2md.cli.install_browser", fail)

    exit_code = main(["setup"])

    assert exit_code == 1
    assert capsys.readouterr().err == "Error: Browser download failed (playwright exited with code 1).\n"


def test_cli_version_prints_package_version(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"web2md {web2md.__version__}"


def test_importing_package_and_cli_defers_heavy_crawler_dependencies():
    code = (
        "import sys, web2md, web2md.cli; "
        "loaded = [m for m in ('crawl4ai', 'playwright', 'httpx') if m in sys.modules]; "
        "assert not loaded, f'eagerly imported: {loaded}'"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
