#!/usr/bin/env node
/**
 * pandoc が生成した HTML を Chromium で PDF 化（A4・フッターページ番号）。
 * 実行例（一時 npm 後）:
 *   NODE_PATH=/path/to/node_modules node scripts/render_japan_export_spec_pdf.cjs
 */
const fs = require("node:fs");
const path = require("node:path");
const puppeteer = require("puppeteer-core");

const ROOT = path.resolve(__dirname, "..");
const HTML = path.join(ROOT, "docs", ".pdf-build", "JAPAN_EXPORT_MODEL_REFRESH_v1.html");
const PDF = path.join(ROOT, "docs", "JAPAN_EXPORT_MODEL_REFRESH_v1.pdf");

const chromeMac =
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

async function main() {
  if (!fs.existsSync(HTML)) {
    console.error("Missing HTML:", HTML);
    process.exit(1);
  }
  if (!fs.existsSync(chromeMac)) {
    console.error("Chrome not found at:", chromeMac);
    process.exit(1);
  }
  const url = "file://" + HTML;
  const browser = await puppeteer.launch({
    executablePath: chromeMac,
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });
  try {
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: "load", timeout: 120_000 });
    await page.pdf({
      path: PDF,
      format: "A4",
      printBackground: true,
      margin: { top: "14mm", bottom: "20mm", left: "12mm", right: "12mm" },
      displayHeaderFooter: true,
      headerTemplate: "<div></div>",
      footerTemplate:
        '<div style="width:100%;font-size:9px;text-align:center;font-family:Hiragino Sans,Meiryo,sans-serif;color:#444;padding:0 8mm;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    });
    console.log("Wrote", PDF);
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
