# web2md

ウェブサイトや HTML をクロールし、目次（`index.md`）付きの Markdown ファイル群へ変換する Python 製 CLI ツールです。

## セットアップ

```bash
task setup
```

## 使い方

### `uv run web2md --help`

```text
usage: web2md [-h] {convert,crawl} ...

Convert HTML pages or crawl documentation sites into Markdown with table of contents.

positional arguments:
  {convert,crawl}
    convert        Convert a single URL or local HTML file to Markdown.
    crawl          Crawl a documentation website and generate Markdown files with index.md TOCs.

options:
  -h, --help       show this help message and exit
```

### `uv run web2md convert --help`

```text
usage: web2md convert [-h] [-o OUTPUT] [--method {dom-markdownify,crawl4ai}] [--frontmatter] [--frontmatter-fields FRONTMATTER_FIELDS] source

positional arguments:
  source                Source URL or local HTML file path.

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output Markdown file path (default: stdout).
  --method {dom-markdownify,crawl4ai}
                        HTML-to-Markdown extraction method (default: dom-markdownify).
  --frontmatter         Prepend YAML frontmatter to output Markdown.
  --frontmatter-fields FRONTMATTER_FIELDS
                        Comma-separated YAML frontmatter fields (title,description,source,timestamp). Enables frontmatter when set.
```

### `uv run web2md crawl --help`

```text
usage: web2md crawl [-h] -o OUTPUT [--max-depth MAX_DEPTH] [--max-pages MAX_PAGES] [--method {dom-markdownify,crawl4ai}] [--include INCLUDE] [--exclude EXCLUDE] [--allow-all-paths] [--frontmatter] [--frontmatter-fields FRONTMATTER_FIELDS] [-v] url

positional arguments:
  url                   Seed URL to start crawling from.

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output directory for Markdown files and index.md.
  --max-depth MAX_DEPTH
                        Maximum crawl depth (default: 2).
  --max-pages MAX_PAGES
                        Maximum number of pages (default: 100).
  --method {dom-markdownify,crawl4ai}
                        HTML-to-Markdown extraction method (default: dom-markdownify).
  --include INCLUDE     URL pattern to include (repeatable).
  --exclude EXCLUDE     URL pattern to exclude (repeatable).
  --allow-all-paths     Allow crawling any path on the seed domain instead of restricting to the seed path prefix.
  --frontmatter         Prepend YAML frontmatter to output Markdown.
  --frontmatter-fields FRONTMATTER_FIELDS
                        Comma-separated YAML frontmatter fields (title,description,source,timestamp). Enables frontmatter when set.
  -v, --verbose         Enable verbose crawler logging.
```

### 実行例

```bash
# 単一ページ（URL またはローカル HTML）の変換
uv run web2md convert https://docs.elgato.com/streamdeck/cli/intro -o intro.md

# ドキュメントサイトのクロールと目次生成
uv run web2md crawl https://docs.elgato.com/streamdeck/cli/intro \
  --include "https://docs.elgato.com/streamdeck/cli/**" \
  --frontmatter-fields title,description,source,timestamp \
  -o ./output/streamdeck-cli
```

Python API 例:

```python
from web2md import crawl_site_sync

summary = crawl_site_sync(
    "https://docs.elgato.com/streamdeck/cli/intro",
    "output/streamdeck-cli",
    include_patterns=["https://docs.elgato.com/streamdeck/cli/**"],
)
```
