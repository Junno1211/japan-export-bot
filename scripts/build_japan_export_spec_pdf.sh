#!/usr/bin/env bash
# JAPAN_EXPORT_MODEL_REFRESH_v1.md → docs/JAPAN_EXPORT_MODEL_REFRESH_v1.pdf
# 依存: pandoc, Google Chrome (macOS), 一時 npm で puppeteer-core（ページ番号付き PDF 用）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MD="$ROOT/docs/JAPAN_EXPORT_MODEL_REFRESH_v1.md"
CSS="$ROOT/docs/assets/japan-export-spec-print.css"
HTMLDIR="$ROOT/docs/.pdf-build"
HTML="$HTMLDIR/JAPAN_EXPORT_MODEL_REFRESH_v1.html"
PDF="$ROOT/docs/JAPAN_EXPORT_MODEL_REFRESH_v1.pdf"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

mkdir -p "$HTMLDIR"
pandoc "$MD" -f markdown-smart -t html5 --standalone --embed-resources \
  --css="$CSS" \
  --metadata title="JAPAN EXPORT 事業モデル刷新仕様書 v1.0" \
  -o "$HTML"

PDFTMP="$(mktemp -d)"
cleanup() { rm -rf "$PDFTMP"; }
trap cleanup EXIT
(
  cd "$PDFTMP"
  npm init -y >/dev/null
  npm install puppeteer-core@24.8.1 >/dev/null
  export NODE_PATH="$PDFTMP/node_modules"
  node "$ROOT/scripts/render_japan_export_spec_pdf.cjs"
)

if [[ ! -f "$PDF" ]]; then
  echo "puppeteer 失敗時のフォールバック: Chrome のみ（フッターページ番号なし）" >&2
  "$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
    --print-to-pdf="$PDF" "file://$HTML"
fi

echo "OK: $PDF"
