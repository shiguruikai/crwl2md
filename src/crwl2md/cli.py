from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from crwl2md import __version__
from crwl2md.crawler import (
    CrawlConfig,
    CrawlSummary,
    convert_single,
    crawl_site,
    describe_crawl_scope,
    install_browser,
    validate_http_url,
)
from crwl2md.site_builder import FRONTMATTER_FIELDS, parse_frontmatter_fields


def _is_expected_cli_error(exc: BaseException) -> bool:
    if isinstance(exc, (OSError, ValueError, RuntimeError, re.error)):
        return True
    # Avoid importing playwright just to check exception types when it was never loaded.
    mod = sys.modules.get("playwright.async_api")
    err_cls = getattr(mod, "Error", None)
    return isinstance(err_cls, type) and isinstance(exc, err_cls)


def _at_least[NumberT: (int, float)](minimum: NumberT) -> Callable[[str], NumberT]:
    def parse(value: str) -> NumberT:
        number = type(minimum)(value)
        if number < minimum:
            raise argparse.ArgumentTypeError(f"must be {minimum} or greater")
        return number

    return parse


def _add_frontmatter_options(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--frontmatter",
        action="store_true",
        help="Prepend YAML frontmatter to output Markdown.",
    )
    subparser.add_argument(
        "--frontmatter-fields",
        default=None,
        help=f"Comma-separated YAML frontmatter fields ({','.join(FRONTMATTER_FIELDS)}). Enables frontmatter when set.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the `crwl2md` CLI."""
    parser = argparse.ArgumentParser(
        prog="crwl2md",
        description="Convert HTML pages or crawl documentation sites into Markdown with table of contents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert_parser = subparsers.add_parser(
        "convert",
        help="Convert a single URL or local HTML file to Markdown.",
    )
    convert_parser.add_argument("source", help="Source URL, file:// URI, or local HTML file path.")
    convert_parser.add_argument("-o", "--output", type=Path, help="Output Markdown file path (default: stdout).")
    _add_frontmatter_options(convert_parser)

    crawl_parser = subparsers.add_parser(
        "crawl",
        help="Crawl a documentation website and generate Markdown files with index.md TOCs.",
    )
    crawl_parser.add_argument("url", help="Seed URL to start crawling from.")
    crawl_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output directory for Markdown files and index.md.",
    )
    crawl_parser.add_argument(
        "--max-depth",
        type=_at_least(0),
        default=None,
        metavar="N",
        help="Maximum number of link hops from the seed page (0 = seed page only, default: unlimited).",
    )
    crawl_parser.add_argument(
        "--max-pages", type=_at_least(1), default=100, metavar="N", help="Maximum number of pages (default: 100)."
    )
    crawl_parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="URL pattern to crawl: glob or regex, repeatable. Replaces the default seed-directory scope.",
    )
    crawl_parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="URL pattern to skip: glob or regex, repeatable.",
    )
    crawl_parser.add_argument(
        "--allow-all-paths",
        action="store_true",
        help="Allow crawling any path on the seed domain instead of restricting to the seed URL's directory.",
    )
    crawl_parser.add_argument(
        "--delay",
        type=_at_least(0.0),
        default=0.1,
        metavar="SECONDS",
        help="Seconds to wait before each batch of concurrent requests (default: 0.1).",
    )
    crawl_parser.add_argument(
        "--concurrency",
        type=_at_least(1),
        default=5,
        metavar="N",
        help="Maximum number of pages fetched at the same time (default: 5).",
    )
    crawl_parser.add_argument(
        "--respect-robots",
        action="store_true",
        help="Skip pages that the site's robots.txt disallows.",
    )
    crawl_parser.add_argument(
        "--force",
        action="store_true",
        help="Allow writing into a non-empty output directory and overwriting existing files.",
    )
    _add_frontmatter_options(crawl_parser)
    crawl_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose crawler logging.")

    setup_parser = subparsers.add_parser(
        "setup",
        help="Download the headless browser used for fetching URLs (about 290 MB). Run once after installing or upgrading.",
    )
    setup_parser.add_argument(
        "--with-deps",
        action="store_true",
        help="Also install OS-level libraries required by Chromium on Linux (may prompt for sudo).",
    )

    return parser


def _summarize_top_level_dirs(files: Sequence[str]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for relpath in files:
        if relpath == "index.md" or relpath.endswith("/index.md"):
            continue
        top_dir = f"{relpath.split('/', 1)[0]}/" if "/" in relpath else "(root)"
        counts[top_dir] += 1
    if not any(name != "(root)" for name in counts):
        return []
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _format_progress_line(result: Any, pages_crawled: int, max_pages: int) -> str:
    final_url = getattr(result, "redirected_url", None) or getattr(result, "url", "")
    redirected_status = getattr(result, "redirected_status_code", None)
    status_code = redirected_status if redirected_status is not None else getattr(result, "status_code", None)
    http_error = status_code is not None and status_code >= 400
    if not getattr(result, "success", False) or http_error:
        reason = getattr(result, "error_message", None) or (f"HTTP {status_code}" if http_error else "Unknown error")
        return f"[failed] {final_url} ({reason})"
    return f"[{pages_crawled}/{max_pages}] {final_url}"


def _format_unfetched_warning(summary: CrawlSummary, config: CrawlConfig) -> str:
    count = summary.unfetched_in_scope_links
    noun = "link was" if count == 1 else "links were"
    limits: list[str] = []
    if summary.hit_max_depth and config.max_depth is not None:
        limits.append(f"--max-depth {config.max_depth}")
    if summary.hit_max_pages:
        limits.append(f"--max-pages {config.max_pages}")
    if summary.hit_max_pages and summary.hit_max_depth:
        hint = "Raise the limits or narrow the scope with --include / --exclude."
    elif summary.hit_max_pages:
        hint = "Raise --max-pages or narrow the scope with --include / --exclude."
    elif summary.hit_max_depth:
        hint = "Raise --max-depth or omit it for unlimited depth."
    else:
        hint = ""
    reason = f" (stopped at {' and '.join(limits)})" if limits else ""
    return f"Warning: {count} in-scope {noun} not fetched{reason}." + (f" {hint}" if hint else "")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `crwl2md` CLI entrypoint and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "setup":
            install_browser(with_deps=args.with_deps)
            print("The headless browser is ready.")
            return 0

        frontmatter_fields = (
            parse_frontmatter_fields(args.frontmatter_fields) if args.frontmatter_fields is not None else None
        )

        if args.command == "convert":
            markdown = asyncio.run(
                convert_single(
                    args.source,
                    frontmatter=args.frontmatter,
                    frontmatter_fields=frontmatter_fields,
                )
            )
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(markdown, encoding="utf-8", newline="\n")
                print(f"Saved Markdown to {args.output}")
            elif hasattr(sys.stdout, "buffer"):
                sys.stdout.buffer.write(markdown.encode("utf-8"))
                sys.stdout.buffer.flush()
            else:
                sys.stdout.write(markdown)
            return 0

        if args.command == "crawl":
            url = validate_http_url(args.url)
            config = CrawlConfig(
                url=url,
                output_dir=args.output,
                max_depth=args.max_depth,
                max_pages=args.max_pages,
                include_patterns=args.include,
                exclude_patterns=args.exclude,
                allow_all_paths=args.allow_all_paths,
                respect_robots=args.respect_robots,
                delay=args.delay,
                concurrency=args.concurrency,
                frontmatter=args.frontmatter or frontmatter_fields is not None,
                frontmatter_fields=frontmatter_fields,
                force=args.force,
                verbose=args.verbose,
            )
            print(f"Crawl scope: {describe_crawl_scope(config)}", file=sys.stderr)
            summary = asyncio.run(
                crawl_site(
                    config,
                    on_progress=lambda result, count: print(
                        _format_progress_line(result, count, config.max_pages),
                        file=sys.stderr,
                        flush=True,
                    ),
                )
            )
            print(
                f"Crawled {summary.page_count} pages and generated {summary.toc_count} index files in {summary.output_dir}"
            )
            if dir_counts := _summarize_top_level_dirs(summary.files):
                print("Pages by top-level directory:")
                for dir_name, count in dir_counts:
                    noun = "page" if count == 1 else "pages"
                    print(f"  - {dir_name}: {count} {noun}")
            if summary.seed_redirected_to:
                print(
                    f"Warning: the seed URL was redirected to {summary.seed_redirected_to}, outside the crawl scope, "
                    "so links on that page were not followed. Run the crawl again with that URL as the seed.",
                    file=sys.stderr,
                )
            if summary.unfetched_in_scope_links > 0:
                print(_format_unfetched_warning(summary, config), file=sys.stderr)
            if summary.skipped_urls:
                print(f"Skipped pages outside the crawl scope ({len(summary.skipped_urls)}):", file=sys.stderr)
                for url in summary.skipped_urls:
                    print(f"  - {url}", file=sys.stderr)
            if summary.failed_pages:
                print(f"Failed pages ({len(summary.failed_pages)}):", file=sys.stderr)
                for page in summary.failed_pages:
                    print(f"  - {page.url}: {page.reason}", file=sys.stderr)
            return 0

        parser.error(f"Unknown command: {args.command}")
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if not _is_expected_cli_error(exc):
            raise
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
