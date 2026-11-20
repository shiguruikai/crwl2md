# crwl2md

[English](README.md)

ウェブサイトや HTML をクロールし、目次（`index.md`）付きの Markdown ファイル群へ変換する Python 製 CLI ツールです。Python 3.13 以上に対応しています。

## 主な特徴

- **本文抽出**：Docusaurus、MkDocs Material、VitePress、MDN、Qiita、Zenn 等の本文領域を抽出し、ナビゲーション・パンくず・編集リンク等を除去
- **技術文書向け変換**：コードブロックの言語タグ、Admonition、ARIA タブパネル、テーブル、定義リストを保持
- **リンク書き換えと階層目次**：取得済みページ間を相対 `.md` リンクへ変換し、サイドバー順に `index.md` を生成
- **動的・認証サイト対応**：Playwright（Chromium）による描画待機、遅延読み込みスクロール、Shadow DOM 展開、Cookie／プロファイル認証、ステルスモードに対応

## インストール

推奨の `uv` を使ってグローバルインストールし、URL 取得に使う Chromium ブラウザをダウンロードします。

```bash
uv tool install crwl2md
crwl2md setup
```

`pipx` や `pip` でインストールする場合（インストール後に `crwl2md setup` も実行してください）：

```bash
pipx install crwl2md
# または
pip install crwl2md
```

開発中の最新版を GitHub やローカルのリポジトリからインストールする場合：

```bash
uv tool install git+https://github.com/shiguruikai/crwl2md.git
# またはローカルのリポジトリから（編集可能モードは -e .）
uv tool install .
```

- `crwl2md setup` は、URL を取得する `crawl` と `convert <URL>` で必要です。ローカル HTML ファイルの変換（`convert <PATH>`）はブラウザなしで動きます。
- `uv tool upgrade crwl2md` などで更新したあとも `crwl2md setup` を実行してください。Playwright はバージョンごとに決まった Chromium ビルドを必要とします。
- `crwl2md` コマンドが見つからない場合や Linux で OS の共有ライブラリが不足する場合は、[トラブルシューティング](#トラブルシューティング)を参照してください。

## 使い方

ローカルにクローンしたリポジトリからグローバルインストールせずに実行する場合は、`uv run crwl2md` を使用してください。

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

SPA や認証が必要なサイトでの利用例：

```bash
# 要素の描画を待ってから変換（CSS セレクターまたは js:() => ...）
crwl2md convert https://example.com/app \
  --wait-for "article.doc-content" \
  --scan-full-page \
  -o app.md

crwl2md convert https://example.com/spa \
  --wait-for "js:() => document.querySelectorAll('.doc-item').length > 0" \
  --wait-for-timeout 20

# Playwright の認証状態（storage_state.json）を使ってクロール
crwl2md crawl https://internal.example.com/docs/ \
  -o ./output/internal-docs \
  --storage-state ./auth.json
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
| `--delay <SECONDS>` | `0.1` | 同時取得のまとまりごとに入れる待機秒数（0以上。指定値に最大0.3秒のランダムな揺らぎが加わる）。 |
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
| `--header <NAME:VALUE>` | — | ブラウザの全リクエスト（外部 CDN 等を含む）に付与する追加 HTTP ヘッダー（`Name: Value` 形式、複数回指定可）。認証には `--storage-state` または `--user-data-dir` を推奨。 |
| `--storage-state <PATH>` | — | 認証済みセッションを使うための Playwright `storage_state.json`（Cookie と `localStorage`）。`--user-data-dir` とは併用不可。 |
| `--user-data-dir <PATH>` | — | ログイン済みセッションを再利用する Chromium の永続プロファイルディレクトリ。`--storage-state` とは併用不可。 |
| `--proxy <PROXY>` | — | プロキシサーバー（`http://host:port`、`socks5://host:port`、`http://user:pass@host:port`、`host:port:user:pass` など）。 |
| `--stealth` | — | ステルスモードと navigator の上書きを有効にし、ボット遮断を緩和する。 |
| `--headed` | — | ヘッドレスではなくウィンドウを表示して Chromium を実行する（`--stealth` との併用やデバッグに有用）。 |
| `--wait-for <CONDITION>` | — | HTML 抽出前に待機する条件（CSS セレクターまたは `js:() => ...`）。 |
| `--wait-for-timeout <SECONDS>` | `15`（`--wait-for` 指定時）／`5`（未指定時） | HTML 抽出前の待機タイムアウト秒数（0より大きい値）。`--wait-for` 未指定時も、本文テキストの描画を待つ組み込み判定に適用される。 |
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

このほか、次の公開 API も利用できます。

- 非同期版：`convert_single`、`crawl_site`（既存のイベントループ内から呼ぶ場合に使用します。`crawl_site` / `crawl_site_sync` は進捗通知用の `on_progress` コールバックを受け取れます）
- HTML 文字列からの直接変換：`extract_markdown(html, url=...)`（ブラウザやファイル I/O なしで変換できます）
- ブラウザ導入と例外：`install_browser()`、`BrowserNotInstalledError`

## クロール範囲

既定では、起点 URL と同じホストのうち次の範囲にあるリンクだけを辿ります。画像・CSS・JavaScript・PDF・アーカイブなどの非 HTML アセットは自動的にスキップします。適用する範囲は、開始時に `Crawl scope: ...` として標準エラー出力に表示します。

| 起点 URL | 既定の範囲 |
| --- | --- |
| `https://example.com/docs/intro` | `/docs` 配下（起点と同じディレクトリのページを含む） |
| `https://example.com/docs/` | `/docs` 配下 |
| `https://example.com/docs` | `/docs` 配下 |
| `https://example.com/`、`https://example.com/index.html` | ホスト全体 |

範囲は次のオプションで変更できます。

- `--include`：既定の範囲の代わりに、指定したパターンに一致する URL を範囲にします。別ホストを含む完全 URL パターンを指定すると、そのホストもクロール対象になります。
- `--exclude`：範囲のうち、指定したパターンに一致する URL を除きます。
- `--allow-all-paths`：同一ホスト上の全パスを範囲にします。

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

- 全ページに共通するパスの接頭辞は取り除きます。`/docs/intro` と `/docs/commands/create` をクロールすると、`intro.md` と `commands/create.md` になります。複数ホストにまたがる場合は、ホスト名ごとのディレクトリに分けて保存します。
- 配下にページを持つ URL は、そのディレクトリの `overview.md` になります（`/commands` と `/commands/create` があれば、前者は `commands/overview.md`）。`index.md` は生成する目次のために使います。
- URL のパーセントエンコードはデコードします（`/docs/%E3%81%AF...` は `はじめに.md`）。ファイル名に使えない文字は `_` に置き換えます。
- 出力先が重なる場合は、後から処理したページに `-2`、`-3` の連番を付けます。クエリ文字列だけが異なるページには、クエリのハッシュ値を付けます。
- クロールしたページへのリンクは相対パスの `.md` に、それ以外の相対リンクと画像は絶対 URL に書き換えます。
- 目次の並び順は、起点ページのサイドバーにあるリンクの順序に従います。サイドバーにないページはパスの順に並べます。

### 生成ファイルの例

ルート目次（`index.md`）：

```markdown
# docs.elgato.com Documentation

## Subcategories

- [Commands](commands/index.md) - CLI command reference

## Documents

- [Overview](overview.md) - Stream Deck CLI documentation
- [Introduction](intro.md) - Get started with the Stream Deck CLI
```

YAML フロントマター（`--frontmatter` 指定時）：

```yaml
---
title: "Introduction"
description: "Get started with the Stream Deck CLI"
source: "https://docs.elgato.com/streamdeck/cli/intro"
timestamp: 2026-04-01T00:00:00Z
---
```

### 進捗・結果の報告と終了コード

- クロール中の進捗は標準エラー出力に表示されます（`--no-progress` で抑止可能）。完了時には取得ページ数・目次ファイル数・トップレベルディレクトリごとのページ数を標準出力に表示します。
- 取得に失敗したページ（HTTP 400 番台・500 番台の応答を含む）は保存せず、終了時に URL と理由を標準エラー出力に表示します。リダイレクトで範囲外に出た URL や、上限に達して未取得となったリンクがある場合も同様に警告を表示します。
- Python API では、`CrawlSummary` の `failed_pages`、`skipped_urls`、`seed_redirected_to`、`unfetched_in_scope_links` などから同じ情報を参照できます。
- CLI の終了コードは、1ページ以上を保存できれば `0`（一部ページの失敗があっても `0`）、1ページも保存できない場合や設定エラー時は `1`、中断時（Ctrl+C）は `130` です。

## トラブルシューティング

### `crwl2md` コマンドが見つからない

`uv` でインストールしたあとにコマンドが見つからない場合は、`uv tool update-shell` を実行してシェルを再起動してください。

### Chromium が見つからない・バージョンが一致しない・OS ライブラリが不足している

- `crawl` や `convert <URL>` でブラウザ未導入やバージョン不一致のエラーが出る場合は、`crwl2md setup` を実行してください（パッケージのアップグレード後も再実行が必要です）。
- Linux 環境で `libnss3` などの共有ライブラリ不足が報告される場合は、`crwl2md setup --with-deps` を実行してください（必要に応じて `sudo` が求められます）。

### `HTTP 429`（レート制限）で失敗する

既定では最大5ページを同時に取得し、まとまりごとに 0.1〜0.4 秒待ちます。失敗一覧に `HTTP 429` が出る場合は、次のように同時取得数と間隔を調整して再実行してください。

```bash
crwl2md crawl https://example.com/docs/ -o ./output/docs --delay 2 --concurrency 1
```

### 起点 URL しか取得されない（範囲外へリダイレクトされる）

起点 URL が別のホストやディレクトリへリダイレクトされる場合、クロール範囲はリダイレクト前の URL から決まるため起点ページしか取得できません。終了時にリダイレクト先 URL が警告として表示されるので、その URL を起点に指定して再実行してください。

### ボット対策で遮断される（403 やチャレンジ画面）

`--stealth` を付けて再実行してください。対策が厳しいサイトでは、GUI 環境で `--stealth --headed` を併用するとヘッドレス判定を回避しやすくなります。

### SPA や動的ページで本文が空になる・一部が欠ける

既定では本文コンテナにテキストが描画されるまで最大5秒待機します。それでも本文が空（`Empty page content`）になる場合や一部が欠ける場合は、ページ構造に応じて次を試してください。

- 特定要素の出現を待つ：`--wait-for "CSSセレクター"` または `--wait-for "js:() => ..."`（必要に応じて `--wait-for-timeout` で秒数を延長）
- スクロールしないと読み込まれないコンテンツがある：`--scan-full-page`
- Web Components（Shadow DOM）内に本文がある：`--flatten-shadow-dom`

### 未取得リンクが残る警告が出る

`Warning: N in-scope links were not fetched ...` が表示された場合、既定の `--max-pages 100` や指定した `--max-depth` に達しています。`--max-pages` の上限を上げるか、`--include` / `--exclude` で対象範囲を絞って再実行してください。

### 認証が必要なページを取得できない

ログイン済みセッションの Cookie・`localStorage` を使うには、Playwright の `storage_state.json` を `--storage-state <PATH>` で渡すか、ログイン済みの Chromium プロファイルを `--user-data-dir <PATH>` で指定してください（両者の併用はできません）。

### 出力先ディレクトリが空でないエラーが出る

既存ファイルの上書きを防ぐため、出力先ディレクトリが空でない場合はエラーで終了します。既存の出力先へ再クロールするときは `--force` を指定してください。

## 既知の制限

- **インライン `<svg>` は出力されない**：HTML 内に直接埋め込まれた `<svg>` の図は省略されます（`<img src="...svg">` のような画像要素は絶対 URL として保持されます）。
- **画像はローカルにダウンロードしない**：画像ファイル自体は保存せず、Markdown 内の参照を絶対 URL に書き換えます。
- **HTTP 429 / 503 で拒否されたページは自動再取得しない**：429 または 503 を受け取ると以降の待ち時間は自動的に延びますが、拒否されたページを待ってから取り直すことはしません。
- **`<a href>` を持たない JS 遷移リンクは辿れない**：JavaScript のクリックイベントのみで遷移するページはリンク発見の対象になりません。
- **`--force` は前回の残存ファイルを削除しない**：再クロール時に今回生成されたファイルは上書きされますが、前回のクロールで作られ今回は生成されなかった古いファイルは残ります。
- **既定では `robots.txt` を確認しない**：公開サイトをクロールする場合は、サイトの利用規約を確認し、必要に応じて `--respect-robots` を指定してください。
- **`--header` はブラウザの全リクエストに送信される**：外部 CDN やサードパーティスクリプトにも付与されるため、特定サイト向けの認証には `--storage-state` または `--user-data-dir` の利用を推奨します。

## アンインストール

```bash
uv tool uninstall crwl2md
```

`pipx` や `pip` でインストールした場合は、それぞれ `pipx uninstall crwl2md` または `pip uninstall crwl2md` を実行してください。

`crwl2md` 本体をアンインストールしても、`crwl2md setup` でダウンロードした Playwright の Chromium キャッシュは自動では削除されません。不要であれば次のディレクトリを削除してください（他の Playwright 利用ツールと共有している場合は注意してください）。

- Linux / macOS：`~/.cache/ms-playwright`
- Windows：`%LOCALAPPDATA%\ms-playwright`

## 開発

開発には `mise`・`go-task`（`task`）・`uv` を使用します。

```bash
task setup
```

`task setup` は `mise install`、`uv sync --frozen --reinstall`、`uv run crwl2md setup` を順に実行します。主な開発タスクは次のとおりです。

| タスク | 内容 |
| --- | --- |
| `task setup` | ランタイム・依存パッケージ・Chromium のセットアップ |
| `task format` | TOML・Markdown・Python のフォーマットと自動修正 |
| `task lint` | `tombi`、`markdownlint-cli2`、`ruff`、`pyright` による検査 |
| `task test` | `pytest` によるテストとカバレッジ計測（ブラウザ不要） |

## ライセンス

MIT License（[LICENSE](LICENSE)）

## 謝辞

This product includes software developed by UncleCode (<https://x.com/unclecode>) as part of the Crawl4AI project (<https://github.com/unclecode/crawl4ai>).
