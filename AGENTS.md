# AGENTS.md

## プロジェクト概要

ウェブサイトをクロールして Markdown ファイルに変換するための Python 製 CLI ツール。

こんなときに使う:

- HTML を Markdown に変換したい
- ウェブ上で公開されている技術系ドキュメントをクロールし、目次を含む Markdown ファイル群に変換したい

## 技術スタック

- **言語・ランタイム**: Python 3.14
- **パッケージ・環境管理**: uv, mise
- **タスクランナー**: go-task（`task`）
- **クローラー・HTTP**: Crawl4AI（Playwright）, httpx
- **HTML 解析・Markdown 変換**: BeautifulSoup4, lxml, markdownify
- **データ検証**: Pydantic
- **リント・フォーマット・型検査**: Ruff, Pyright, tombi, markdownlint-cli2
- **テスト**: pytest, pytest-asyncio

## コマンド

- 定型操作は [Taskfile.yml](Taskfile.yml) に集約しており、`task <TASK>`（`setup`, `format`, `lint`, `test`）で実行する。
- 手法比較ベンチマークは [scripts/compare_methods.py](scripts/compare_methods.py) を `uv run python` で実行する。

## 構成

- [src/web2md/\_\_init\_\_.py](src/web2md/__init__.py): 公開 API のエクスポート
- [src/web2md/extractors.py](src/web2md/extractors.py): HTML→Markdown 変換（`dom-markdownify`, `crawl4ai`）、メタデータ抽出、サイドバーリンク抽出
- [src/web2md/site_builder.py](src/web2md/site_builder.py): URL→相対パス設計、Markdown 内の相対リンク書き換え、YAML フロントマター生成、階層目次（`index.md`）生成
- [src/web2md/crawler.py](src/web2md/crawler.py): 単一ページ変換（`convert_single`）および Crawl4AI によるサイトクロール（`crawl_site`, `crawl_site_sync`）
- [src/web2md/cli.py](src/web2md/cli.py): `web2md` CLI エントリポイント
- [docs/comparison.md](docs/comparison.md): 各変換手法・目次生成手法の検証結果

## 開発ルール

- **ソースコメント**: コメントは英語で記述し、コードを見れば分かる自明なコメントは書かない。公開 API（公開クラス・公開関数）には簡潔な英語 docstring を記述する。
- **検証**: 変更後は `task format`, `task lint`, `task test` がすべて成功することを確認する。
- **テスト**: AAA（Arrange-Act-Assert）パターンで記述し、ネットワーク依存のテストにはフェイクまたはモックを用いる。
- **コミット**: Conventional Commits 形式（`<type>: <日本語の簡潔な概要>`）で署名付きとする。
