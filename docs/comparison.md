# 手法の比較検証結果

`crwl2md` の抽出手法および目次（`index.md`）生成手法について、ローカルフィクスチャと実サイト（`https://docs.elgato.com/streamdeck/cli/**`）で比較検証した記録。

## 1. 実サイトでの比較検証（Elgato Stream Deck CLI ドキュメント）

`https://docs.elgato.com/streamdeck/cli/intro` を起点に `https://docs.elgato.com/streamdeck/cli/**`（11ページ＋目次2ファイル）をクロールし、試作段階で検討した4手法（`dom-markdownify`、`crawl4ai`、`readability-lxml`、`trafilatura`）およびブラウザのリーダービュー（Readability.js 系）を比較した。

### 実サイトでの出力比較

| 手法 | `intro.md` サイズ | `commands/create.md` サイズ | 観察された結果 |
| --- | ---: | ---: | --- |
| `dom-markdownify` | 4,026 bytes | 1,730 bytes | パンくず・TOC・ページ送りを除去し、コード言語タグ（`bash` / `text`）と Admonition（引用ブロック）、相対リンクを保持 |
| `crawl4ai`（検証後に削除） | 4,182 bytes | 1,963 bytes | `target_elements=["main"]` によりヘッダーと左サイドバーは除外されたが、`<main>` 内のパンくず・`On this page`・`Previous` / `Next`・ページ内目次アンカーが残存 |
| `readability`（検証後に削除） | 176 bytes | 1,147 bytes | `intro.md` では本文の大半が欠落して1段落のみになり、`commands/create.md` でも `## Synopsis` や `## Description` が脱落 |
| `trafilatura`（検証後に削除） | 3,807 bytes | 1,625 bytes | ナビゲーション除去は良好だが、短いコードブロックがインラインコード化され、出力例内の空行や末尾の `## See also` リンクが欠落 |

### Readability 系（`readability-lxml` / Readability.js）と `trafilatura` の判断

- Python 版 `readability-lxml` だけでなく、Web ブラウザ（Readability.js 系）で同ページを確認した場合でも、Docusaurus のような階層構造では本文の一部が大きく欠落するケースがあった。
- `trafilatura` はニュース・ブログ記事向けには有効だが、技術ドキュメントで重要なコードブロックのフェンス保持や末尾リンクの維持で欠落が出た。
- そのため不要なフォールバック依存（`readability-lxml`、`trafilatura`）は削除した。
- `crawl4ai`（Crawl4AI 標準の Markdown 変換）は、当初は `--method crawl4ai` で選択できる手法として残していた。しかし、`<main>` 内のナビゲーションが残ること、コード言語タグが落ちること、単一ページ変換とサイトクロールで出力が食い違うことから、抽出手法としては削除し、**`dom-markdownify`** に一本化した。クローラーとしての Crawl4AI は引き続き使用する。

## 2. フィクスチャを用いた定量比較

試作時のベンチマークスクリプトにより、3種類の代表 HTML（Docusaurus 技術ドキュメント、`<main>` なしの技術ブログ、定義リストと表を含む API リファレンス）で、`dom-markdownify` と Crawl4AI 標準の Markdown 変換（`<main>` があればその中だけを変換）を比較した。平均時間は、初回呼び出しを除いた20回の平均である。

### Docusaurus 技術ドキュメント（パンくず・サイドバー・TOC・編集リンク・コード言語タグ付き）

| 手法 | 平均時間 (ms) | 文字数 | 必須要素の保持 | ノイズ除去 | 観察された特徴 |
| --- | ---: | ---: | --- | --- | --- |
| `dom-markdownify` | 2.29 | 368 | 4/4 | 完全除去 | `# Actions`、`python` 言語タグ付きコードブロック、`@action`、表をすべて欠落なく保持 |
| `crawl4ai` | 1.06 | 808 | 3/4（言語タグ欠落） | 残存あり | `<main>` 抽出後も `On this page`、`Edit this page`、`Previous Getting Started`、`Copy`、見出しのゼロ幅スペースが残り、コード言語タグが落ちる |

### 技術ブログ・記事ページ（`<main>` なし・`<article>` と関連記事サイドバー）

| 手法 | 平均時間 (ms) | 文字数 | 必須要素の保持 | ノイズ除去 | 観察された特徴 |
| --- | ---: | ---: | --- | --- | --- |
| `dom-markdownify` | 1.12 | 222 | 3/3 | 完全除去 | `<article>` 内のリード文を含め本文をそのまま保持 |
| `crawl4ai` | 0.59 | 387 | 3/3 | 残存あり | ヘッダーのナビゲーション、`Related Posts`、`All rights reserved.` が残る |

### API リファレンス（`<dl>/<dt>/<dd>` 定義リスト・表中心）

| 手法 | 平均時間 (ms) | 文字数 | 必須要素の保持 | ノイズ除去 | 観察された特徴 |
| --- | ---: | ---: | --- | --- | --- |
| `dom-markdownify` | 3.54 | 380 | 3/3 | 対象なし | 定義リスト（`:   ...`）と GFM テーブルを保持 |
| `crawl4ai` | 0.81 | 387 | 3/3 | 対象なし | 定義リストを字下げブロックとして出力し、見出し前後の空行が詰まる |

## 3. 目次（`index.md`）生成手法の比較

4ページ分のドキュメント（`sdk/` 配下3ページと `cli/` 配下1ページ）を対象に比較した。

| 手法 | 内容 | 実測時間 | `sdk/index.md` の出力順 | 特徴 |
| --- | --- | ---: | --- | --- |
| 手法 A | URL パス階層 + ファイル名順 | 0.10 ms | `actions.md`, `getting-started.md`, `settings.md` | 決定的・最速だが学習順（Getting Started が先頭）が崩れる |
| 手法 B | URL パス階層 + サイドバー DOM 順 | 0.37 ms | `getting-started.md`, `actions.md`, `settings.md` | 外部 AI 不要かつミリ秒未満で自然な章立て順を再現 |
| 手法 C（参考検証後に不採用） | ローカル LLM（Ollama `gemma4:12b`） | 9,383.1 ms | 入力順に応じた Markdown リストを生成 | 大量ページや階層分割の安定性・速度面で標準ツールには不向き |

## 4. 最終方針

- **クロールエンジン**：Crawl4AI（`AsyncWebCrawler` + `BFSDeepCrawlStrategy`）を採用する。
- **抽出手法**：`dom-markdownify`（親要素最大3階層の言語クラス検出、Admonition の引用ブロック化、リンク内改行の正規化を含む）のみとする。
- **目次生成**：外部 AI を使わず、URL パス階層 + サイドバー DOM 順 + メタデータ抽出（手法 B）で決定的に生成する。
- **YAML フロントマター**：既定では無効とし、`--frontmatter` または `--frontmatter-fields`（`title`, `description`, `source`, `timestamp` [ISO 8601 UTC]）で出力項目を指定可能とする。
