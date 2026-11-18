from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx

from web2md import __version__
from web2md.crawler import CrawlConfig, convert_single, crawl_site, describe_crawl_scope
from web2md.site_builder import FRONTMATTER_FIELDS, parse_frontmatter_fields


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
    """Build the argument parser for the `web2md` CLI."""
    parser = argparse.ArgumentParser(
        prog="web2md",
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
        "--max-depth", type=_at_least(0), default=2, metavar="N", help="Maximum crawl depth (default: 2)."
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
    _add_frontmatter_options(crawl_parser)
    crawl_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose crawler logging.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `web2md` CLI entrypoint and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        frontmatter_fields = (
            parse_frontmatter_fields(args.frontmatter_fields) if args.frontmatter_fields is not None else None
        )

        if args.command == "convert":
            markdown = convert_single(
                args.source,
                frontmatter=args.frontmatter,
                frontmatter_fields=frontmatter_fields,
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
            config = CrawlConfig(
                url=args.url,
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
                verbose=args.verbose,
            )
            print(f"Crawl scope: {describe_crawl_scope(config)}", file=sys.stderr)
            summary = asyncio.run(crawl_site(config))
            print(
                f"Crawled {summary.page_count} pages and generated {summary.toc_count} index files in {summary.output_dir}"
            )
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
    except (OSError, ValueError, RuntimeError, re.error, httpx.HTTPError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
