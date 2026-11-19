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

# URL 取得に使うヘッドレスブラウザをダウンロード（約 290 MB）
web2md setup
```

- `web2md` コマンドが見つからない場合は `uv tool update-shell` を実行し、シェルを再起動してください。
- `web2md setup` は、URL を取得する `crawl` と `convert <URL>` で必要です。ローカル HTML ファイルの変換（`convert <PATH>`）はブラウザなしで動きます。
- Linux 環境で Chromium の依存ライブラリ（`libnss3` など）が不足している場合は、`web2md setup --with-deps` を実行してください（必要に応じて `sudo` が求められます）。
- `uv tool upgrade web2md` で更新したあとも `web2md setup` を実行してください。ブラウザは Playwright のバージョンごとに決まったビルドが必要で、ブラウザだけを更新することはできません。合っていない場合、`crawl` や `convert <URL>` は `web2md setup` の実行を求めて終了します。
- PyPI には、別の作者による同名のパッケージ `web2md` があります。`uv tool install web2md` や `uvx web2md` のように名前だけを指定すると、そちらがインストールされます。上記のとおり、リポジトリの URL またはパスを指定してください。

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
usage: web2md [-h] [--version] {convert,crawl,setup} ...

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

### `web2md convert --help`

```text
usage: web2md convert [-h] [-o OUTPUT] [--frontmatter] [--frontmatter-fields FRONTMATTER_FIELDS] source

positional arguments:
  source                Source URL, file:// URI, or local HTML file path.

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output Markdown file path (default: stdout).
  --frontmatter         Prepend YAML frontmatter to output Markdown.
  --frontmatter-fields FRONTMATTER_FIELDS
                        Comma-separated YAML frontmatter fields (title,description,source,timestamp). Enables frontmatter when set.
```

### `web2md crawl --help`

```text
usage: web2md crawl [-h] -o OUTPUT [--max-depth N] [--max-pages N] [--include INCLUDE] [--exclude EXCLUDE] [--allow-all-paths] [--delay SECONDS] [--concurrency N] [--respect-robots] [--force] [--frontmatter] [--frontmatter-fields FRONTMATTER_FIELDS] [-v] url

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
  --frontmatter         Prepend YAML frontmatter to output Markdown.
  --frontmatter-fields FRONTMATTER_FIELDS
                        Comma-separated YAML frontmatter fields (title,description,source,timestamp). Enables frontmatter when set.
  -v, --verbose         Enable verbose crawler logging.
```

### `web2md setup --help`

```text
usage: web2md setup [-h] [--with-deps]

options:
  -h, --help   show this help message and exit
  --with-deps  Also install OS-level libraries required by Chromium on Linux (may prompt for sudo).
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

# ローカルで起動したドキュメントサーバーのクロール
web2md crawl http://localhost:3000/docs/ -o ./output/local-docs
```

Python API 例:

```python
from pathlib import Path

from web2md import CrawlConfig, convert_single_sync, crawl_site_sync

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

## クロール範囲

`crawl` は、起点 URL と同じホストのうち、次の範囲にあるリンクだけを辿ります。適用する範囲は、開始時に `Crawl scope: ...` として標準エラー出力に表示します。

| 起点 URL | 既定の範囲 |
| --- | --- |
| `https://example.com/docs/intro` | `/docs` 配下（起点と同じディレクトリのページを含む） |
| `https://example.com/docs/` | `/docs` 配下 |
| `https://example.com/docs` | `/docs` 配下 |
| `https://example.com/`、`https://example.com/index.html` | ホスト全体 |

範囲は次のオプションで変更できます。

- `--include`：既定の範囲の代わりに、指定したパターンに一致する URL を範囲にします。
- `--exclude`：範囲のうち、指定したパターンに一致する URL を除きます。
- `--allow-all-paths`：ホスト全体を範囲にします。

リダイレクトの結果として範囲の外に出たページは保存せず、終了時に一覧を表示します。

### パターンの書き方

`--include` と `--exclude` には、次の5種類のパターンを指定できます。

| 書き方 | 例 | 一致する URL |
| --- | --- | --- |
| URL のグロブ | `https://example.com/docs/**` | `/docs` 自体とその配下すべて |
| ホスト相対のグロブ（`/` で始まる） | `/docs/*` | 任意のホストの `/docs` 直下 |
| 相対グロブ | `api/**`、`*.pdf` | パスの途中に `api/` というディレクトリを持つ URL、`.pdf` で終わる URL |
| 部分文字列（`*` も `?` も含まない） | `changelog` | `changelog` を含む URL |
| 正規表現（`^` で始まるか `$` で終わる） | `^https://example\.com/v\d+/` | 正規表現に一致する URL |

グロブの `*` はパスの1階層の中だけに、`**` は複数の階層に一致します。末尾の `/**` はそのディレクトリ自体にも一致し、途中の `/**/` は階層が0個の場合にも一致します。

旧バージョンや他言語のディレクトリが範囲に含まれてしまう場合は、`--exclude` で除外できます。

```bash
# 旧バージョン（2.x、3.0.1、next など）を除外
web2md crawl https://docusaurus.io/docs \
  --exclude '^https://docusaurus\.io/docs/(next|\d[\d.x]*)(/|$)' \
  -o ./output/docusaurus

# 英語以外の言語ディレクトリを除外
web2md crawl https://example.com/docs/ \
  --exclude '/docs/fr/**' \
  --exclude '/docs/de/**' \
  -o ./output/docs
```

## 出力の構成

```text
output/
├── index.md              # ルートの目次
├── overview.md           # 範囲の最上位の URL 自体のページ（配下にページがある場合）
├── intro.md
└── commands/
    ├── index.md          # commands/ の目次
    ├── overview.md       # /commands 自体のページ（配下にページがある場合）
    └── create.md
```

- 全ページに共通するパスの接頭辞は取り除きます。`/docs/intro` と `/docs/commands/create` をクロールすると、`intro.md` と `commands/create.md` になります。
- 配下にページを持つ URL は、そのディレクトリの `overview.md` になります（`/commands` と `/commands/create` があれば、前者は `commands/overview.md`）。`index.md` は生成する目次のために使います。
- URL のパーセントエンコードはデコードします（`/docs/%E3%81%AF...` は `はじめに.md`）。ファイル名に使えない文字は `_` に置き換えます。
- 出力先が重なる場合は、後から処理したページに `-2`、`-3` の連番を付けます。クエリ文字列だけが異なるページには、クエリのハッシュ値を付けます。
- クロールしたページへのリンクは相対パスの `.md` に、それ以外の相対リンクと画像は絶対 URL に書き換えます。
- 目次の並び順は、起点ページのサイドバーにあるリンクの順序に従います。サイドバーにないページはパスの順に並べます。

## 失敗と除外の報告

取得に失敗したページ（HTTP 400 番台・500 番台の応答を含む）は保存せず、終了時に URL と理由を標準エラー出力に表示します。Python API では `CrawlSummary.failed_pages` と `CrawlSummary.skipped_urls` で取得できます。失敗したページがあっても、1ページ以上を保存できれば終了コードは 0 です。

## 注意と既知の制限

- 既定では robots.txt を確認しません。公開サイトをクロールする場合は、サイトの利用規約を確認し、必要に応じて `--respect-robots` を指定してください。
- 既定では、最大5ページを同時に取得し、取得のまとまりごとに 0.1〜0.4 秒待ちます。失敗の一覧に `HTTP 429` が出る場合は、`--delay 2 --concurrency 1` のように間隔を空けて再実行してください。429 または 503 を受け取ると、以降の待ち時間は自動的に延びますが、拒否されたページを待ってから取り直すことはしません。
- 起点 URL が別のホストやディレクトリへリダイレクトされる場合、範囲はリダイレクト前の URL から決まるため、起点ページしか取得できません。このときは終了時にリダイレクト先の URL を警告として表示するので、その URL を起点に指定して再実行してください。
- インライン SVG で描かれた図は出力されません。
- 出力先にファイルが既に存在する場合は上書きを防ぐため終了します。既存の出力先へ再クロールするときは `--force` を指定してください。なお、`--force` を指定しても前回のクロールで作られ今回は作られなかったファイルは削除しません。
