# crwl2md

[English](README.md)

ウェブサイトや HTML をクロールし、目次（`index.md`）付きの Markdown ファイル群へ変換する Python 製 CLI ツールです。Python 3.13 以上に対応しています。

こんなときに使う:

- HTML を Markdown に変換したい
- ウェブ上で公開されている技術系ドキュメントをクロールし、目次を含む Markdown ファイル群に変換したい

## インストール

```bash
# uv を使ってグローバルインストール（推奨）
uv tool install crwl2md

# pipx や pip でもインストール可能
pipx install crwl2md
pip install crwl2md

# URL 取得に使う Chromium ブラウザをダウンロード
crwl2md setup
```

開発中の最新版を GitHub やローカルからインストールする場合:

```bash
uv tool install git+https://github.com/shiguruikai/crwl2md.git
# またはローカルのリポジトリから（編集可能モードは -e .）
uv tool install .
```

- `crwl2md` コマンドが見つからない場合は `uv tool update-shell` を実行し、シェルを再起動してください。
- `crwl2md setup` は、URL を取得する `crawl` と `convert <URL>` で必要です。ローカル HTML ファイルの変換（`convert <PATH>`）はブラウザなしで動きます。
- Linux 環境で Chromium の依存ライブラリ（`libnss3` など）が不足している場合は、`crwl2md setup --with-deps` を実行してください（必要に応じて `sudo` が求められます）。
- `uv tool upgrade crwl2md` などで更新したあとも `crwl2md setup` を実行してください。ブラウザは Playwright のバージョンごとに決まったビルドが必要で、ブラウザだけを更新することはできません。合っていない場合、`crawl` や `convert <URL>` は `crwl2md setup` の実行を求めて終了します。

## アンインストール

```bash
uv tool uninstall crwl2md
```

## 開発セットアップ

```bash
task setup
```

## 使い方

インストールしない場合は `uv run crwl2md` で実行してください。

### コマンド一覧

```bash
crwl2md [グローバルオプション] <コマンド> [引数・オプション]
```

| コマンド | 説明 |
| --- | --- |
| `setup` | URL 取得に使う Chromium ブラウザをダウンロードする。 |
| `convert` | 単一の URL、`file://` URI、またはローカル HTML ファイルを Markdown に変換する。 |
| `crawl` | ウェブサイトをクロールし、Markdown ファイル群と階層目次（`index.md`）を生成する。 |

| グローバルオプション | 説明 |
| --- | --- |
| `-h`, `--help` | ヘルプを表示して終了する（各サブコマンドでも使用可）。 |
| `--version` | バージョンを表示して終了する。 |

### 実行例

```bash
# 単一ページ（URL またはローカル HTML）の変換
crwl2md convert https://docs.elgato.com/streamdeck/cli/intro -o intro.md
crwl2md convert ./page.html

# ドキュメントサイトのクロールと目次生成
crwl2md crawl https://docs.elgato.com/streamdeck/cli/intro \
  -o ./output/streamdeck-cli \
  --include "https://docs.elgato.com/streamdeck/cli/**" \
  --frontmatter-fields title,description,source,timestamp

# ローカルで起動したドキュメントサーバーのクロール
crwl2md crawl http://localhost:3000/docs/ -o ./output/local-docs
```

### `crwl2md setup`

URL 取得に使う Chromium ブラウザをダウンロードします。インストール後およびアップグレード後に1回実行してください。

```bash
crwl2md setup [オプション]
```

| オプション | 既定値 | 説明 |
| --- | --- | --- |
| `--with-deps` | — | Linux 環境で Chromium に必要な OS レベルのライブラリもインストールする（`sudo` が求められる場合あり）。 |

### `crwl2md convert`

単一のページを Markdown に変換します。

```bash
crwl2md convert <source> [オプション]
```

| 引数・オプション | 既定値 | 説明 |
| --- | --- | --- |
| `<source>` | 必須 | 変換元の URL、`file://` URI、またはローカル HTML ファイルのパス。 |
| `-o`, `--output <PATH>` | 標準出力 | 出力先の Markdown ファイルパス。 |

上記のほか、[共通オプション](#共通オプション)も指定できます。ブラウザ取得に関するオプションは `http://`・`https://` の URL を変換するときに使われます。

### `crwl2md crawl`

ドキュメントサイトをクロールし、リンクを書き換えた Markdown ファイル群と階層目次（`index.md`）を生成します。

```bash
crwl2md crawl <url> -o <DIR> [オプション]
```

| 引数・オプション | 既定値 | 説明 |
| --- | --- | --- |
| `<url>` | 必須 | クロールの起点 URL（`http://` または `https://`）。 |
| `-o`, `--output <DIR>` | 必須 | Markdown ファイルと `index.md` の出力先ディレクトリ。 |
| `--max-depth <N>` | 無制限 | 起点ページからリンクを辿る最大ホップ数（`0` は起点ページのみ）。 |
| `--max-pages <N>` | `100` | 取得する最大ページ数（1以上）。 |
| `--include <PATTERN>` | — | クロール対象とする URL パターン（グロブまたは正規表現、複数回指定可）。指定すると既定のクロール範囲を置き換える。 |
| `--exclude <PATTERN>` | — | クロール対象から除外する URL パターン（グロブまたは正規表現、複数回指定可）。 |
| `--allow-all-paths` | — | 起点 URL のディレクトリ配下に限定せず、同一ホスト上の全パスを対象にする。 |
| `--delay <SECONDS>` | `0.1` | 同時取得のまとまりごとに入れる待機秒数（0以上）。 |
| `--concurrency <N>` | `5` | 同時に取得する最大ページ数（1以上）。 |
| `--respect-robots` | — | サイトの `robots.txt` で禁止されたページをスキップする。 |
| `--force` | — | 空でない出力先ディレクトリへの書き込みと既存ファイルの上書きを許可する。 |
| `--no-progress` | — | クロール中のページごとの進捗出力を抑止する。 |
| `-v`, `--verbose` | — | クローラーの詳細ログを有効にする。 |

上記のほか、[共通オプション](#共通オプション)も指定できます。クロール範囲とパターンの指定方法は[クロール範囲](#クロール範囲)を参照してください。

### 共通オプション

`convert` と `crawl` の両方で指定できるオプションです。

#### ブラウザ・取得

| オプション | 既定値 | 説明 |
| --- | --- | --- |
| `--header <NAME:VALUE>` | — | ブラウザのリクエストに付与する追加 HTTP ヘッダー（`Name: Value` 形式、複数回指定可）。 |
| `--storage-state <PATH>` | — | 認証済みセッションを使うための Playwright `storage_state.json`（Cookie と `localStorage`）。`--user-data-dir` とは併用不可。 |
| `--user-data-dir <PATH>` | — | ログイン済みセッションを再利用する Chromium の永続プロファイルディレクトリ。`--storage-state` とは併用不可。 |
| `--proxy <PROXY>` | — | プロキシサーバー（`http://host:port`、`socks5://host:port`、`http://user:pass@host:port`、`host:port:user:pass` など）。 |
| `--stealth` | — | ステルスモードと navigator の上書きを有効にし、ボット遮断を緩和する。 |
| `--headed` | — | ヘッドレスではなくウィンドウを表示して Chromium を実行する（`--stealth` との併用やデバッグに有用）。 |
| `--wait-for <CONDITION>` | — | HTML 抽出前に待機する条件（CSS セレクターまたは `js:() => ...`）。 |
| `--wait-for-timeout <SECONDS>` | `15`（`--wait-for` 指定時）／`5`（未指定時） | HTML 抽出前の待機タイムアウト秒数（0より大きい値）。 |
| `--scan-full-page` | — | HTML 抽出前にページ先頭から末尾までスクロールし、遅延読み込みコンテンツを描画させる。 |
| `--flatten-shadow-dom` | — | 変換前に open・closed の Shadow DOM ツリーを HTML へ展開する。 |

#### フロントマター

| オプション | 既定値 | 説明 |
| --- | --- | --- |
| `--frontmatter` | — | 出力 Markdown の先頭に YAML フロントマター（`title`、`description`、`source`、`timestamp`）を付与する。 |
| `--frontmatter-fields <FIELDS>` | — | 出力する YAML フロントマター項目をカンマ区切りで指定する（`title`、`description`、`source`、`timestamp`）。指定するとフロントマター出力が有効になる。 |

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
| 相対グロブ | `api/**`、`*.html` | パスの途中に `api/` というディレクトリを持つ URL、`.html` で終わる URL |
| 部分文字列（`*` も `?` も含まない） | `changelog` | `changelog` を含む URL |
| 正規表現（`^` で始まるか `$` で終わる） | `^https://example\.com/v\d+/` | 正規表現に一致する URL |

グロブの `*` はパスの1階層の中だけに、`**` は複数の階層に一致します。末尾の `/**` はそのディレクトリ自体にも一致し、途中の `/**/` は階層が0個の場合にも一致します。

旧バージョンや他言語のディレクトリが範囲に含まれてしまう場合は、`--exclude` で除外できます。

```bash
# 旧バージョン（2.x、3.0.1、next など）を除外
crwl2md crawl https://docusaurus.io/docs \
  --exclude '^https://docusaurus\.io/docs/(next|\d[\d.x]*)(/|$)' \
  -o ./output/docusaurus

# 英語以外の言語ディレクトリを除外
crwl2md crawl https://example.com/docs/ \
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
- `--header` で指定したヘッダーは、ブラウザが行うすべてのリクエスト（外部 CDN やサードパーティスクリプトを含む）に送信されます。特定サイト向けの認証には `--storage-state` や `--user-data-dir` の利用を推奨します。
- ボット対策が厳しいサイトでは、GUI 環境で `--stealth --headed` を併用するとヘッドレス判定を回避しやすくなります。

## ライセンス

MIT License（[LICENSE](LICENSE)）

## 謝辞

This product includes software developed by UncleCode (<https://x.com/unclecode>) as part of the Crawl4AI project (<https://github.com/unclecode/crawl4ai>).
