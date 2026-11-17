# web2md

ウェブサイトや HTML をクロールし、目次（`index.md`）付きの Markdown ファイル群へ変換する Python 製 CLI ツールです。

## 使い方

```bash
# 環境構築
task setup

# 単一ページ（URL またはローカル HTML）の変換
uv run web2md convert https://example.com/docs/intro -o intro.md

# ドキュメントサイトのクロールと目次生成（URL パターン指定）
uv run web2md crawl https://docs.elgato.com/streamdeck/cli/intro \
  --include "https://docs.elgato.com/streamdeck/cli/**" \
  -o ./output/streamdeck-cli
```

Python API 例:

```python
from web2md import crawl_site_sync

summary = crawl_site_sync(
    "https://docs.elgato.com/streamdeck/cli/intro",
    "output/streamdeck-cli",
    include_patterns=["https://docs.elgato.com/streamdeck/cli/**"],
)
```

## 開発

```bash
task format
task lint
task test
```
