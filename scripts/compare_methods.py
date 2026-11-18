from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from bs4 import BeautifulSoup
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from web2md.extractors import extract_markdown, extract_page_metadata, extract_sidebar_links
from web2md.site_builder import CrawledPageDoc, compute_relative_paths, generate_toc_files


@dataclass(frozen=True)
class HtmlFixture:
    """Representative HTML page fixture for extraction benchmarks."""

    name: str
    url: str
    html: str
    required_snippets: tuple[str, ...]
    noise_snippets: tuple[str, ...]


FIXTURES: tuple[HtmlFixture, ...] = (
    HtmlFixture(
        name="Docusaurus 技術ドキュメント",
        url="https://docs.example.com/docs/sdk/actions",
        html="""
<!DOCTYPE html>
<html lang="en">
<head>
  <title>Actions | Example SDK</title>
  <meta name="description" content="Actions represent the core functionality provided by your plugin." />
</head>
<body>
  <header role="banner"><nav><a href="/">Home</a><a href="/docs/">Docs</a></nav></header>
  <aside class="sidebar"><nav>
    <a href="/docs/sdk/getting-started">Getting Started</a>
    <a href="/docs/sdk/actions">Actions</a>
    <a href="/docs/sdk/settings">Settings</a>
  </nav></aside>
  <main>
    <nav aria-label="Breadcrumbs" class="breadcrumbs"><a href="/">Home</a> / SDK / Actions</nav>
    <article>
      <header><h1>Actions<a class="hash-link" href="#actions">\u200b</a></h1></header>
      <p>Actions represent the core functionality provided by your plugin, and bind events to handlers.</p>
      <h2>Registering an Action<a class="hash-link" href="#registering">\u200b</a></h2>
      <p>Create a class decorated with <code>@action</code> and register it at startup.</p>
      <div class="language-python">
        <pre><code class="language-python">from sdk import action

@action("com.example.counter")
class CounterAction:
    pass</code></pre>
        <button type="button">Copy</button>
      </div>
      <table>
        <thead><tr><th>Method</th><th>Trigger</th></tr></thead>
        <tbody><tr><td><code>on_key_down</code></td><td>Key pressed</td></tr></tbody>
      </table>
    </article>
    <div class="table-of-contents"><a href="#registering">On this page</a></div>
    <a class="theme-edit-this-page" href="https://github.com/org/repo/edit/main/actions.md">Edit this page</a>
    <nav class="pagination-nav">
      <a href="/docs/sdk/getting-started">Previous Getting Started</a>
      <a href="/docs/sdk/settings">Next Settings</a>
    </nav>
  </main>
  <footer>Copyright 2026 Example</footer>
</body>
</html>
""",
        required_snippets=("# Actions", "```python", "@action", "| Method | Trigger |"),
        noise_snippets=("Breadcrumbs", "On this page", "Edit this page", "Previous Getting Started", "\u200b", "Copy"),
    ),
    HtmlFixture(
        name="技術ブログ・記事ページ（main なし・article + 関連記事サイドバー）",
        url="https://tech.example.com/posts/async-crawling",
        html="""
<!DOCTYPE html>
<html lang="ja">
<head>
  <title>非同期クローラーの設計メモ - Tech Blog</title>
  <meta name="description" content="並列クロール時にレート制限と重複排除を両立する設計パターンを解説します。" />
</head>
<body>
  <header><nav><a href="/">Top</a><a href="/posts">Articles</a></nav></header>
  <div class="container">
    <article>
      <header>
        <h1>非同期クローラーの設計メモ</h1>
        <p class="lead">並列クロール時にレート制限と重複排除を両立する設計パターンを解説します。</p>
      </header>
      <p>ドキュメントサイトをクロールする際は、リダイレクト後の最終 URL を正規化して重複取得を防ぐ必要があります。</p>
      <h2>重複排除のポイント</h2>
      <p>末尾スラッシュやフラグメントを統一したうえで、訪問済み集合で管理すると実装が単純になります。</p>
      <p>さらに、ドメインとパスプレフィックスでクロール範囲を絞ることで無関係なページへの発散を防げます。</p>
    </article>
    <aside class="related">
      <h2>Related Posts</h2>
      <ul><li><a href="/posts/other">Other Post</a></li></ul>
    </aside>
  </div>
  <footer>All rights reserved.</footer>
</body>
</html>
""",
        required_snippets=("# 非同期クローラーの設計メモ", "重複排除のポイント", "無関係なページへの発散"),
        noise_snippets=("Related Posts", "Other Post", "All rights reserved"),
    ),
    HtmlFixture(
        name="API リファレンス（定義リスト・表中心）",
        url="https://docs.example.com/docs/api/config",
        html="""
<!DOCTYPE html>
<html lang="en">
<head>
  <title>Configuration Reference | Example SDK</title>
</head>
<body>
  <main>
    <article>
      <h1>Configuration Reference</h1>
      <p>Use <code>CrawlConfig</code> to customize depth, filters, and output layout.</p>
      <h2>Parameters</h2>
      <dl>
        <dt><code>max_depth</code></dt>
        <dd>Maximum link depth from the seed URL. Defaults to <code>2</code>.</dd>
        <dt><code>max_pages</code></dt>
        <dd>Maximum total pages to fetch in one run. Defaults to <code>100</code>.</dd>
      </dl>
      <table>
        <thead><tr><th>Flag</th><th>Type</th><th>Default</th></tr></thead>
        <tbody>
          <tr><td><code>--method</code></td><td>string</td><td>dom-markdownify</td></tr>
          <tr><td><code>--frontmatter</code></td><td>bool</td><td>false</td></tr>
        </tbody>
      </table>
    </article>
  </main>
</body>
</html>
""",
        required_snippets=("# Configuration Reference", "max_depth", "| Flag | Type | Default |"),
        noise_snippets=(),
    ),
)


def convert_with_crawl4ai(html: str, url: str) -> str:
    """Reference conversion using Crawl4AI's default Markdown generator, limited to <main> when present."""
    main_el = BeautifulSoup(html, "lxml").select_one("main")
    target_html = str(main_el) if main_el is not None else html
    result = DefaultMarkdownGenerator().generate_markdown(input_html=target_html, base_url=url, citations=False)
    return result.raw_markdown.strip()


# web2md's extractor compared against the Crawl4AI conversion that it was chosen over.
CONVERTERS: dict[str, Callable[[str, str], str]] = {
    "dom-markdownify": extract_markdown,
    "crawl4ai": convert_with_crawl4ai,
}


def benchmark_extractors(iterations: int = 5, dump: bool = False) -> None:
    """Run HTML-to-Markdown extraction benchmarks across all fixtures."""
    print("## HTML → Markdown 抽出手法の比較\n")
    for fixture in FIXTURES:
        print(f"### {fixture.name}")
        print("| 手法 | 平均時間 (ms) | 文字数 | 必須要素の保持 | ノイズ除去 |")
        print("| --- | ---: | ---: | --- | --- |")

        outputs: dict[str, str] = {}
        for method, convert in CONVERTERS.items():
            # The first call pays one-off costs (selector compilation, lazy imports), so keep it out of the timing.
            md = convert(fixture.html, fixture.url)
            start = time.perf_counter()
            for _ in range(iterations):
                md = convert(fixture.html, fixture.url)
            elapsed_ms = (time.perf_counter() - start) * 1000 / iterations
            outputs[method] = md

            kept = [s for s in fixture.required_snippets if s in md]
            leaked = [s for s in fixture.noise_snippets if s in md]
            kept_str = f"{len(kept)}/{len(fixture.required_snippets)}"
            if len(kept) < len(fixture.required_snippets):
                missing = [s for s in fixture.required_snippets if s not in md]
                kept_str += f" (欠落: {', '.join(missing)})"

            if fixture.noise_snippets:
                noise_str = "完全除去" if not leaked else f"残存: {', '.join(leaked)}"
            else:
                noise_str = "対象なし"

            print(f"| `{method}` | {elapsed_ms:.2f} | {len(md)} | {kept_str} | {noise_str} |")
        if dump:
            for method, md in outputs.items():
                print(f"\n#### 出力サンプル: `{method}`\n```markdown\n{md}\n```")
        print()


def _extract_order_from_toc(toc_md: str) -> list[str]:
    return [line.split("](")[1].split(")")[0] for line in toc_md.splitlines() if line.startswith("- [")]


def benchmark_toc_generation() -> None:
    """Compare URL-order vs sidebar-DOM-order TOC generation."""
    print("## 目次（index.md）生成手法の比較\n")
    seed_url = "https://docs.example.com/docs/sdk/getting-started"
    # Intentionally supply pages out of sidebar order to verify DOM ordering takes precedence.
    sample_pages = [
        (
            "https://docs.example.com/docs/sdk/settings",
            "Settings",
            "Persist plugin settings across restarts.",
        ),
        (
            "https://docs.example.com/docs/sdk/actions",
            "Actions",
            "Core handlers triggered by user interactions.",
        ),
        (
            "https://docs.example.com/docs/sdk/getting-started",
            "Getting Started",
            "Install tools and create your first project.",
        ),
        (
            "https://docs.example.com/docs/cli/intro",
            "CLI Introduction",
            "Command line utilities for building and packaging.",
        ),
    ]
    sidebar_html = """
    <html><body><aside><nav>
      <a href="/docs/sdk/getting-started">Getting Started</a>
      <a href="/docs/sdk/actions">Actions</a>
      <a href="/docs/sdk/settings">Settings</a>
      <a href="/docs/cli/intro">CLI Introduction</a>
    </nav></aside></body></html>
    """
    urls = [item[0] for item in sample_pages]
    url_to_relpath = compute_relative_paths(urls, seed_url)
    docs = [
        CrawledPageDoc(
            url=url,
            relpath=url_to_relpath[url],
            title=title,
            description=desc,
            markdown=f"# {title}\n\n{desc}\n",
        )
        for url, title, desc in sample_pages
    ]

    t0 = time.perf_counter()
    toc_a = generate_toc_files(docs, nav_order=(), root_title="Example SDK")
    ms_a = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    nav_order = extract_sidebar_links(sidebar_html, seed_url)
    toc_b = generate_toc_files(docs, nav_order=nav_order, root_title="Example SDK")
    ms_b = (time.perf_counter() - t1) * 1000

    print(
        f"- 手法 A（URL パス階層 + ファイル名順）: {ms_a:.2f} ms -> sdk 配下順序: {_extract_order_from_toc(toc_a['sdk/index.md'])}"
    )
    print(
        f"- 手法 B（URL パス階層 + サイドバー DOM 順）: {ms_b:.2f} ms -> sdk 配下順序: {_extract_order_from_toc(toc_b['sdk/index.md'])}"
    )


def benchmark_metadata_extraction() -> None:
    """Print extracted page metadata samples across fixtures."""
    print("\n## メタデータ抽出サンプル\n")
    for fixture in FIXTURES:
        md = extract_markdown(fixture.html, url=fixture.url)
        meta = extract_page_metadata(fixture.html, md)
        print(f"- {fixture.name}: {json.dumps(meta.model_dump(), ensure_ascii=False)}")


def main() -> None:
    """CLI entrypoint for running method comparison benchmarks."""
    parser = argparse.ArgumentParser(description="Compare HTML-to-Markdown and TOC generation methods.")
    parser.add_argument("--iterations", type=int, default=5, help="Benchmark iterations per fixture (default: 5).")
    parser.add_argument("--dump", action="store_true", help="Print full extracted Markdown samples for inspection.")
    args = parser.parse_args()

    benchmark_extractors(iterations=args.iterations, dump=args.dump)
    benchmark_toc_generation()
    benchmark_metadata_extraction()


if __name__ == "__main__":
    main()
