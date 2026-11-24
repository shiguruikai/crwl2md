# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-24

### Changed

- Flatten open Shadow DOM trees automatically by default; keep `--flatten-shadow-dom` / `flatten_shadow_dom=True` to also expose and flatten closed Shadow DOM trees.

### Fixed

- Fix `--flatten-shadow-dom` corrupting HTML tag literals and `<`, `>`, `&` characters in text and code blocks due to unescaped text-node serialization in Crawl4AI.
- Strip Microsoft Learn header action bars, popover menus, code block headers, hidden boilerplate, and feedback footers, and convert `.alert` callouts to blockquotes.
- Suppress Crawl4AI's compile-time `SyntaxWarning` (`'return' in a 'finally' block` in `crawl4ai/content_scraping_strategy.py`) on Python 3.14+ during CLI execution.

### Security

- Raise dependency floors to `crawl4ai>=0.9.6` and `playwright>=1.64.1` to include Crawl4AI 0.9.6 security fixes (CVE-2026-111497).

## [0.1.0] - 2026-11-21

### Added

- CLI commands `setup`, `convert`, and `crawl` (also invocable via `python -m crwl2md`).
- DOM-based HTML-to-Markdown extraction targeting main content on Docusaurus, MkDocs Material, VitePress, MDN, Qiita, Zenn, and generic sites, preserving code fence languages, admonitions, ARIA tab panels, KaTeX math, GFM task lists, `<details>` elements, tables, and definition lists.
- Site crawling powered by Crawl4AI (Playwright / Chromium) with BFS scope filtering (`--include`, `--exclude`, `--allow-all-paths`, `--max-depth`, `--max-pages`), rate control (`--delay`, `--concurrency`), `--respect-robots`, authentication (`--storage-state`, `--user-data-dir`, `--header`), `--proxy`, `--stealth`, `--headed`, `--wait-for`, `--wait-for-timeout`, `--scan-full-page`, and `--flatten-shadow-dom`.
- Internal link rewriting to relative `.md` paths, hierarchical `index.md` TOC generation ordered by sidebar DOM, and optional YAML frontmatter (`--frontmatter`, `--frontmatter-fields`).
- Public Python API (`extract_markdown`, `convert_single`, `convert_single_sync`, `crawl_site`, `crawl_site_sync`, `CrawlConfig`, `CrawlSummary`, `install_browser`, `BrowserNotInstalledError`).
- Agent Skill for AI coding agents in `skills/crwl2md/SKILL.md`.

[unreleased]: https://github.com/shiguruikai/crwl2md/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/shiguruikai/crwl2md/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/shiguruikai/crwl2md/releases/tag/v0.1.0
