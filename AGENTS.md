# AGENTS.md

## プロジェクト概要

ウェブサイトをクロールして Markdown ファイルに変換するための Python 製 CLI ツール。

こんなときに使う:

- HTML を Markdown に変換したい
- ウェブ上で公開されている技術系ドキュメントをクロールし、目次を含む Markdown ファイル群に変換したい

## 技術スタック

- Python 3.14, uv, mise, go-task（`task`）
- Crawl4AI（Playwright ベースの取得・深さクロール）
- BeautifulSoup4 + lxml + markdownify（既定の `dom-markdownify` 抽出）
- readability-lxml, trafilatura, httpx, pydantic（比較・代替抽出および設定モデル）
- ruff, pyright, pytest, pytest-asyncio, tombi, markdownlint-cli2

## コマンド

- 定型操作は [Taskfile.yml](Taskfile.yml) に集約し、`task <TASK>` で実行する。
  - `task setup`: `mise install` と `uv sync --frozen --reinstall` を実行する。
  - `task format`: `tombi format`, `markdownlint-cli2 --fix`, `ruff check --fix`, `ruff format` を実行する。
  - `task lint`: `tombi lint`, `markdownlint-cli2`, `ruff check`, `ruff format --check`, `pyright` を実行する。
  - `task test`: `uv run pytest` を実行する。
- CLI 実行例:
  - `uv run web2md convert <URLまたはHTMLファイル> [-o OUTPUT] [--method dom-markdownify|crawl4ai|readability|trafilatura] [--frontmatter]`
  - `uv run web2md crawl <URL> -o <出力ディレクトリ> [--max-depth 2] [--max-pages 100] [--method ...] [--frontmatter]`
- 手法比較ベンチマーク:
  - `uv run python scripts/compare_methods.py [--with-ollama] [--dump]`

## 構成

- [src/web2md/extractors.py](src/web2md/extractors.py): HTML→Markdown 変換（`dom-markdownify`, `crawl4ai`, `readability`, `trafilatura`）、メタデータ抽出、サイドバーリンク抽出
- [src/web2md/site_builder.py](src/web2md/site_builder.py): URL→相対パス設計、Markdown 内の相対リンク書き換え、階層目次（`index.md`）生成
- [src/web2md/crawler.py](src/web2md/crawler.py): 単一ページ変換（`convert_single`）および Crawl4AI によるサイトクロール（`crawl_site`）
- [src/web2md/cli.py](src/web2md/cli.py): `web2md` CLI エントリポイント
- [docs/comparison.md](docs/comparison.md): 各変換手法・目次生成手法の実測比較結果

## 開発ルール

- 変更後は `task format`, `task lint`, `task test` がすべて成功することを確認する。
- テストは AAA（Arrange-Act-Assert）パターンで記述し、ネットワーク依存のテストにはフェイクまたはモックを用いる。
- コミットは Conventional Commits 形式（`<type>: <日本語の簡潔な概要>`）で署名付きとする。
