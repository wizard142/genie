const { chromium } = require('/home/claude/.npm-global/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await b.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: { dir: '/home/claude/genie/rec', size: { width: 1280, height: 720 } },
  });
  const p = await ctx.newPage();
  await p.goto('file:///home/claude/genie/promo.html');
  // wait until the animation signals done (max 60s safety)
  await p.waitForFunction('window.__done === true', { timeout: 60000 }).catch(()=>{});
  const events = await p.evaluate('window.__ev');
  require('fs').writeFileSync('/home/claude/genie/events.json', JSON.stringify(events));
  await p.waitForTimeout(300);
  const video = p.video();
  await ctx.close();          // flushes/finishes the webm
  const path = await video.path();
  console.log('VIDEO:' + path);
  console.log('EVENTS:' + events.length);
  await b.close();
})();
