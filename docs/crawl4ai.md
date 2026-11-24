# Crawl4AI 側の不具合・仕様と対処

`crawl4ai` は 0.9 系に固定している（[pyproject.toml](../pyproject.toml)）。次の表は、0.9.6 で確認した Crawl4AI 側の挙動と、crwl2md 側の対処である。上限を上げるときは、各項目の挙動が変わっていないかを実クロールで確認し、不要になった対処は削除する。

| Crawl4AI の挙動 | crwl2md 側の対処 |
| --- | --- |
| `BFSDeepCrawlStrategy.can_process_url` が、ドットを含まないホスト（`localhost` など）の URL を不正として拒否する。 | `_LinkFollowingBFSStrategy` で判定を上書きしている。 |
| `BFSDeepCrawlStrategy._arun_batch` が `visited` に開始 URL やリダイレクト先 URL を登録せず重複取得する。また HTTP 404/500 の結果も `max_pages` に算入してリンクをたどり、`link_discovery` は `max_pages` 上限で切り捨てた URL も `visited` に登録する。`_arun_stream` は `max_pages` 件目の結果を `yield` 前に破棄する。 | `_LinkFollowingBFSStrategy` の `_arun_batch` と `link_discovery` で各 BFS 深さを `arun_many(..., stream=True)` でストリーミング受信しつつ、結果順を元の URL 順へ戻してから次深さを探索する。また `visited` にはリダイレクト先と実際に次深さへ採用した URL のみ登録し、スコープ内で HTTP 400 未満の成功ページのみ `max_pages` に算入する（ただし開始 URL `depth == 0` が 404 ページでもサイドバー等から配下リンクを発見できるよう `depth == 0` のみリンク探索を許可する）。 |
| `DomainFilter` は、URL からポートを除いたホスト名を取り出して比較する。 | `allowed_domains` には `netloc` ではなく `hostname` を渡す。 |
| HTTP 404 や 500 のページも `success=True` で返す。リダイレクトされたページの `status_code` は最初の 301/302 のままになり、最終ページのステータスは `redirected_status_code` に入る。 | `_effective_status_code`（`redirected_status_code` を優先）が 400 以上の結果を失敗として扱う。 |
| 約100バイト未満の HTML は、HTTP 200 でも「Near-empty content」としてボット遮断（`success=False`）と判定する。 | 対処していない。失敗の一覧に理由が表示される。 |
| 429 を受け取ったページは、直後に1回だけ再試行される（`max_retries=1` の指定による）。待機はなく、`Retry-After` は無視される。内部の RateLimiter は以降のリクエスト間隔を延ばすだけで、拒否されたページを取り直さない。 | 対処していない。README で `--delay` と `--concurrency` による回避を案内している。 |
| `mean_delay` の待機は、リクエストごとではなく、同時取得のまとまり（`semaphore_count` 件）ごとに入る。 | `--delay` のヘルプと README にその旨を書いている。 |
| `arun` の戻り値は、`CrawlResult`、`CrawlResultContainer`、それらのリストのいずれかになる。 | `_flatten_crawl_results` で平坦化する。 |
| `URLPatternFilter` は、`**` を含む文字列を `fnmatch` で解釈する（既存のコードコメントによる。0.9.6 では未検証）。 | `compile_url_pattern` で正規表現にしてから渡す。 |
| 初回のクロール時とボット遮断の検出時に、宣伝のバナーを表示する。 | `crawl_site` がブラウザを起動する前に、環境変数 `CRAWL4AI_NO_CLOUD_NOTICE=1` を設定して抑止する（利用者が明示的に設定した値は上書きしない）。 |
| `flatten_shadow_dom=True` で実行される `js_snippet/flatten_shadow_dom.js` が、テキストノードの `&`・`<`・`>` を HTML エスケープせずに出力するため、本文やコードブロック内の HTML タグ表記やジェネリクス（`<button>`、`</button>` など）が破損する。また Shadow DOM を持たないページでも DOM 全体を再シリアライズする。 | `_ShadowDomCrawlerStrategy` で `config.flatten_shadow_dom` を無効化して Crawl4AI 側のスクリプト実行を回避し、`before_return_html` フックから HTML エスケープ付きの自前シリアライザ（`_FLATTEN_SHADOW_DOM_JS`、Shadow DOM がないページは即座にスキップ）を実行して open Shadow DOM を既定で展開する。`flatten_shadow_dom=True` 指定時のみ `on_page_context_created` フックで closed Shadow DOM を公開する init スクリプトを登録する。 |
| Python 3.14 では、インストール後の初回実行時（バイトコードの生成時）に `SyntaxWarning: 'return' in a 'finally' block` を表示する。 | 対処していない。2回目以降は表示されない。 |
