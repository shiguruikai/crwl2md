# 手法の比較検証結果

`web2md` のプロトタイプ設計にあたり、HTML から Markdown への変換手法および目次（`index.md`）生成手法を [scripts/compare_methods.py](../scripts/compare_methods.py) で実測比較した記録。

## 検証環境と前提

- 実行環境：Python 3.14.10、`crawl4ai 0.9.5`、`beautifulsoup4 4.15.0`、`markdownify 1.2.3`、`readability-lxml 0.9`、`trafilatura 2.3.1`、Ollama（`gemma4:12b`）
- 比較対象：代表的な3種類の HTML フィクスチャ（Docusaurus 技術ドキュメント、`<main>` なしの技術ブログ、定義リストと表を含む API リファレンス）
- 実行コマンド：`uv run python scripts/compare_methods.py --dump` および `uv run python scripts/compare_methods.py --with-ollama`

## 1. HTML → Markdown 変換手法の比較

### 実測結果

#### Docusaurus 技術ドキュメント（パンくず・サイドバー・TOC・編集リンク・コード言語タグ付き）

| 手法 | 平均時間 (ms) | 文字数 | 必須要素の保持 | ノイズ除去 | 観察された特徴 |
| --- | ---: | ---: | --- | --- | --- |
| `dom-markdownify` | 13.65 | 368 | 4/4 | 完全除去 | `# Actions`、`python` 言語タグ付きコードブロック、`@action`、表をすべて欠落なく保持 |
| `crawl4ai` | 0.62 | 960 | 3/4（言語タグ欠落） | 残存あり | 生の HTML 入力時はヘッダー・サイドバー・`Copy`・`Edit this page` 等が残り、コード言語タグが落ちる |
| `readability` | 4.54 | 382 | 4/4 | 完全除去 | 見出しが `<title>` 由来の `# Actions \| Example SDK` に置き換わる |
| `trafilatura` | 1.79 | 356 | 3/4（言語タグ欠落） | 完全除去 | ノイズ除去は正確だが、コード言語タグとコードブロック内の空行が失われる |

#### 技術ブログ・記事ページ（`<main>` なし・`<article>` と関連記事サイドバー）

| 手法 | 平均時間 (ms) | 文字数 | 必須要素の保持 | ノイズ除去 | 観察された特徴 |
| --- | ---: | ---: | --- | --- | --- |
| `dom-markdownify` | 1.13 | 222 | 3/3 | 完全除去 | `<article>` 内のリード文を含め本文をそのまま保持 |
| `crawl4ai` | 0.35 | 311 | 3/3 | 残存あり | `Related Posts` や `All rights reserved.` が末尾に残る |
| `readability` | 1.77 | 184 | 3/3 | 完全除去 | `<article>` 先頭の `<header>` 内にあるリード文（`<p class="lead">`）が欠落 |
| `trafilatura` | 16.55 | 222 | 3/3 | 完全除去 | 本文・見出しを過不足なく抽出 |

#### API リファレンス（`<dl>/<dt>/<dd>` 定義リスト・表中心）

| 手法 | 平均時間 (ms) | 文字数 | 必須要素の保持 | ノイズ除去 | 観察された特徴 |
| --- | ---: | ---: | --- | --- | --- |
| `dom-markdownify` | 2.48 | 380 | 3/3 | 対象なし | 定義リスト（`:   ...`）と GFM テーブルを保持 |
| `crawl4ai` | 0.33 | 377 | 3/3 | 対象なし | 定義リストを字下げブロックとして出力し、見出し前後の空行が詰まる |
| `readability` | 3.16 | 380 | 3/3 | 対象なし | `dom-markdownify` と同等の出力 |
| `trafilatura` | 1.30 | 373 | 3/3 | 対象なし | 定義リストがフラットな箇条書き（`-`）へ変換される |

### Readability.js（Node.js）の検討結果

- ユーザー案にある `Node.js` + `pnpm` + `Readability.js`（`@mozilla/readability` + `jsdom` + `turndown`）は、Python 側の `readability-lxml` と同系統のスコアリング型本文抽出アルゴリズムである。
- 実測から分かったとおり、Readability 系アルゴリズムは技術ドキュメントの `<header>` 内要素やリード文・サイト固有のコードブロック構造を落とす場合があり、さらに Node.js サブプロセス起動とランタイム二重管理のコストが発生する。
- そのためプロトタイプでは Python 単一ランタイムに統一し、DOM ベースの `dom-markdownify` を既定手法とした。

### 変換手法の結論

- **クロールエンジン**：JavaScript 描画や幅優先クロール（`BFSDeepCrawlStrategy`）、ドメイン・URL フィルタリングに優れる **Crawl4AI**（`AsyncWebCrawler`）を採用する。
- **HTML → Markdown 変換の既定手法**：技術ドキュメントで重要なコード言語タグ・定義リスト・表・`<h1>` を維持しつつナビゲーションノイズを確実に除去できる **`dom-markdownify`** を既定とする。
- **代替手法の併用**：ブログ・ニュース系の汎用記事には `trafilatura` や `readability`、Crawl4AI 標準変換を比較・切替できるよう `--method` オプションとして残した。

## 2. 目次（`index.md`）生成手法の比較

### 各手法の仕組みと実測結果

4ページ分のドキュメント（`sdk/` 配下3ページと `cli/` 配下1ページ）を対象に、3つの手法を比較した。

| 手法 | 内容 | 実測時間 | `sdk/index.md` の出力順 | 特徴 |
| --- | --- | ---: | --- | --- |
| 手法 A | URL パス階層 + ファイル名順 | 0.13 ms | `actions.md`, `getting-started.md`, `settings.md` | 決定的・最速だが学習順（Getting Started が先頭）が崩れる |
| 手法 B | URL パス階層 + サイドバー DOM 順 | 0.71 ms | `getting-started.md`, `actions.md`, `settings.md` | 外部 AI 不要かつミリ秒未満で自然な章立て順を再現 |
| 手法 C | ローカル LLM（Ollama `gemma4:12b`） | 9,383.1 ms | 入力順に応じた Markdown リストを生成（全パス保持） | 意味的な整理や要約が可能だが低速で、大規模階層には不向き |

### 目次生成の結論

- **標準方式（外部 AI 非依存）**：**手法 B（URL パス階層 + サイドバー DOM 順 + `<meta description>` / 冒頭段落抽出）**を採用する。ハルシネーションやリンク切れが起きず、既存のサイト構造を高速・決定的に再構成できる。
- **AI 補助（Ollama / `agy` / `claude`）の使い分け**：複数の異なるドメインを統合してテーマ別に再分類したい場合や、英語ページの概要を日本語化して精選したい場合など、機械的ルールだけでは判断が難しい仕上げ工程で必要に応じて併用する位置づけとする。
