# crwl2md

[日本語](https://github.com/shiguruikai/crwl2md/blob/HEAD/README.ja.md)

A Python CLI tool that crawls websites or converts HTML pages into clean Markdown files with hierarchical tables of contents (`index.md`). Requires Python 3.13 or later.

## Features

- **Content extraction**: Targets the main body on Docusaurus, MkDocs Material, VitePress, MDN, Qiita, Zenn, etc., stripping navs, breadcrumbs, and edit links.
- **Technical Markdown**: Preserves code fence languages, admonitions, ARIA tab panels, tables, and definition lists.
- **Link rewriting & TOCs**: Rewrites internal links to relative `.md` paths and generates nested `index.md` files ordered by sidebar navigation.
- **Dynamic & authenticated sites**: Playwright (Chromium) rendering with wait conditions, full-page scroll, Shadow DOM flattening, cookie/profile auth, and stealth mode.

## Installation

Install globally with `uv` (recommended) and download the Chromium browser used for fetching URLs:

```bash
uv tool install crwl2md
crwl2md setup
```

To install with `pipx` or `pip` instead (then run `crwl2md setup`):

```bash
pipx install crwl2md
# or
pip install crwl2md
```

To install the latest development version from GitHub or a local checkout:

```bash
uv tool install git+https://github.com/shiguruikai/crwl2md.git
# Or from a local clone (use -e . for editable install)
uv tool install .
```

- `crwl2md setup` is required for `crawl` and `convert <URL>`. Converting local HTML files (`convert <PATH>`) works without a browser.
- Re-run `crwl2md setup` after upgrading (for example, `uv tool upgrade crwl2md`). Playwright requires a specific Chromium build per release.
- If `crwl2md` is not found on your `PATH` or Linux OS libraries are missing, see [Troubleshooting](#troubleshooting).

### Agent Skill

An [Agent Skill](https://agentskills.io/) for AI coding agents is available in [skills/crwl2md/SKILL.md](https://github.com/shiguruikai/crwl2md/blob/HEAD/skills/crwl2md/SKILL.md):

```bash
# GitHub CLI
gh skill install shiguruikai/crwl2md crwl2md

# skills CLI
npx skills add shiguruikai/crwl2md
```

Pass `--scope user` (`gh skill`) or `-g` (`npx skills`) to install globally instead of in the current project.

## Usage

When running from a locally cloned repository without a global install, invoke the CLI with `uv run crwl2md`.

### Commands

```bash
crwl2md [GLOBAL OPTIONS] <COMMAND> [ARGS / OPTIONS]
```

| Command | Description |
| --- | --- |
| `setup` | Download the Chromium browser used for fetching URLs. |
| `convert` | Convert a single URL, `file://` URI, or local HTML file to Markdown. |
| `crawl` | Crawl a website and generate Markdown files with hierarchical `index.md` tables of contents. |

| Global option | Description |
| --- | --- |
| `-h`, `--help` | Show help and exit (also available on every subcommand). |
| `--version` | Show the program version and exit. |

### Examples

```bash
# Convert a single page (URL or local HTML file)
crwl2md convert https://docs.elgato.com/streamdeck/cli/intro -o intro.md
crwl2md convert ./page.html

# Crawl a documentation site and generate hierarchical index.md TOCs
crwl2md crawl https://docs.elgato.com/streamdeck/cli/intro \
  -o ./output/streamdeck-cli \
  --include "https://docs.elgato.com/streamdeck/cli/**" \
  --frontmatter-fields title,description,source,timestamp

# Crawl a locally running documentation server
crwl2md crawl http://localhost:3000/docs/ -o ./output/local-docs
```

Examples for SPAs and authenticated sites:

```bash
# Wait for dynamic content before converting (CSS selector or js:() => ...)
crwl2md convert https://example.com/app \
  --wait-for "article.doc-content" \
  --scan-full-page \
  -o app.md

crwl2md convert https://example.com/spa \
  --wait-for "js:() => document.querySelectorAll('.doc-item').length > 0" \
  --wait-for-timeout 20

# Crawl using a Playwright storage_state.json file
crwl2md crawl https://internal.example.com/docs/ \
  -o ./output/internal-docs \
  --storage-state ./auth.json
```

### `crwl2md setup`

Download the Chromium browser used for fetching URLs. Run once after installing or upgrading.

```bash
crwl2md setup [OPTIONS]
```

| Option | Default | Description |
| --- | --- | --- |
| `--with-deps` | — | Also install OS-level libraries required by Chromium on Linux (may prompt for `sudo`). |

### `crwl2md convert`

Convert a single page into Markdown.

```bash
crwl2md convert <source> [OPTIONS]
```

| Argument / Option | Default | Description |
| --- | --- | --- |
| `<source>` | Required | Source URL, `file://` URI, or local HTML file path. |
| `-o`, `--output <PATH>` | stdout | Output Markdown file path. |

Also accepts all [Shared Options](#shared-options). Browser and fetching options apply when converting `http://` or `https://` URLs.

### `crwl2md crawl`

Crawl a documentation website and write link-rewritten Markdown files with hierarchical `index.md` tables of contents.

```bash
crwl2md crawl <url> -o <DIR> [OPTIONS]
```

| Argument / Option | Default | Description |
| --- | --- | --- |
| `<url>` | Required | Seed URL (`http://` or `https://`) to start crawling from. |
| `-o`, `--output <DIR>` | Required | Output directory for Markdown files and `index.md`. |
| `--max-depth <N>` | Unlimited | Maximum number of link hops from the seed page (`0` = seed page only). |
| `--max-pages <N>` | `100` | Maximum number of pages to fetch (`>= 1`). |
| `--include <PATTERN>` | — | URL pattern to crawl (glob or regex, repeatable). Replaces the default seed-directory scope. |
| `--exclude <PATTERN>` | — | URL pattern to skip (glob or regex, repeatable). |
| `--allow-all-paths` | — | Allow crawling any path on the seed host instead of restricting to the seed URL's directory. |
| `--delay <SECONDS>` | `0.1` | Seconds to wait before each batch of concurrent requests (`>= 0`; up to 0.3 s of random jitter is added). |
| `--concurrency <N>` | `5` | Maximum number of pages fetched at the same time (`>= 1`). |
| `--respect-robots` | — | Skip pages disallowed by the site's `robots.txt`. |
| `--force` | — | Allow writing into a non-empty output directory and overwriting existing files. |
| `--no-progress` | — | Suppress per-page progress output during crawling. |
| `-v`, `--verbose` | — | Enable verbose crawler logging. |

Also accepts all [Shared Options](#shared-options). See [Crawl Scope](#crawl-scope) for details on scope rules and pattern syntax.

### Shared Options

These options are available for both `convert` and `crawl`.

#### Browser and Fetching

| Option | Default | Description |
| --- | --- | --- |
| `--header <NAME:VALUE>` | — | Extra HTTP header sent with all browser requests, including third-party assets (`Name: Value` format, repeatable). Prefer `--storage-state` or `--user-data-dir` for authentication. |
| `--storage-state <PATH>` | — | Playwright `storage_state.json` file (cookies and `localStorage`) for authenticated sessions. Cannot be combined with `--user-data-dir`. |
| `--user-data-dir <PATH>` | — | Persistent Chromium profile directory to reuse logged-in sessions. Cannot be combined with `--storage-state`. |
| `--proxy <PROXY>` | — | Proxy server (`http://host:port`, `socks5://host:port`, `http://user:pass@host:port`, `host:port:user:pass`, etc.). |
| `--stealth` | — | Enable stealth mode and navigator overrides to reduce anti-bot blocking. |
| `--headed` | — | Run Chromium in a visible window instead of headless mode (useful with `--stealth` or debugging). |
| `--wait-for <CONDITION>` | — | CSS selector or `js:() => ...` condition to wait for before extracting HTML. |
| `--wait-for-timeout <SECONDS>` | `15` (with `--wait-for`) / `5` (otherwise) | Seconds to wait before HTML extraction times out (`> 0`). Also applies to the built-in content-ready wait when `--wait-for` is omitted. |
| `--scan-full-page` | — | Scroll from top to bottom before extracting HTML so lazy-loaded content renders. |
| `--flatten-shadow-dom` | — | Inline open and closed Shadow DOM trees into the HTML before conversion. |

#### Frontmatter

| Option | Default | Description |
| --- | --- | --- |
| `--frontmatter` | — | Prepend YAML frontmatter (`title`, `description`, `source`, `timestamp`) to output Markdown. |
| `--frontmatter-fields <FIELDS>` | — | Comma-separated YAML frontmatter fields (`title`, `description`, `source`, `timestamp`). Enables frontmatter when set. |

### Python API

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

Additional public APIs are also exported:

- Async equivalents: `convert_single` and `crawl_site` (for callers running inside an existing event loop; `crawl_site` and `crawl_site_sync` also accept an `on_progress` callback).
- Direct HTML string conversion: `extract_markdown(html, url=...)` converts raw HTML without launching a browser or touching the filesystem.
- Browser setup and errors: `install_browser()` and `BrowserNotInstalledError`.

## Crawl Scope

By default, `crawl` follows only links on the same host within the scope below. Non-HTML assets (images, CSS, JavaScript, PDFs, archives, etc.) are skipped automatically. The active scope is printed to stderr as `Crawl scope: ...` when crawling starts.

| Seed URL | Default scope |
| --- | --- |
| `https://example.com/docs/intro` | Under `/docs` (including sibling pages in the same directory) |
| `https://example.com/docs/` | Under `/docs` |
| `https://example.com/docs` | Under `/docs` |
| `https://example.com/`, `https://example.com/index.html` | Entire host |

You can customize the scope with:

- `--include`: Replaces the default scope with URLs matching the given pattern(s). Specifying a full URL pattern for another host also allows crawling that host.
- `--exclude`: Skips URLs matching the given pattern(s).
- `--allow-all-paths`: Crawls any path on the seed host.

Pages that end up outside the scope after a redirect are not saved and are listed when the crawl finishes.

### Pattern Syntax

`--include` and `--exclude` accept five pattern styles:

| Style | Example | Matches |
| --- | --- | --- |
| Full URL glob | `https://example.com/docs/**` | `/docs` itself and everything under it |
| Host-relative glob (starts with `/`) | `/docs/*` | Direct children of `/docs` on any host |
| Relative glob | `api/**`, `*.html` | URLs with an `api/` path segment, or URLs ending in `.html` |
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

- Common path prefixes shared across all crawled pages are stripped. Crawling `/docs/intro` and `/docs/commands/create` produces `intro.md` and `commands/create.md`. When a crawl spans multiple hosts, pages are grouped under per-host directories.
- A URL that has descendant pages is saved as `overview.md` in its directory (for example, `/commands` becomes `commands/overview.md` when `/commands/create` also exists). `index.md` is reserved for generated tables of contents.
- Percent-encoded URL segments are decoded into readable filenames, and characters invalid in filenames are replaced with `_`.
- Colliding output paths receive `-2`, `-3`, ... suffixes. URLs differing only in query parameters receive a short query hash suffix.
- Links to crawled pages are rewritten to relative `.md` paths; all other relative links and images are rewritten to absolute URLs.
- Entries in `index.md` follow the link order from the seed page's sidebar navigation; pages absent from the sidebar are sorted by path.

### Sample Output

Root table of contents (`index.md`):

```markdown
# docs.elgato.com Documentation

## Subcategories

- [Commands](commands/index.md) - CLI command reference

## Documents

- [Overview](overview.md) - Stream Deck CLI documentation
- [Introduction](intro.md) - Get started with the Stream Deck CLI
```

YAML frontmatter (with `--frontmatter`):

```yaml
---
title: "Introduction"
description: "Get started with the Stream Deck CLI"
source: "https://docs.elgato.com/streamdeck/cli/intro"
timestamp: 2026-04-01T00:00:00Z
---
```

### Progress, Reporting, and Exit Codes

- Per-page progress is printed to stderr during crawling (suppress with `--no-progress`). On completion, total page count, generated `index.md` count, and per-top-level-directory counts are printed to stdout.
- Pages that fail to fetch (including HTTP 4xx/5xx responses) are not saved; their URLs and reasons are printed to stderr at the end of the run, along with any skipped out-of-scope URLs, seed redirect warnings, and unfetched in-scope link warnings.
- Through the Python API, the same details are exposed on `CrawlSummary` (`failed_pages`, `skipped_urls`, `seed_redirected_to`, `unfetched_in_scope_links`, etc.).
- CLI exit codes: `0` if at least one page is saved (even when some pages fail), `1` on fatal errors or when zero pages are saved, and `130` when interrupted with Ctrl+C.

## Troubleshooting

### `crwl2md` command not found

If `crwl2md` is not found after installing with `uv`, run `uv tool update-shell` and restart your shell.

### Missing Chromium, version mismatch, or missing Linux libraries

- If `crawl` or `convert <URL>` reports a missing browser or Playwright version mismatch, run `crwl2md setup` (also required after upgrading `crwl2md`).
- On Linux, if OS-level shared libraries (such as `libnss3`) are missing, run `crwl2md setup --with-deps` (may prompt for `sudo`).

### Pages fail with `HTTP 429` (rate limiting)

By default, up to 5 pages are fetched concurrently with a 0.1–0.4 second wait before each batch. If `HTTP 429` appears in the failed pages list, re-run with slower pacing:

```bash
crwl2md crawl https://example.com/docs/ -o ./output/docs --delay 2 --concurrency 1
```

### Only the seed page is crawled (redirected outside scope)

If the seed URL redirects to a different host or directory outside the initial scope, only the seed page is fetched. A warning displays the redirected URL so you can re-run using that URL as the seed.

### Blocked by anti-bot protection (403 or challenge pages)

Re-run with `--stealth`. On sites with stricter bot detection, combining `--stealth --headed` in an environment with a desktop display reduces headless detection signals.

### Missing or empty content on SPA or dynamic pages

By default, `crwl2md` waits up to 5 seconds for main content text to render. If a page still fails with `Empty page content` or misses dynamically loaded sections, try:

- Waiting for a specific element or JS condition: `--wait-for "CSS selector"` or `--wait-for "js:() => ..."` (raise `--wait-for-timeout` if needed)
- Rendering lazy-loaded sections by scrolling: `--scan-full-page`
- Extracting content inside Web Components: `--flatten-shadow-dom`

### Warning that in-scope links were not fetched

`Warning: N in-scope links were not fetched ...` means the crawl hit the `--max-pages` limit (default `100`) or `--max-depth`. Raise the limits or narrow the scope with `--include` / `--exclude`.

### Cannot crawl pages behind authentication

To reuse a logged-in session's cookies and `localStorage`, pass a Playwright `storage_state.json` via `--storage-state <PATH>`, or point `--user-data-dir <PATH>` to a persistent Chromium profile directory (these two options cannot be combined).

### Output directory is not empty

To avoid accidental overwrites, `crawl` exits if the output directory already contains files. Pass `--force` to write into a non-empty directory.

## Known Limitations

- **Inline `<svg>` graphics are omitted**: Inline `<svg>` diagrams in HTML are dropped from Markdown output (external image tags such as `<img src="...svg">` are preserved as absolute URLs).
- **Images are not downloaded locally**: Image files are not saved to disk; image references are rewritten to absolute URLs.
- **HTTP 429 / 503 rejections are not retried after waiting**: Subsequent batch delays increase automatically after 429 or 503 responses, but rejected pages are not retried after waiting.
- **JavaScript-only navigation without `<a href>` is not followed**: Links triggered solely by JS click handlers cannot be discovered during crawling.
- **`--force` does not remove stale files**: Re-crawling overwrites newly generated paths, but files left over from previous crawls remain in the output directory.
- **`robots.txt` is not checked by default**: Before crawling a public site, review its terms of service and pass `--respect-robots` when appropriate.
- **`--header` is sent on every browser request**: Custom headers are attached to third-party scripts and CDN assets as well. For site-scoped authentication, prefer `--storage-state` or `--user-data-dir`.

## Uninstallation

```bash
uv tool uninstall crwl2md
```

If installed with `pipx` or `pip`, run `pipx uninstall crwl2md` or `pip uninstall crwl2md` instead.

Uninstalling `crwl2md` does not automatically remove the Chromium cache downloaded by `crwl2md setup`. If you no longer need it (and do not share it with other Playwright tools), you can remove:

- Linux / macOS: `~/.cache/ms-playwright`
- Windows: `%LOCALAPPDATA%\ms-playwright`

## Development

Development uses `mise`, `go-task` (`task`), and `uv`.

```bash
task setup
```

`task setup` runs `mise install`, `uv sync --frozen --reinstall`, and `uv run crwl2md setup`. Common tasks:

| Task | Description |
| --- | --- |
| `task setup` | Set up runtime tools, Python dependencies, and Chromium |
| `task format` | Format and auto-fix TOML, Markdown, and Python files |
| `task lint` | Run `tombi`, `markdownlint-cli2`, `ruff`, and `pyright` |
| `task test` | Run `pytest` with coverage (no browser required) |

## License

MIT License ([LICENSE](https://github.com/shiguruikai/crwl2md/blob/HEAD/LICENSE))

## Acknowledgments

This product includes software developed by UncleCode (<https://x.com/unclecode>) as part of the Crawl4AI project (<https://github.com/unclecode/crawl4ai>).
