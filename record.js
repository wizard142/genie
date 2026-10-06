// Dev-only dependency: Playwright with Chromium. CLI usage: node record.js [output-dir]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
(async () => {
  const output = path.resolve(process.argv[2] || path.join(__dirname, 'rec'));
  fs.mkdirSync(output, { recursive: true });
  const options = { headless: true };
  if (process.env.GENIE_CHROMIUM) options.executablePath = process.env.GENIE_CHROMIUM;
  const browser = await chromium.launch(options);
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 },
      recordVideo: { dir: output, size: { width: 1280, height: 720 } } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent(fs.readFileSync(path.join(__dirname, 'promo.html'), 'utf8'));
    await page.waitForFunction(() => window.__done === true, { timeout: 60000 });
    if (errors.length) throw new Error(errors.join('\n'));
    const events = await page.evaluate(() => window.__ev);
    fs.writeFileSync(path.join(output, 'events.json'), JSON.stringify(events));
    await page.screenshot({ path: path.join(output, 'poster.png') });
    await page.waitForTimeout(300);
    const video = page.video();
    await ctx.close();
    fs.renameSync(await video.path(), path.join(output, 'genie-ad.webm'));
    console.log(`Video: ${path.join(output, 'genie-ad.webm')}; ${events.length} sound events`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
