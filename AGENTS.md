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
- 抽出結果と目次生成のベンチマークは [scripts/compare_methods.py](scripts/compare_methods.py) を `uv run python` で実行する。

## 構成

- [src/web2md/\_\_init\_\_.py](src/web2md/__init__.py): 公開 API のエクスポート
- [src/web2md/extractors.py](src/web2md/extractors.py): HTML→Markdown 変換（本文コンテナの選択、不要要素の除去、markdownify による変換）、メタデータ抽出、サイドバーリンク抽出
- [src/web2md/markdown_code.py](src/web2md/markdown_code.py): Markdown のフェンス付きコードブロックとインラインコードの判定（後処理やリンク書き換えの対象から外すために使う）
- [src/web2md/site_builder.py](src/web2md/site_builder.py): URL→相対パス設計、Markdown 内の相対リンク書き換え、YAML フロントマター生成、階層目次（`index.md`）生成
- [src/web2md/crawler.py](src/web2md/crawler.py): 単一ページ変換（`convert_single`）および Crawl4AI によるサイトクロール（`crawl_site`, `crawl_site_sync`）
- [src/web2md/cli.py](src/web2md/cli.py): `web2md` CLI エントリポイント
- [docs/comparison.md](docs/comparison.md): 各変換手法・目次生成手法の検証結果

## Crawl4AI 側の不具合・仕様と対処

`crawl4ai` は 0.9 系に固定している（[pyproject.toml](pyproject.toml)）。次の表は、0.9.5 で確認した Crawl4AI 側の挙動と、web2md 側の対処である。上限を上げるときは、各項目の挙動が変わっていないかを実クロールで確認し、不要になった対処は削除する。

| Crawl4AI の挙動 | web2md 側の対処 |
| --- | --- |
| `BFSDeepCrawlStrategy.can_process_url` が、ドットを含まないホスト（`localhost` など）の URL を不正として拒否する。 | `_LinkFollowingBFSStrategy` で判定を上書きしている。直っていればこのクラスは削除できる。 |
| `DomainFilter` は、URL からポートを除いたホスト名を取り出して比較する。 | `allowed_domains` には `netloc` ではなく `hostname` を渡す。 |
| HTTP 404 や 500 のページも `success=True` で返す。リダイレクトされたページの `status_code` は 302 のままになる。 | `_triage_results` で `status_code` が 400 以上の結果を失敗として扱う。 |
| 約100バイト未満の HTML は、HTTP 200 でも「Near-empty content」としてボット遮断（`success=False`）と判定する。 | 対処していない。失敗の一覧に理由が表示される。 |
| 429 を受け取ったページは、直後に1回だけ再試行される（`max_retries=1` の指定による）。待機はなく、`Retry-After` は無視される。内部の RateLimiter は以降のリクエスト間隔を延ばすだけで、拒否されたページを取り直さない。 | 対処していない。README で `--delay` と `--concurrency` による回避を案内している。 |
| `mean_delay` の待機は、リクエストごとではなく、同時取得のまとまり（`semaphore_count` 件）ごとに入る。 | `--delay` のヘルプと README にその旨を書いている。 |
| `arun` の戻り値は、`CrawlResult`、`CrawlResultContainer`、それらのリストのいずれかになる。 | `_flatten_crawl_results` で平坦化する。 |
| `URLPatternFilter` は、`**` を含む文字列を `fnmatch` で解釈する（既存のコードコメントによる。0.9.5 では未検証）。 | `compile_url_pattern` で正規表現にしてから渡す。 |
| 初回のクロール時とボット遮断の検出時に、宣伝のバナーを表示する。 | `crawl_site` がブラウザを起動する前に、環境変数 `CRAWL4AI_NO_CLOUD_NOTICE=1` を設定して抑止する（利用者が明示的に設定した値は上書きしない）。 |

## 開発ルール

- **ソースコメント**: コメントは英語で記述し、コードを見れば分かる自明なコメントは書かない。公開 API（公開クラス・公開関数）には簡潔な英語 docstring を記述する。
- **検証**: 変更後は `task format`, `task lint`, `task test` がすべて成功することを確認する。
- **テスト**: AAA（Arrange-Act-Assert）パターンで記述し、ネットワーク依存のテストにはフェイクまたはモックを用いる。
- **コミット**: Conventional Commits 形式（`<type>: <日本語の簡潔な概要>`）で署名付きとする。
