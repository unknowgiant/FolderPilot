// 皮肤专项检查：逐个切换 10 套主题，截图 + 校验变量、壁纸、对比度是否真正生效
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, 'output');
fs.mkdirSync(OUT, {recursive: true});
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/unkno/.workbuddy/binaries/node/workspace/node_modules/playwright-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const urlFile = path.join(__dirname, '.server_url');
const reachable = async u => { try { const r = await fetch(u, {signal: AbortSignal.timeout(800)}); return r.ok; } catch { return false; } };
let srv = null;
if (!fs.existsSync(urlFile) || !(await reachable(fs.readFileSync(urlFile, 'utf-8').trim()))) {
  srv = spawn('py', ['-3.14', path.join(__dirname, 'serve.py')], {stdio: 'ignore'});
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 150));
    if (fs.existsSync(urlFile) && await reachable(fs.readFileSync(urlFile, 'utf-8').trim())) break;
  }
}
const base = fs.readFileSync(urlFile, 'utf-8').trim();
const browser = await chromium.launch({executablePath: CHROME, headless: true});
const page = await browser.newPage({viewport: {width: 1280, height: 800}});
const errs = [];
page.on('pageerror', e => errs.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
page.on('response', r => { if (r.status() >= 400) errs.push(r.status() + ' ' + r.url()); });
await page.goto(base + '?demo=1', {waitUntil: 'domcontentloaded'});
await page.waitForSelector('body[data-ready="1"]', {timeout: 20000});

const meta = await page.evaluate(async () => {
  const m = await import('./js/skins.js');
  return m.SKINS.map(s => ({key: s.key, name: s.name, scheme: s.scheme, wall: s.wall, acc: s.acc}));
});
const rows = [];
const checks = [];
const check = (name, ok, note = '') => checks.push({name, ok, note});
// 从 computed 的 rgb()/rgba() 里取透明度
const alphaOf = c => { const m = String(c).match(/[\d.]+/g) || []; return m.length >= 4 ? +m[3] : 1; };

const probe = () => page.evaluate(() => {
  const cs = getComputedStyle(document.documentElement);
  const rgb = h => {
    h = String(h).trim();
    if (h.startsWith('#')) {
      let x = h.slice(1);
      if (x.length === 3) x = x.split('').map(c => c + c).join('');
      return [parseInt(x.slice(0, 2), 16), parseInt(x.slice(2, 4), 16), parseInt(x.slice(4, 6), 16)];
    }
    const m = h.match(/[\d.]+/g) || [0, 0, 0];
    return [+m[0], +m[1], +m[2]];
  };
  const lum = c => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => {
    const la = lum(rgb(a)), lb = lum(rgb(b));
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  // 壁纸独立成层（body::before），body 自身背景已让位给 html
  const bgImage = getComputedStyle(document.body, '::before').backgroundImage
    || getComputedStyle(document.body).backgroundImage;
  return {
    skin: document.documentElement.dataset.skin,
    theme: document.documentElement.dataset.theme,
    wallpaper: document.documentElement.dataset.wallpaper,
    acc: cs.getPropertyValue('--acc').trim(),
    bg: cs.getPropertyValue('--bg').trim(),
    tx: cs.getPropertyValue('--tx').trim(),
    panel: cs.getPropertyValue('--panel').trim(),
    chrome: cs.getPropertyValue('--chrome').trim(),
    paneBg: cs.getPropertyValue('--pane-bg').trim(),
    hasWall: /skins\/[\w-]+\.webp/.test(bgImage),
    wallName: (bgImage.match(/skins\/[\w-]+\.webp/) || [''])[0],
    contrast: +ratio(cs.getPropertyValue('--tx').trim(), cs.getPropertyValue('--panel').trim()).toFixed(2),
    topbarBg: getComputedStyle(document.querySelector('.topbar')).backgroundColor,
    // 内容区容器与窗格的实际底色：容器若是实色，壁纸会被整块挡在侧栏一侧
    panesColor: getComputedStyle(document.querySelector('#panes')).backgroundColor,
    paneColor: getComputedStyle(document.querySelector('.pane')).backgroundColor,
  };
});

for (const s of meta) {
  await page.click('#btn-theme');
  await page.waitForSelector('.skin-card', {timeout: 5000});
  if (s.key === 'default') {
    await page.waitForTimeout(400);
    await page.screenshot({path: path.join(OUT, 'skin_modal.png')});
    await page.waitForTimeout(120);
  }
  await page.click(`.skin-card[data-skin="${s.key}"]`);
  await page.waitForTimeout(260);
  const v = await probe();
  const onCards = await page.$$eval('.skin-card.on', xs => xs.map(x => x.dataset.skin));
  await page.click('[data-done]');
  await page.waitForTimeout(170);
  await page.screenshot({path: path.join(OUT, `skin_${s.key}.png`)});

  const wantTheme = s.scheme || 'light';
  // 界面背景用去文字的 bg-*.webp；原图只作缩略图
  const wantBg = s.key === 'default' ? '' : 'skins/bg-' + s.key + '.webp';
  check(`${s.key}.applied`, v.skin === s.key && onCards.length === 1 && onCards[0] === s.key,
    `dataset=${v.skin} on=${onCards.join('/')}`);
  check(`${s.key}.scheme`, v.theme === wantTheme, `${v.theme} ≠ ${wantTheme}`);
  check(`${s.key}.wallpaper`, wantBg ? (v.hasWall && v.wallName === wantBg) : !v.hasWall, v.wallName);
  check(`${s.key}.contrast`, v.contrast >= 4.5, `${v.contrast}:1`);
  // 整窗一张图的前提：#panes 必须透气，且 .pane 真的半透明。
  // 回归过一次「只有侧栏能看图」——.panes 用 --line 实色铺满内容区。
  check(`${s.key}.glass`, s.key === 'default'
    ? alphaOf(v.panesColor) === 1
    : (alphaOf(v.panesColor) <= 0.05 && alphaOf(v.paneColor) > 0.2 && alphaOf(v.paneColor) < 0.9),
    `panes=${v.panesColor} pane=${v.paneColor}`);
  rows.push({...v, name: s.name, ok: v.skin === s.key && v.theme === wantTheme});
}

// 壁纸开关：关掉后背景不应再有图片
await page.click('#btn-theme');
await page.waitForSelector('#sk-wall');
await page.click('.skin-card[data-skin="hongri"]');
await page.waitForTimeout(200);
await page.locator('#sk-wall').uncheck();
await page.waitForTimeout(220);
const noWall = await probe();
check('wallpaper.off', !noWall.hasWall && noWall.wallpaper === '0', noWall.wallName || '无图');
await page.screenshot({path: path.join(OUT, 'skin_nowall.png')});
await page.locator('#sk-wall').check();
await page.waitForTimeout(200);
const wallBack = await probe();
check('wallpaper.on', wallBack.hasWall && wallBack.wallpaper === '1', wallBack.wallName);

// 壁纸不透明度滑杆：拖动后只降壁纸层的 opacity
const opDefault = await page.evaluate(() =>
  getComputedStyle(document.body, '::before').opacity);
check('wallopacity.default', Math.abs(parseFloat(opDefault) - 1) < 0.02, opDefault);
await page.locator('#sk-op').fill('40');
await page.waitForTimeout(220);
const op40 = await page.evaluate(() => ({
  css: getComputedStyle(document.body, '::before').opacity,
  label: document.querySelector('#sk-op-v').textContent,
  cfg: (window.__FMP_TEST_CFG__ || {}).skin_opacity,
}));
check('wallopacity.slider', Math.abs(parseFloat(op40.css) - 0.4) < 0.02 && op40.label === '40%',
  `${op40.css} / ${op40.label}`);
await page.screenshot({path: path.join(OUT, 'skin_wallop40.png')});
await page.locator('#sk-op').fill('100');
await page.waitForTimeout(200);

// 明暗切换在皮肤下应回到默认皮肤
await page.click('#sk-seg button[data-th="dark"]');
await page.waitForTimeout(250);
const back = await probe();
check('theme.back_to_default', back.skin === 'default' && back.theme === 'dark', `${back.skin}/${back.theme}`);
await page.click('[data-reset]');
await page.waitForTimeout(220);
const reset = await probe();
check('reset', reset.skin === 'default' && reset.theme === 'light', `${reset.skin}/${reset.theme}`);
await page.click('[data-done]');
await page.waitForTimeout(150);
await page.screenshot({path: path.join(OUT, 'skin_reset.png')});

const passed = checks.filter(c => c.ok).length;
fs.writeFileSync(path.join(OUT, 'skin_report.json'),
  JSON.stringify({passed, total: checks.length, rows, checks, jsErrors: errs}, null, 2), 'utf-8');
console.log(JSON.stringify({passed, total: checks.length, errors: checks.filter(c => !c.ok),
  jsErrors: errs}, null, 2));
await browser.close();
if (srv) srv.kill();
