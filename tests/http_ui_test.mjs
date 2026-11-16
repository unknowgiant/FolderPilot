// 无桥环境端到端验证：普通 Chrome 里不存在 window.pywebview，
// 若前端仍依赖 js_api 就必然启动失败。此脚本用真实后端 + HTTP 命令通道跑通全流程。
// 用法：node tests/http_ui_test.mjs
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/unkno/.workbuddy/binaries/node/workspace/node_modules/playwright-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const urlFile = path.join(__dirname, '.real_server_url');
const outDir = path.join(__dirname, 'output');
fs.mkdirSync(outDir, {recursive: true});
const report = {checks: [], errors: []};
const check = (name, ok, detail = '') => {
  report.checks.push({name, ok: !!ok, detail});
  if (!ok) report.errors.push(name + ': ' + detail);
};

try { fs.unlinkSync(path.join(outDir, 'real_cfg', 'config.json')); } catch (_) {}
try { fs.unlinkSync(urlFile); } catch (_) {}
const server = spawn('py', ['-3.14', path.join(__dirname, 'serve_real.py')], {stdio: 'ignore'});
let base = '';
for (let i = 0; i < 60; i++) {
  await new Promise(r => setTimeout(r, 150));
  if (fs.existsSync(urlFile)) {
    const u = fs.readFileSync(urlFile, 'utf-8').trim();
    try { const r = await fetch(u, {signal: AbortSignal.timeout(800)}); if (r.ok) { base = u; break; } }
    catch (_) {}
  }
}
if (!base) { console.log(JSON.stringify({...report, errors: ['真实服务未启动'], passed: false})); process.exit(1); }

const browser = await chromium.launch({executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']});
const page = await browser.newPage({viewport: {width: 1360, height: 860}});
const jsErrors = [];
page.on('pageerror', e => jsErrors.push('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) jsErrors.push('console: ' + m.text()); });

try {
  await page.goto(base, {waitUntil: 'domcontentloaded', timeout: 20000});
  await page.waitForSelector('body[data-ready="1"]', {timeout: 20000});
  check('真实后端启动成功（无 js_api）', true);
  const noBridge = await page.evaluate(() => typeof window.pywebview === 'undefined');
  check('确认浏览器中没有 pywebview 桥', noBridge);
  const bodyText = await page.locator('body').innerText();
  check('未出现启动失败提示', !/启动失败|is not a function/.test(bodyText), bodyText.slice(0, 120));

  const pane = page.locator('#panes .pane[data-pi="0"]');
  const rows = await pane.locator('.lbody .row').count();
  check('真实目录列表已加载', rows > 0, `rows=${rows}`);
  const addr = await pane.locator('.addr .ap').textContent();
  check('地址栏是真实本机路径', /^[A-Za-z]:\\/.test(addr || '') && !/移动云盘同步盘/.test(addr || ''), addr);
  await page.screenshot({path: path.join(outDir, '07-http-real.png')});

  // 真实后端 + 本地索引：文件夹内搜索（不执行打开，避免启动外部程序）
  await pane.locator('.toolbar [data-act="search"]').click();
  await pane.locator('.sb-input').fill('a');
  await page.waitForFunction(() => {
    const c = document.querySelector('#panes .pane[data-pi="0"] .searchctx');
    return c && !c.classList.contains('hidden') && /命中/.test(c.textContent || '');
  }, null, {timeout: 25000});
  const ctxText = await pane.locator('.searchctx').innerText();
  const resultCount = await pane.locator('.lbody .row').count();
  check('搜索命令经 HTTP 通道执行', /命中/.test(ctxText), ctxText.slice(0, 120));
  check('真实搜索返回结果', resultCount > 0, `rows=${resultCount}`);
  await page.screenshot({path: path.join(outDir, '08-http-search.png')});

  // 右键菜单能弹出，说明上下文命令链路完好
  if (resultCount > 0) {
    await pane.locator('.lbody .row').first().click({button: 'right'});
    await page.waitForSelector('.ctx:not(.hidden) .ctx-item', {timeout: 3000});
    const labels = await page.locator('.ctx-item .cl').allTextContents();
    check('真实搜索结果右键菜单可用', labels.includes('打开'), labels.slice(0, 3).join('/'));
  }
  const cfgPath = path.join(outDir, 'real_cfg', 'config.json');
  check('启动握手已写入真实配置', fs.existsSync(cfgPath) &&
    !!JSON.parse(fs.readFileSync(cfgPath, 'utf-8')).last_launch);

  // ---------- 手动拖拽（窗格间复制 / 拖出命令链路） ----------
  const osMod = await import('node:os');
  const dragRoot = fs.mkdtempSync(path.join(osMod.tmpdir(), 'fmp_dragtest_'));
  const dirA = path.join(dragRoot, '甲源'), dirB = path.join(dragRoot, '乙目标');
  fs.mkdirSync(dirA); fs.mkdirSync(dirB);
  fs.writeFileSync(path.join(dirA, '拖拽样本.txt'), 'drag-me');

  async function gotoPath(paneIdx, dir) {
    const pane = page.locator(`#panes .pane[data-pi="${paneIdx}"]`);
    await pane.locator('.addr').click();
    const inp = pane.locator('.addr input');
    await inp.fill(dir);
    await inp.press('Enter');
    await page.waitForFunction(i => {
      const a = document.querySelector(`#panes .pane[data-pi="${i}"] .addr .ap`);
      return a && a.textContent.length > 0;
    }, paneIdx, {timeout: 8000});
  }
  await gotoPath(0, dirA);
  await gotoPath(1, dirB);

  const rowA = page.locator('#panes .pane[data-pi="0"] .lbody .row').first();
  await rowA.waitFor({timeout: 8000});
  const ra = await rowA.boundingBox();
  const paneB = page.locator('#panes .pane[data-pi="1"]');
  const pb = await paneB.boundingBox();
  check('拖拽测试目录就绪', !!ra && !!pb, `A=${!!ra} B=${!!pb}`);
  if (ra && pb) {
    // 手动拖拽：按下 → 移动超过阈值 → 拖到窗格 B 中心 → 松开
    await page.mouse.move(ra.x + ra.width / 2, ra.y + ra.height / 2);
    await page.mouse.down();
    await page.mouse.move(ra.x + ra.width / 2 + 40, ra.y + ra.height / 2 + 30, {steps: 4});
    await page.mouse.move(pb.x + pb.width / 2, pb.y + pb.height / 2, {steps: 8});
    const highlighted = await paneB.evaluate(el => el.classList.contains('drop-ok'));
    await page.mouse.up();
    await new Promise(r => setTimeout(r, 900));       // 等复制任务完成
    const copied = fs.existsSync(path.join(dirB, '拖拽样本.txt'));
    check('窗格间手动拖拽完成复制', copied, dirB);
    check('拖拽过程目标窗格高亮', highlighted);
    await page.screenshot({path: path.join(outDir, '10-drag-drop.png')});
    // 拖到本窗格自身应无操作：再拖一次到窗格 A 内部，目标文件不应重复
    await page.mouse.move(pb.x + pb.width / 2, pb.y + pb.height / 2);
    await page.mouse.down();
    await page.mouse.move(ra.x + 10, ra.y + 10, {steps: 6});
    await page.mouse.up();
    await new Promise(r => setTimeout(r, 500));
    const dup = fs.readdirSync(dirA).filter(f => f.includes('副本')).length;
    check('拖回源窗格不产生副本', dup === 0, `dups=${dup}`);
  }

  // 拖出命令链路（无窗口环境应返回明确错误而不是崩溃）
  const dragResp = await page.evaluate(async () => {
    const r = await fetch('/api?t=real-test-token', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({method: 'drag.start', params: {paths: ['C:\\\\'], effect: 'copy'}})});
    return await r.json();
  });
  const dragErr = dragResp && dragResp.ok === false ? (dragResp.error || '') :
    JSON.stringify(dragResp && dragResp.data || {});
  check('drag.start 命令链路可达（无窗环境返回明确提示）', !dragResp || dragResp.ok === false || !dragResp.data || dragResp.data.started === false, dragErr.slice(0, 120));

  check('无 JS 运行时错误', jsErrors.length === 0, jsErrors.join(' | '));
} catch (ex) {
  report.errors.push('FATAL: ' + ex.message);
} finally {
  await browser.close();
  server.kill();
  try { fs.unlinkSync(urlFile); } catch (_) {}
}
report.passed = report.errors.length === 0;
fs.writeFileSync(path.join(outDir, 'http_report.json'), JSON.stringify(report, null, 2), 'utf-8');
console.log(JSON.stringify(report, null, 2));
process.exit(report.passed ? 0 : 1);
