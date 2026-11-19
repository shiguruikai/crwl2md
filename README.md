# crwl2md

[日本語](https://github.com/shiguruikai/crwl2md/blob/HEAD/README.ja.md)

A Python CLI tool that crawls websites or converts HTML pages into clean Markdown files with hierarchical tables of contents (`index.md`). Requires Python 3.13 or later.

Use `crwl2md` when you want to:

- Convert a single web page or local HTML file into Markdown
- Crawl a public or local technical documentation site into a linked tree of Markdown files with `index.md` tables of contents

## Installation

```bash
# Install globally with uv (recommended)
uv tool install crwl2md

# Or install with pipx / pip
pipx install crwl2md
pip install crwl2md

# Download the headless browser used for fetching URLs (about 290 MB)
crwl2md setup
```

To install the latest development version from GitHub or a local checkout:

```bash
uv tool install git+https://github.com/shiguruikai/crwl2md.git
# Or from a local clone (use -e . for editable install)
uv tool install .
```

- If the `crwl2md` command is not found after installing with `uv`, run `uv tool update-shell` and restart your shell.
- `crwl2md setup` is required for `crawl` and `convert <URL>`. Converting local HTML files (`convert <PATH>`) works without a browser.
- On Linux, if Chromium's OS-level dependencies (such as `libnss3`) are missing, run `crwl2md setup --with-deps` (may prompt for `sudo`).
- Re-run `crwl2md setup` after upgrading (for example, `uv tool upgrade crwl2md`). Playwright requires a specific browser build per release, and `crawl` or `convert <URL>` will exit and prompt you to run `crwl2md setup` if the installed browser does not match.

## Uninstallation

```bash
uv tool uninstall crwl2md
```

## Development Setup

```bash
task setup
```

## Usage

If you have not installed the tool globally, invoke it with `uv run crwl2md`.

### `crwl2md --help`

```text
usage: crwl2md [-h] [--version] {convert,crawl,setup} ...

Convert HTML pages or crawl documentation sites into Markdown with table of contents.

positional arguments:
  {convert,crawl,setup}
    convert             Convert a single URL or local HTML file to Markdown.
    crawl               Crawl a documentation website and generate Markdown files with index.md TOCs.
    setup               Download the headless browser used for fetching URLs (about 290 MB). Run once after installing or upgrading.

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```

### `crwl2md convert --help`

```text
usage: crwl2md convert [-h] [-o OUTPUT] [--header NAME:VALUE] [--storage-state PATH] [--user-data-dir PATH] [--proxy PROXY] [--stealth] [--wait-for CONDITION] [--scan-full-page] [--flatten-shadow-dom] [--frontmatter] [--frontmatter-fields FRONTMATTER_FIELDS] source

positional arguments:
  source                Source URL, file:// URI, or local HTML file path.

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output Markdown file path (default: stdout).
  --header NAME:VALUE   Extra HTTP header sent with browser requests ('Name: Value', repeatable).
  --storage-state PATH  Playwright storage_state.json file (cookies and localStorage) for authenticated sessions.
  --user-data-dir PATH  Persistent Chromium profile directory to reuse logged-in sessions.
  --proxy PROXY         Proxy server ('http://host:port', 'socks5://host:port', 'http://user:pass@host:port', or 'host:port:user:pass').
  --stealth             Enable stealth mode and navigator overrides to reduce anti-bot blocking.
  --wait-for CONDITION  CSS selector or 'js:() => ...' condition to wait for before extracting HTML.
  --scan-full-page      Scroll from top to bottom before extracting HTML so lazy-loaded content renders.
  --flatten-shadow-dom  Inline open and closed Shadow DOM trees into the HTML before conversion.
  --frontmatter         Prepend YAML frontmatter to output Markdown.
  --frontmatter-fields FRONTMATTER_FIELDS
                        Comma-separated YAML frontmatter fields (title,description,source,timestamp). Enables frontmatter when set.
```

### `crwl2md crawl --help`

```text
usage: crwl2md crawl [-h] -o OUTPUT [--max-depth N] [--max-pages N] [--include INCLUDE] [--exclude EXCLUDE] [--allow-all-paths] [--delay SECONDS] [--concurrency N] [--respect-robots] [--force] [--header NAME:VALUE] [--storage-state PATH] [--user-data-dir PATH] [--proxy PROXY] [--stealth] [--wait-for CONDITION] [--scan-full-page] [--flatten-shadow-dom] [--frontmatter] [--frontmatter-fields FRONTMATTER_FIELDS] [--no-progress] [-v] url

positional arguments:
  url                   Seed URL to start crawling from.

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output directory for Markdown files and index.md.
  --max-depth N         Maximum number of link hops from the seed page (0 = seed page only, default: unlimited).
  --max-pages N         Maximum number of pages (default: 100).
  --include INCLUDE     URL pattern to crawl: glob or regex, repeatable. Replaces the default seed-directory scope.
  --exclude EXCLUDE     URL pattern to skip: glob or regex, repeatable.
  --allow-all-paths     Allow crawling any path on the seed domain instead of restricting to the seed URL's directory.
  --delay SECONDS       Seconds to wait before each batch of concurrent requests (default: 0.1).
  --concurrency N       Maximum number of pages fetched at the same time (default: 5).
  --respect-robots      Skip pages that the site's robots.txt disallows.
  --force               Allow writing into a non-empty output directory and overwriting existing files.
  --header NAME:VALUE   Extra HTTP header sent with browser requests ('Name: Value', repeatable).
  --storage-state PATH  Playwright storage_state.json file (cookies and localStorage) for authenticated sessions.
  --user-data-dir PATH  Persistent Chromium profile directory to reuse logged-in sessions.
  --proxy PROXY         Proxy server ('http://host:port', 'socks5://host:port', 'http://user:pass@host:port', or 'host:port:user:pass').
  --stealth             Enable stealth mode and navigator overrides to reduce anti-bot blocking.
  --wait-for CONDITION  CSS selector or 'js:() => ...' condition to wait for before extracting HTML.
  --scan-full-page      Scroll from top to bottom before extracting HTML so lazy-loaded content renders.
  --flatten-shadow-dom  Inline open and closed Shadow DOM trees into the HTML before conversion.
  --frontmatter         Prepend YAML frontmatter to output Markdown.
  --frontmatter-fields FRONTMATTER_FIELDS
                        Comma-separated YAML frontmatter fields (title,description,source,timestamp). Enables frontmatter when set.
  --no-progress         Suppress per-page progress output during crawling.
  -v, --verbose         Enable verbose crawler logging.
```

### `crwl2md setup --help`

```text
usage: crwl2md setup [-h] [--with-deps]

options:
  -h, --help   show this help message and exit
  --with-deps  Also install OS-level libraries required by Chromium on Linux (may prompt for sudo).
```

### Examples

```bash
# Convert a single page (URL or local HTML file)
crwl2md convert https://docs.elgato.com/streamdeck/cli/intro -o intro.md

# Crawl a documentation site and generate hierarchical index.md TOCs
crwl2md crawl https://docs.elgato.com/streamdeck/cli/intro \
  --include "https://docs.elgato.com/streamdeck/cli/**" \
  --frontmatter-fields title,description,source,timestamp \
  -o ./output/streamdeck-cli

# Crawl a locally running documentation server
crwl2md crawl http://localhost:3000/docs/ -o ./output/local-docs
```

Python API example:

```python
from pathlib import Path

from crwl2md import CrawlConfig, convert_single_sync, crawl_site_sync

markdown = convert_single_sync(Path("page.html"), frontmatter=True)

summary = crawl_site_sync(
    CrawlConfig(
        url="https://docs.elgato.com/streamdeck/cli/intro",
        output_dir=Path("output/streamdeck-cli"),
        include_patterns=["https://docs.elgato.com/streamdeck/cli/**"],
    )
)
for page in summary.failed_pages:
    print(page.url, page.reason)
```

## Crawl Scope

`crawl` only follows links on the same host within the default scope below. The active scope is printed to stderr as `Crawl scope: ...` when crawling starts.

| Seed URL | Default scope |
| --- | --- |
| `https://example.com/docs/intro` | Under `/docs` (including sibling pages in the same directory) |
| `https://example.com/docs/` | Under `/docs` |
| `https://example.com/docs` | Under `/docs` |
| `https://example.com/`, `https://example.com/index.html` | Entire host |

You can customize the scope with:

- `--include`: Replaces the default scope with URLs matching the given pattern(s).
- `--exclude`: Skips URLs matching the given pattern(s).
- `--allow-all-paths`: Crawls any path on the seed host.

Pages that end up outside the scope after a redirect are not saved and are listed when the crawl finishes.

### Pattern Syntax

`--include` and `--exclude` accept five pattern styles:

| Style | Example | Matches |
| --- | --- | --- |
| Full URL glob | `https://example.com/docs/**` | `/docs` itself and everything under it |
| Host-relative glob (starts with `/`) | `/docs/*` | Direct children of `/docs` on any host |
| Relative glob | `api/**`, `*.pdf` | URLs with an `api/` path segment, or URLs ending in `.pdf` |
| Substring (no `*` or `?`) | `changelog` | Any URL containing `changelog` |
| Regular expression (starts with `^` or ends with `$`) | `^https://example\.com/v\d+/` | URLs matching the regex |

In globs, `*` matches within a single path segment and `**` crosses multiple segments. A trailing `/**` also matches the directory itself, and an intermediate `/**/` matches zero or more directories.

You can exclude legacy versions or other language directories with `--exclude`:

```bash
# Exclude legacy versions (2.x, 3.0.1, next, etc.)
crwl2md crawl https://docusaurus.io/docs \
  --exclude '^https://docusaurus\.io/docs/(next|\d[\d.x]*)(/|$)' \
  -o ./output/docusaurus

# Exclude non-English language directories
crwl2md crawl https://example.com/docs/ \
  --exclude '/docs/fr/**' \
  --exclude '/docs/de/**' \
  -o ./output/docs
```

## Output Layout

```text
output/
├── index.md              # Root table of contents
├── overview.md           # Top-level scope URL itself (when descendant pages exist)
├── intro.md
└── commands/
    ├── index.md          # Table of contents for commands/
    ├── overview.md       # /commands itself (when descendant pages exist)
    └── create.md
```

- Common path prefixes shared across all crawled pages are stripped. Crawling `/docs/intro` and `/docs/commands/create` produces `intro.md` and `commands/create.md`.
- A URL that has descendant pages is saved as `overview.md` in its directory (for example, `/commands` becomes `commands/overview.md` when `/commands/create` also exists). `index.md` is reserved for generated tables of contents.
- Percent-encoded URL segments are decoded into readable filenames, and characters invalid in filenames are replaced with `_`.
- Colliding output paths receive `-2`, `-3`, ... suffixes. URLs differing only in query parameters receive a short query hash suffix.
- Links to crawled pages are rewritten to relative `.md` paths; all other relative links and images are rewritten to absolute URLs.
- Entries in `index.md` follow the link order from the seed page's sidebar navigation; pages absent from the sidebar are sorted by path.

## Failed and Skipped Pages

Pages that fail to fetch (including HTTP 4xx/5xx responses) are not saved; their URLs and reasons are printed to stderr at the end of the run. Through the Python API, they are available on `CrawlSummary.failed_pages` and `CrawlSummary.skipped_urls`. As long as at least one page is saved, the CLI exits with status `0`.

## Notes and Known Limitations

- `robots.txt` is not checked by default. Before crawling a public site, review its terms of service and pass `--respect-robots` when appropriate.
- By default, up to 5 pages are fetched concurrently with a 0.1–0.4 second wait before each batch. If `HTTP 429` appears in the failed pages list, re-run with slower pacing such as `--delay 2 --concurrency 1`. On HTTP 429 or 503, subsequent delays automatically increase, but rejected pages are not retried after waiting.
- If the seed URL redirects to a different host or directory outside the initial scope, only the seed page is fetched. A warning displays the redirected URL so you can re-run using that URL as the seed.
- Inline `<svg>` graphics are omitted from the Markdown output.
- If the output directory already contains files, `crawl` exits to avoid accidental overwrites. Pass `--force` to write into a non-empty directory. Note that `--force` does not remove stale files left over from previous crawls.
- `--header` attaches the given headers to every request made by the browser (including third-party scripts and assets). For site-scoped authentication, prefer `--storage-state` or `--user-data-dir`.

## License

MIT License ([LICENSE](https://github.com/shiguruikai/crwl2md/blob/HEAD/LICENSE))

## Acknowledgments

This product includes software developed by UncleCode (<https://x.com/unclecode>) as part of the Crawl4AI project (<https://github.com/unclecode/crawl4ai>).
