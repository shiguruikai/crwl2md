---
name: crwl2md
description: Converts web pages or local HTML files to Markdown and crawls documentation sites into offline Markdown copies with index.md tables of contents using the crwl2md CLI. Use when saving online documentation locally, fetching multi-page docs, or converting HTML files to Markdown.
license: MIT
---

# crwl2md

## Prerequisites

- Check availability with `crwl2md --version`. Inside the `crwl2md` repository, run it via `uv run crwl2md`.
- If `crwl2md` is not installed, ask the user before installing it globally with `uv tool install crwl2md`.
- Fetching `http://` or `https://` URLs requires Playwright's Chromium browser (`crwl2md setup`).
- Local HTML files (`convert <path>` or `file://`) are read directly without a browser (JavaScript is not executed).

## Commands

- `crwl2md setup`: Download the Chromium browser used for fetching URLs.
- `crwl2md convert <source>`: Convert a single URL, `file://` URI, or local HTML file to Markdown. Prefer `-o <path>` for anything but short pages, then read only the parts you need.
- `crwl2md crawl <url> -o <dir>`: Crawl a website starting from `<url>` and save Markdown files and `index.md` tables of contents in `<dir>`.

## Detailed Usage and Options

Do not guess CLI flags or defaults. Run the built-in help commands to check detailed usage and all available options (such as crawl scope, page limits, rate limiting, browser rendering, authentication, and frontmatter):

```bash
crwl2md --help
crwl2md setup --help
crwl2md convert --help
crwl2md crawl --help
```

## Crawl Workflow

1. Run a small trial crawl first (for example, with `--max-pages 5`) into a temporary directory, then inspect `Crawl scope:` on stderr and check a generated Markdown file (an unfetched-links warning is expected during a trial).
2. Run the full crawl into a clean output directory (do not reuse the trial directory, because overwriting does not remove stale files).
3. Check stderr for warnings, skipped out-of-scope URLs, and failed pages. If you hit rate limits, bot blocks, missing dynamic content, authentication walls, or scope issues, check `crwl2md crawl --help` (or `crwl2md convert --help`) for the relevant options and re-run.

## Output Notes

- **Start from `index.md`**: After `crawl`, read `<dir>/index.md` first to browse the generated documentation tree.
- **File layout**: `index.md` files are generated tables of contents. A crawled page that also has child pages is saved as `overview.md` in its directory.
- **Links and images**: For `crawl`, links between crawled pages become relative `.md` paths, while external links and images become absolute URLs (images are not downloaded locally). For `convert`, relative links and images become absolute URLs for URL sources, or stay relative for local HTML files without a base URL.
- **Exit status**: For `crawl`, exit code `0` means at least one page was saved, even if some pages failed; always review stderr.
