const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const root = process.env.MOBILE_WEB_ARTIFACTS;
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const results = [];
  try {
    for (const width of [320, 375, 812, 1280]) {
      const page = await browser.newPage({ viewport: { width, height: width === 812 ? 375 : 850 } });
      for (const name of ['dashboard', 'maison-list', 'maison-create', 'maison-detail', 'planning-detail', 'camera-list', 'camera-create', 'camera-detail', 'camera-analysis-update', 'camera-evaluation', 'event-list', 'event-detail', 'camera-monitor', 'connect-camera', 'mfa-setup']) {
        await page.goto('http://127.0.0.1:8001/health/');
        await page.setContent(await fs.readFile(path.join(root, `${name}.html`), 'utf8'), { waitUntil: 'networkidle' });
        const result = await page.evaluate(() => ({
          width: innerWidth,
          overflow: document.documentElement.scrollWidth > innerWidth,
          headingSize: getComputedStyle(document.querySelector('h1')).fontSize,
          tabs: getComputedStyle(document.querySelector('.mobile-tabbar')).display,
          redElements: [...document.querySelectorAll('.badge, .status-pill, .stat-danger, .notice.error')].filter((element) => {
            const color = getComputedStyle(element).color.match(/\d+/g)?.map(Number);
            return color && color[0] > color[1] * 1.5 && color[0] > color[2] * 1.5;
          }).length,
        }));
        results.push({ name, ...result });
        if (width === 375 || (width === 1280 && name === 'dashboard')) {
          await page.screenshot({ path: path.join(root, `${name}-${width}.png`), fullPage: true });
        }
      }
      await page.close();
    }
    const context = await browser.newContext();
    const installPage = await context.newPage();
    await installPage.goto('http://127.0.0.1:8001/connexion/');
    await installPage.evaluate(() => navigator.serviceWorker.ready);
    await installPage.waitForFunction(() => navigator.serviceWorker.controller !== null);
    const cachePaths = await installPage.evaluate(async () => {
      const paths = [];
      for (const key of await caches.keys()) {
        for (const request of await (await caches.open(key)).keys()) paths.push(new URL(request.url).pathname);
      }
      return paths;
    });
    if (cachePaths.length !== 1 || cachePaths[0] !== '/hors-ligne/') throw new Error(`Unexpected cache: ${cachePaths}`);
    await context.setOffline(true);
    await installPage.goto('http://127.0.0.1:8001/tableau-de-bord/');
    if (!(await installPage.locator('body').innerText()).includes('Connexion interrompue')) throw new Error('Missing offline fallback');
    await context.close();
    await fs.writeFile(path.join(root, 'checks.json'), JSON.stringify(results, null, 2));
    const failed = results.filter((result) => result.overflow || (result.width <= 768 && (result.redElements || result.headingSize !== '24px' || result.tabs !== 'grid')));
    console.log(JSON.stringify({ checked: results.length, failed, offlineCache: cachePaths }, null, 2));
    if (failed.length) process.exitCode = 1;
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
