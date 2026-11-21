# AGENTS.md

## プロジェクト概要

ウェブサイトをクロールして Markdown ファイルに変換するための Python 製 CLI ツール。

こんなときに使う:

- HTML を Markdown に変換したい
- ウェブ上で公開されている技術系ドキュメントをクロールし、目次を含む Markdown ファイル群に変換したい

## 技術スタック

- **言語・ランタイム**: Python 3.13+（開発環境は 3.14）
- **パッケージ・環境管理**: uv, mise
- **タスクランナー**: go-task（`task`）
- **クローラー・ブラウザ**: Crawl4AI（Playwright）
- **HTML 解析・Markdown 変換**: BeautifulSoup4, lxml, markdownify
- **データ検証**: Pydantic
- **リント・フォーマット・型検査**: Ruff, Pyright, tombi, markdownlint-cli2
- **テスト**: pytest, pytest-asyncio

## コマンド

- 定型操作は [Taskfile.yml](Taskfile.yml) に集約しており、`task <TASK>`（`setup`, `format`, `lint`, `test`）で実行する。
- `crawl` が使う Chromium ブラウザは `uv run crwl2md setup` でダウンロードする（`task setup` に含まれる）。テストはブラウザを使わない。

## 構成

- [src/crwl2md/\_\_init\_\_.py](src/crwl2md/__init__.py): 公開 API のエクスポート
- [src/crwl2md/extractors.py](src/crwl2md/extractors.py): HTML→Markdown 変換（本文コンテナの選択、不要要素の除去、markdownify による変換）、メタデータ抽出、サイドバーリンク抽出
- [src/crwl2md/markdown_code.py](src/crwl2md/markdown_code.py): Markdown のフェンス付きコードブロックとインラインコードの判定（後処理やリンク書き換えの対象から外すために使う）
- [src/crwl2md/site_builder.py](src/crwl2md/site_builder.py): URL→相対パス設計、Markdown 内の相対リンク書き換え、YAML フロントマター生成、階層目次（`index.md`）生成
- [src/crwl2md/crawler.py](src/crwl2md/crawler.py): 単一ページ変換（`convert_single`, `convert_single_sync`）および Crawl4AI によるサイトクロール（`crawl_site`, `crawl_site_sync`）
- [src/crwl2md/cli.py](src/crwl2md/cli.py): `crwl2md` CLI エントリポイント
- [skills/crwl2md/SKILL.md](skills/crwl2md/SKILL.md): AI エージェント向けの CLI 利用スキル
- [docs/comparison.md](docs/comparison.md): 試作時の各変換手法・目次生成手法の検証結果
- [docs/crawl4ai.md](docs/crawl4ai.md): Crawl4AI の不具合・仕様と crwl2md 側の対処 ※バージョン更新時に再確認する
- [docs/release.md](docs/release.md): リリース手順
- [CHANGELOG.md](CHANGELOG.md): 変更履歴

## 開発ルール

- **ソースコメント**: コメントは英語で記述し、コードを見れば分かる自明なコメントは書かない。公開 API（公開クラス・公開関数）には簡潔な英語 docstring を記述する。
- **検証**: 変更後は `task format lint test` が成功することを確認する。
- **テスト**: AAA（Arrange-Act-Assert）パターンで記述し、ネットワーク依存のテストにはフェイクまたはモックを用いる。
- **スキル**: CLI のサブコマンドや出力仕様を変更したときは、[skills/crwl2md/SKILL.md](skills/crwl2md/SKILL.md) の記述も合わせて更新する。
- **チェンジログ**: [CHANGELOG.md](CHANGELOG.md) は [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) 形式（英語）で管理する。利用者に影響する変更を加えたときは、`## [Unreleased]` 配下の該当セクション（`Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` / `Security`）に簡潔な1行で追記する（リファクタリング・テスト・内部ドキュメントのみの変更は記載しない）。
- **コミット**: [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 形式（`<type>: <日本語の簡潔な概要>`）に従い、適切な粒度でコミット。
- **リリース**: [docs/release.md](docs/release.md) に従う。`git push`、`gh release create`、`gh workflow run publish.yml` は明示的な指示なしに実行しない。
