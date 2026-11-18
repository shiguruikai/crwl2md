# web2md

ウェブサイトや HTML をクロールし、目次（`index.md`）付きの Markdown ファイル群へ変換する Python 製 CLI ツールです。

こんなときに使う:

- HTML を Markdown に変換したい
- ウェブ上で公開されている技術系ドキュメントをクロールし、目次を含む Markdown ファイル群に変換したい

## インストール

前提として `uv` がインストールされている必要があります。

```bash
# GitHub リポジトリからグローバルインストール
uv tool install git+https://github.com/shiguruikai/web2md.git

# ローカルのリポジトリからインストールする場合（開発時は -e .）
uv tool install .

# 初回のみ：Playwright の Chromium ブラウザをインストール
uv tool run --from web2md playwright install chromium
```

`web2md` コマンドが見つからない場合は `uv tool update-shell` を実行し、シェルを再起動してください。

## アンインストール

```bash
uv tool uninstall web2md
```

## 開発セットアップ

```bash
task setup
```

## 使い方

インストールしない場合は `uv run web2md` で実行してください。

### `web2md --help`

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

### `web2md convert --help`

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

### `web2md crawl --help`

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
web2md convert https://docs.elgato.com/streamdeck/cli/intro -o intro.md

# ドキュメントサイトのクロールと目次生成
web2md crawl https://docs.elgato.com/streamdeck/cli/intro \
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
