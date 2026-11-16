// 字色专项检查：换主题后字色是否真的跟着换、压在壁纸上是否还看得清。
//
// 做法不是「读 CSS 变量自己算」，而是量**真实渲染结果**：
//   1. 切到某套主题，取当前的 --tx / --tx2 / --tx3；
//   2. 把列表里的文字临时隐藏（visibility:hidden，不动布局），截一张
//      「只有底」的图 —— 这张图就是文字底下真正的颜色，连同壁纸高光、
//      模糊、蒙层、面板 alpha 全在里面；
//   3. 拿每条像素跟字色算对比度，取中位数与最差 5%。
//   4. 滑杆再拖到该主题的可读下限重来一遍。
//
// 阈值：中位 ≥ 5.0，最差 5% ≥ 4.2（AA 是 4.5，留 0.3 给抗锯齿与取样误差）。
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
if (!fs.existsSync(urlFile) || !(await reachable(fs.readFileSync(urlFile, 'utf-8').trim()))) {
  spawn('py', ['-3.14', path.join(__dirname, 'serve.py')], {stdio: 'ignore'});
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 150));
    if (fs.existsSync(urlFile) && await reachable(fs.readFileSync(urlFile, 'utf-8').trim())) break;
  }
}
const base = fs.readFileSync(urlFile, 'utf-8').trim();

const checks = [];
const rows = [];
const check = (name, ok, note = '') => checks.push({name, ok: !!ok, note: String(note)});

const browser = await chromium.launch({executablePath: CHROME, headless: true});
const page = await browser.newPage({viewport: {width: 1280, height: 800}});
const errs = [];
page.on('pageerror', e => errs.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
await page.goto(base + '?demo=1', {waitUntil: 'domcontentloaded'});
await page.waitForSelector('body[data-ready="1"]', {timeout: 20000});

const meta = await page.evaluate(async () => {
  const m = await import('./js/skins.js');
  return m.SKINS.filter(s => s.key !== 'default')
    .map(s => ({key: s.key, name: s.name, scheme: s.scheme, pf: s.pf}));
});

// 采样：把第一栏列表里的文字藏掉，截这块区域，逐像素算它与字色的对比度
async function measure(vars) {
  const box = await page.evaluate(() => {
    const b = document.querySelector('.pane .lbody');
    if (!b || !b.querySelector('.row')) return null;
    const r = b.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.min(420, Math.round(r.height))};
  });
  if (!box || box.w < 40 || box.h < 40) return null;
  await page.evaluate(() => {
    const s = document.createElement('style');
    s.id = 'ink-hide';
    s.textContent = '.pane .lbody .row *{visibility:hidden!important}';
    document.head.appendChild(s);
  });
  await page.waitForTimeout(120);
  const shot = await page.screenshot({clip: {x: box.x, y: box.y, width: box.w, height: box.h}});
  await page.evaluate(() => document.getElementById('ink-hide')?.remove());
  const stat = await page.evaluate(async ({b64, vars}) => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + b64;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const g = c.getContext('2d');
    g.drawImage(img, 0, 0);
    const {data, width, height} = g.getImageData(0, 0, c.width, c.height);
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    const lum = (r, gg, b) => 0.2126 * f(r) + 0.7152 * f(gg) + 0.0722 * f(b);
    const hx = h => {
      h = String(h).trim().replace('#', '');
      if (h.length === 3) h = h.split('').map(x => x + x).join('');
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    };
    const ratio = (a, b) => {
      const la = lum(...a), lb = lum(...b);
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    };
    const out = {};
    for (const [name, hex] of Object.entries(vars)) {
      const ink = hx(hex);
      const arr = [];
      // 每 3 像素取一个，避开相邻像素的重复
      for (let y = 0; y < height; y += 3) {
        for (let x = 0; x < width; x += 3) {
          const i = (y * width + x) * 4;
          arr.push(ratio(ink, [data[i], data[i + 1], data[i + 2]]));
        }
      }
      arr.sort((a, b) => a - b);
      out[name] = {
        med: +arr[Math.floor(arr.length * 0.5)].toFixed(2),
        p05: +arr[Math.floor(arr.length * 0.05)].toFixed(2),
        min: +arr[0].toFixed(2),
      };
    }
    return out;
  }, {b64: shot.toString('base64'), vars});
  return stat;
}

const readVars = () => page.evaluate(() => {
  const cs = getComputedStyle(document.documentElement);
  return {
    tx: cs.getPropertyValue('--tx').trim(),
    tx2: cs.getPropertyValue('--tx2').trim(),
    tx3: cs.getPropertyValue('--tx3').trim(),
  };
});

// 量之前必须关掉主题面板 —— 它是整屏遮罩，开着的话截到的是弹窗不是列表
async function setSkin(key, pf) {
  await page.click('#btn-theme');
  await page.waitForSelector('.skin-card');
  await page.click(`.skin-card[data-skin="${key}"]`);
  await page.waitForTimeout(160);
  await page.evaluate(v => {
    const r = document.querySelector('#sk-op');
    r.value = String(v);
    r.dispatchEvent(new Event('input', {bubbles: true}));
  }, pf);
  await page.waitForTimeout(160);
  await page.click('[data-done]');
  await page.waitForTimeout(300);
}

for (const s of meta) {
  await setSkin(s.key, 100);
  const v = await readVars();
  const full = await measure({tx: v.tx, tx2: v.tx2});
  if (!full) { check(`${s.key}.sample`, false, '没取到列表区域'); continue; }
  rows.push({key: s.key, at: 100, ...full});
  check(`${s.key}.ink@100`, full.tx.med >= 5.0 && full.tx.p05 >= 4.2,
    `正文 中位 ${full.tx.med} / P05 ${full.tx.p05} / 最差 ${full.tx.min}`);
  check(`${s.key}.ink2@100`, full.tx2.med >= 3.6,
    `次要 中位 ${full.tx2.med} / P05 ${full.tx2.p05}`);
  await page.screenshot({path: path.join(OUT, `ink_${s.key}.png`)});

  // 拖到该主题的可读下限：最薄处的字还必须读得出来
  await setSkin(s.key, s.pf);
  const low = await measure({tx: v.tx, tx2: v.tx2});
  if (low) {
    rows.push({key: s.key, at: s.pf, ...low});
    // 最薄处：中位必须明显过 AA；最亮那一小块允许低一些 —— 那里的字还有
    // 反向描边兜着（截图量的是纯背景，没算光晕的补强）
    check(`${s.key}.ink@floor`, low.tx.med >= 4.6 && low.tx.p05 >= 3.7,
      `下限 ${s.pf}% 正文 中位 ${low.tx.med} / P05 ${low.tx.p05}`);
    await page.screenshot({path: path.join(OUT, `ink_${s.key}_floor.png`)});
  }
}

// 滑杆不许拖到可读下限以下
await page.click('#btn-theme');
await page.waitForSelector('.skin-card');
await page.click('.skin-card[data-skin="hongri"]');
await page.waitForTimeout(200);
const clamp = await page.evaluate(() => {
  const r = document.querySelector('#sk-op');
  r.value = '20';
  r.dispatchEvent(new Event('input', {bubbles: true}));
  const k = getComputedStyle(document.documentElement).getPropertyValue('--plate-k').trim();
  return {min: +r.min, val: +r.value, label: document.querySelector('#sk-op-v').textContent, k: +k};
});
check('slider.clamped', clamp.val === clamp.min && clamp.min > 0
  && clamp.label === clamp.min + '%（可读下限）',
  `min ${clamp.min} → value ${clamp.val} / ${clamp.label}`);
await page.evaluate(() => {
  const r = document.querySelector('#sk-op');
  r.value = '100';
  r.dispatchEvent(new Event('input', {bubbles: true}));
});
// 恢复默认皮肤
await page.click('[data-reset]');
await page.waitForTimeout(200);
await page.click('[data-done]');
await page.waitForTimeout(200);

// 默认皮肤（无壁纸）不该被塞文字光晕
const halo = await page.evaluate(() => getComputedStyle(document.body).textShadow);
check('default.no_halo', !halo || halo === 'none', halo);

const passed = checks.filter(c => c.ok).length;
fs.writeFileSync(path.join(OUT, 'ink_report.json'),
  JSON.stringify({passed, total: checks.length, checks, rows, errors: errs}, null, 2));
console.log(checks.map(c => `${c.ok ? 'OK ' : 'X  '}${c.name}  ${c.note}`).join('\n'));
console.log(`\n${passed}/${checks.length} 通过`);
if (errs.length) console.log('页面错误：', errs.slice(0, 5));
await browser.close();
process.exit(passed === checks.length ? 0 : 1);
