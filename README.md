# web2md

ウェブサイトや HTML をクロールし、目次（`index.md`）付きの Markdown ファイル群へ変換する Python 製 CLI ツールです。

## 使い方

```bash
# 環境構築
task setup

# 単一ページ（URL またはローカル HTML）の変換
uv run web2md convert https://example.com/docs/intro -o intro.md

# ドキュメントサイトのクロールと目次生成
uv run web2md crawl https://example.com/docs/ -o ./output/docs --max-depth 2
```

## 開発

```bash
task format
task lint
task test
```
