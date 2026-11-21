# リリース手順

バージョニングは [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) に従う。

1. `uv version --bump <patch|minor|major>` でバージョンをインクリメントする。
2. [CHANGELOG.md](../CHANGELOG.md) の `## [Unreleased]` を `## [X.Y.Z] - YYYY-MM-DD` へ移し、空の `## [Unreleased]` と末尾リンクを更新する。
3. `task format lint test` で検証する。
4. `release: vX.Y.Z` のメッセージでコミットし、`master` へプッシュして [CI](../.github/workflows/ci.yml) の通過を確認する。
5. 【任意】`gh workflow run publish.yml` で TestPyPI に公開する。
6. `gh release create vX.Y.Z --generate-notes` で GitHub Release を作成する。公開をトリガーに [publish.yml](../.github/workflows/publish.yml) が自動的に PyPI へパブリッシュする。

## 注意事項

- PyPI および TestPyPI は同一バージョンを再アップロードできない。致命的な不具合は PyPI で Yank または Delete を実行し、修正版を新しい `patch` でリリースする。
