---
name: crwl2md
description: Convert web pages or local HTML files to Markdown, or crawl a website into local Markdown files with index.md tables of contents using the crwl2md CLI.
license: MIT
---

# crwl2md

## Prerequisites

- Check availability with `crwl2md --version`. Inside the `crwl2md` repository, run it via `uv run crwl2md`.
- If `crwl2md` is not installed, ask the user before installing it globally with `uv tool install crwl2md`.
- Fetching `http://` or `https://` URLs uses Playwright's Chromium browser. Only run `crwl2md setup` if `convert` or `crawl` reports a missing browser or version mismatch (on Linux with missing OS libraries, ask the user to run `crwl2md setup --with-deps`, which may prompt for `sudo`).
- Local HTML files (`convert <path>` or `file://`) are read directly without a browser (JavaScript is not executed).

## Commands

- `crwl2md setup`: Download the Chromium browser used for fetching URLs.
- `crwl2md convert <source>`: Convert a single URL, `file://` URI, or local HTML file to Markdown. Prefer `-o <path>` for anything but short pages, then read only the parts you need.
- `crwl2md crawl <url> -o <dir>`: Crawl a website starting from `<url>` and save Markdown files and `index.md` tables of contents in `<dir>`.

## Detailed Usage and Options

Do not guess CLI flags or defaults. Check built-in help when needed:

```bash
crwl2md --help
crwl2md setup --help
crwl2md convert --help
crwl2md crawl --help
```

Key behaviors not obvious from `--help`:

- **Page limit**: `--max-pages` defaults to `100`. Raise it for larger sites or narrow the scope.
- **Scope patterns (`--include` / `--exclude`)**: Quote patterns for the shell. Globs use `*` (single segment) and `**` (multi-segment); regex requires a leading `^` or trailing `$`; plain strings without `*`, `?`, `^`, `$` match substrings.
- **Auth**: `--header` is sent on all browser requests, including third-party assets. Prefer `--storage-state` or `--user-data-dir` for authentication.

```bash
# Trial crawl into a temporary directory
crwl2md crawl https://example.com/docs/intro -o <temp-dir> --max-pages 5

# Full crawl with scope filters (glob, regex with ^/$, substring) and higher page limit
crwl2md crawl https://example.com/docs/intro -o ./docs \
  --max-pages 300 \
  --include 'https://example.com/docs/**' \
  --exclude '^https://example\.com/docs/v[0-9]+(/|$)' \
  --exclude 'changelog'
```

## Crawl Workflow

1. Run a small trial crawl (`--max-pages 5`) into a temporary directory separate from the final output, inspect `Crawl scope:` on stderr, and check a generated Markdown file (an unfetched-links warning is expected).
2. Run the full crawl into a clean output directory (do not reuse the trial directory, because overwriting does not remove stale files). Adjust `--max-pages` (default `100`) and `--include` / `--exclude` based on the trial.
3. Review stderr for warnings, skipped out-of-scope URLs, and failed pages. For rate limits, bot blocks, dynamic content, auth walls, or scope issues, check `crwl2md crawl --help` (or `convert --help`) and re-run.

## Output Notes

- **Start from `index.md`**: After `crawl`, read `<dir>/index.md` first to browse the generated documentation tree.
- **File layout**: `index.md` files are generated tables of contents. A crawled page that also has child pages is saved as `overview.md` in its directory.
- **Links and images**: For `crawl`, links between crawled pages become relative `.md` paths, while external links and images become absolute URLs (images are not downloaded locally). For `convert`, relative links and images become absolute URLs for URL sources, or stay relative for local HTML files without a base URL.
- **Exit status**: For `crawl`, exit code `0` means at least one page was saved, even if some pages failed; always review stderr.
