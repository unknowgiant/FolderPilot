// 界面自动化自测（需先启动 tests/.server_url 指向的本地服务）
// 重点验证：文件夹内搜索结果的双击/右键可用、列头与数据列不重叠、长中文名不压字。
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/unkno/.workbuddy/binaries/node/workspace/node_modules/playwright-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const urlFile = path.join(__dirname, '.server_url');
let localServer = null;
async function reachable(u) {
  try { const r = await fetch(u, {signal: AbortSignal.timeout(800)}); return r.ok; }
  catch (_) { return false; }
}
async function getBase() {
  if (fs.existsSync(urlFile)) {
    const u = fs.readFileSync(urlFile, 'utf-8').trim();
    if (await reachable(u)) return u;
  }
  localServer = spawn('py', ['-3.14', path.join(__dirname, 'serve.py')], {stdio: 'ignore'});
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 150));
    if (fs.existsSync(urlFile)) {
      const u = fs.readFileSync(urlFile, 'utf-8').trim();
      if (await reachable(u)) return u;
    }
  }
  throw new Error('无法启动本地界面服务，请确认已安装 Python 3.10+ 与 pywebview');
}
const base = await getBase();
const outDir = path.join(__dirname, 'output');
fs.mkdirSync(outDir, {recursive: true});
const report = {checks: [], errors: []};
const check = (name, ok, detail = '') => { report.checks.push({name, ok: !!ok, detail}); if (!ok) report.errors.push(name + ': ' + detail); };
async function ensureSearch(pane) {
  if (!await pane.locator('.searchbar:not(.hidden)').count())
    await pane.locator('.toolbar [data-act="search"]').click();
}
async function clearToast(page) {
  await page.evaluate(() => { const t = document.querySelector('#toast'); if (t) { t.textContent = ''; t.className = 'toast hidden'; } });
}

const browser = await chromium.launch({executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']});
const page = await browser.newPage({viewport: {width: 1360, height: 860}, deviceScaleFactor: 1});
page.on('pageerror', e => report.errors.push('pageerror: ' + e.message));
page.on('console', m => {
  // demo 模式下 favicon / 占位图片 404 属正常，只关注真正的脚本错误
  if (m.type() === 'error' && !/Failed to load resource/.test(m.text()))
    report.errors.push('console: ' + m.text());
});

try {
  await page.goto(base + '?demo=1', {waitUntil: 'domcontentloaded', timeout: 20000});
  await page.waitForSelector('body[data-ready="1"]', {timeout: 20000});
  await page.waitForTimeout(400);
  await page.screenshot({path: path.join(outDir, '01-main.png')});
  check('应用启动完成', true);

  const pane = page.locator('#panes .pane[data-pi="0"]');
  // 1) 打开「文件夹内搜索」并输入中文关键字
  await pane.locator('.toolbar [data-act="search"]').click();
  await pane.locator('.sb-input').fill('伊川');
  await page.waitForTimeout(800);
  const rows = await pane.locator('.lbody .row').count();
  const paths = await pane.locator('.lbody .row').evaluateAll(rs => rs.map(r => r.dataset.path));
  check('文件夹内搜索返回结果', rows > 0, `rows=${rows}`);
  check('每条结果都带绝对路径', paths.length > 0 && paths.every(p => /^[A-Za-z]:\\/.test(p)),
    paths.slice(0, 2).join(' | '));
  const rels = await pane.locator('.lbody .row .rel').count();
  check('搜索结果显示相对路径副标题', rels === rows, `rel=${rels} rows=${rows}`);
  await page.screenshot({path: path.join(outDir, '02-folder-search.png')});

  // 2) 布局：列头 / 数据列 x 对齐且互不重叠；文本容器均有省略策略
  const layout = await page.evaluate(() => {
    const issues = [];
    const p = document.querySelector('#panes .pane[data-pi="0"]');
    const heads = [...p.querySelectorAll('.lhead .hc')].map(x => x.getBoundingClientRect());
    const row = p.querySelector('.lbody .row');
    const cells = row ? [...row.children].map(x => x.getBoundingClientRect()) : [];
    if (heads.length !== 4 || cells.length !== 4) issues.push('列数不等于 4');
    else {
      for (let i = 0; i < 4; i++)
        if (Math.abs(cells[i].left - heads[i].left) > 2) issues.push(`第${i+1}列错位 ${cells[i].left.toFixed(1)} vs ${heads[i].left.toFixed(1)}`);
      for (let i = 1; i < 4; i++)
        if (cells[i].left < cells[i-1].right - 1) issues.push(`第${i+1}列与前一列重叠`);
    }
    const ctx = p.querySelector('.searchctx');
    if (ctx && !ctx.classList.contains('hidden')) {
      const kids = [...ctx.children].map(x => x.getBoundingClientRect());
      for (let i = 1; i < kids.length; i++)
        if (kids[i].left < kids[i-1].right - 1) issues.push('搜索条件条元素重叠');
    }
    document.querySelectorAll('.row .fname, .row .rel, .row .cell, .side-item .si-name, .sd-name, .sc-txt, .pal-stat').forEach(el => {
      const cs = getComputedStyle(el);
      if (cs.overflow !== 'hidden' || cs.textOverflow !== 'ellipsis' || cs.whiteSpace !== 'nowrap')
        issues.push('文本容器缺少省略保护: ' + el.className);
    });
    return issues;
  });
  check('列对齐且无压字', layout.length === 0, layout.join('; '));

  // 3) 右键搜索结果 → 菜单出现 → 点击「打开」应真正执行
  const fileRow = pane.locator('.lbody .row').filter({has: page.locator('.fname')}).last();
  await fileRow.click({button: 'right'});
  await page.waitForSelector('.ctx:not(.hidden) .ctx-item', {timeout: 3000});
  const menuLabels = await page.locator('.ctx-item .cl').allTextContents();
  check('搜索结果右键菜单可用', menuLabels.includes('打开') && menuLabels.includes('跳转到所在目录'),
    menuLabels.slice(0, 5).join('/'));
  const targetName = await fileRow.locator('.fname').first().textContent();
  await clearToast(page);
  await page.locator('.ctx-item[data-k="open"]').click();
  await page.waitForTimeout(350);
  const toast1 = await page.locator('#toast').textContent();
  check('右键「打开」已执行', /已打开/.test(toast1 || ''), `toast=${toast1} target=${targetName}`);

  // 4) 双击搜索结果同样可执行
  await ensureSearch(pane);
  await pane.locator('.sb-input').fill('伊川');
  await page.waitForTimeout(700);
  const before = await page.locator('#st-main').textContent();
  await clearToast(page);
  await pane.locator('.lbody .row').last().dblclick();
  await page.waitForTimeout(350);
  const after = await page.locator('#st-main').textContent();
  const toast2 = await page.locator('#toast').textContent();
  check('双击搜索结果已执行', /已打开/.test(toast2 || '') || before !== after,
    `toast=${toast2}; status=${before} -> ${after}`);

  // 5) Ctrl+Enter 跳转所在目录
  await ensureSearch(pane);
  await pane.locator('.sb-input').fill('施工图');
  await page.waitForTimeout(700);
  await pane.locator('.lbody .row').first().click();
  const addrBefore = await pane.locator('.addr .ap').textContent();
  await page.keyboard.press('Control+Enter');
  await page.waitForTimeout(500);
  const addrAfter = await pane.locator('.addr .ap').textContent();
  check('Ctrl+Enter 跳转到所在目录', addrBefore !== addrAfter, `${addrBefore} -> ${addrAfter}`);
  await page.screenshot({path: path.join(outDir, '03-after-locate.png')});

  // 6) 全盘搜索命令面板
  await page.keyboard.press('Control+f');
  await page.waitForSelector('#palette:not(.hidden)');
  await page.locator('#pal-input').fill('伊川');
  await page.waitForTimeout(700);
  const palRows = await page.locator('#pal-res .prow').count();
  check('全盘搜索命令面板返回结果', palRows > 0, `rows=${palRows}`);
  await page.screenshot({path: path.join(outDir, '04-global-search.png')});
  await clearToast(page);
  await page.locator('#pal-res .prow').last().dblclick();
  await page.waitForTimeout(300);
  const toast3 = await page.locator('#toast').textContent();
  check('命令面板结果可打开', /已打开/.test(toast3 || ''), `toast=${toast3}`);
  check('打开结果后命令面板自动关闭', await page.locator('#palette.hidden').count() === 1);

  // 7) 皮肤面板（明暗切换也在这里）/ 布局切换不报错
  await page.locator('#btn-theme').click();
  await page.locator('#sk-seg button[data-th="dark"]').click();
  await page.locator('#modal-root [data-done]').click();
  await page.keyboard.press('Control+4');
  await page.waitForTimeout(250);
  const panesVisible = await page.locator('#panes .pane:not(.hidden)').count();
  check('布局切换为三栏', panesVisible === 3, `visible=${panesVisible}`);
  const narrow = await page.evaluate(() => {
    const p = document.querySelector('#panes .pane[data-pi="0"]');
    const nm = p.querySelector('.lbody .row .nm');
    const fn = nm?.querySelector('.fname');
    return {paneWidth: Math.round(p.getBoundingClientRect().width),
      nameWidth: Math.round(nm?.getBoundingClientRect().width || 0),
      color: fn ? getComputedStyle(fn).color : '', text: fn?.textContent || ''};
  });
  check('窄窗格名称列未被挤没', narrow.nameWidth > 140 && !!narrow.text, JSON.stringify(narrow));
  await page.screenshot({path: path.join(outDir, '05-dark-3panes.png')});
  await page.locator('#btn-theme').click();
  await page.locator('#sk-seg button[data-th="light"]').click();
  await page.locator('#modal-root [data-done]').click();

  // 8) 可调节列宽与窗格宽度（用户新增需求）
  await page.keyboard.press('Control+2');           // 回到左右分屏
  await page.waitForTimeout(200);
  const pane0 = page.locator('#panes .pane[data-pi="0"]');
  const cols0 = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--cols').trim());
  check('列头提供名称列拖拽手柄', await pane0.locator('.lhead .grip-name').count() === 1, cols0);
  check('列头提供列宽设置按钮', await pane0.locator('.lhead .hc-cw').count() === 1);

  const nameBefore = await pane0.locator('.lhead .hc').first().evaluate(el => el.getBoundingClientRect().width);
  const gripBox = await pane0.locator('.lhead .grip-name').boundingBox();
  await page.mouse.move(gripBox.x + gripBox.width / 2, gripBox.y + gripBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(gripBox.x + gripBox.width / 2 + 180, gripBox.y + gripBox.height / 2, {steps: 8});
  await page.mouse.up();
  await page.waitForTimeout(150);
  const nameAfter = await pane0.locator('.lhead .hc').first().evaluate(el => el.getBoundingClientRect().width);
  const colsFixed = await page.evaluate(() => document.documentElement.style.getPropertyValue('--cols').trim());
  check('拖动名称列手柄可加宽名称列', nameAfter > nameBefore + 100 && /min\(\d+px/.test(colsFixed),
    `before=${Math.round(nameBefore)} after=${Math.round(nameAfter)} cols=${colsFixed}`);
  const aligned = await pane0.evaluate(el => {
    const h = el.querySelector('.lhead .hc').getBoundingClientRect();
    const r = el.querySelector('.lbody .row > *').getBoundingClientRect();
    return {hleft: Math.round(h.left), rleft: Math.round(r.left), hw: Math.round(h.width), rw: Math.round(r.width)};
  });
  check('加宽后列头与数据行仍严格对齐', Math.abs(aligned.hleft - aligned.rleft) <= 2 &&
    Math.abs(aligned.hw - aligned.rw) <= 2, JSON.stringify(aligned));
  await pane0.locator('.lhead .grip-name').dblclick();
  await page.waitForTimeout(120);
  const colsAuto = await page.evaluate(() => document.documentElement.style.getPropertyValue('--cols').trim());
  check('双击名称列手柄恢复自动宽度', /^minmax\(0,1fr\)/.test(colsAuto), colsAuto);

  // 列宽设置弹窗：数值调整 + 即时预览 + 应用 / 取消
  await pane0.locator('.lhead .hc-cw').click();
  await page.waitForSelector('#cw-n-name', {timeout: 3000});
  await page.locator('#cw-auto').uncheck();
  await page.locator('#cw-n-name').fill('700');
  await page.locator('#cw-n-size').fill('110');
  await page.locator('#cw-n-pane').fill('65');
  await page.waitForTimeout(150);
  const preview = await pane0.evaluate(el => {
    const head = el.querySelector('.lhead');
    return {name: Math.round(head.querySelector('.hc').getBoundingClientRect().width),
      headW: Math.round(head.clientWidth), scrollW: Math.round(head.scrollWidth)};
  });
  const colsPreview = await page.evaluate(() => document.documentElement.style.getPropertyValue('--cols').trim());
  check('设置面板改动即时预览且不挤出其他列',
    /min\(700px/.test(colsPreview) && preview.scrollW <= preview.headW + 2 && preview.name > 180,
    `name=${preview.name} head=${preview.headW} scroll=${preview.scrollW} cols=${colsPreview}`);
  await page.locator('.modal-foot [data-ok]').click();
  await page.waitForTimeout(150);
  const savedCols = await page.evaluate(() => document.documentElement.style.getPropertyValue('--cols').trim());
  check('应用后列宽与窗格比例已生效',
    /min\(700px/.test(savedCols) && /110px/.test(savedCols) &&
    /146px/.test(savedCols) && /108px/.test(savedCols), savedCols);
  const ratioW = await page.evaluate(() => {
    const a = document.querySelector('#panes .pane[data-pi="0"]').getBoundingClientRect().width;
    const b = document.querySelector('#panes .pane[data-pi="1"]').getBoundingClientRect().width;
    return a / (a + b);
  });
  check('左窗格占比调整为 65%', Math.abs(ratioW - 0.65) < 0.02, `ratio=${ratioW.toFixed(3)}`);
  check('窗格分隔条已显示', await page.locator('#pane-split:not(.hidden)').count() === 1);

  // 拖动窗格分隔条
  const splitBox = await page.locator('#pane-split').boundingBox();
  await page.mouse.move(splitBox.x + splitBox.width / 2, splitBox.y + 40);
  await page.mouse.down();
  await page.mouse.move(splitBox.x + splitBox.width / 2 - 120, splitBox.y + 40, {steps: 8});
  await page.mouse.up();
  await page.waitForTimeout(150);
  const ratioAfterDrag = await page.evaluate(() => {
    const a = document.querySelector('#panes .pane[data-pi="0"]').getBoundingClientRect().width;
    const b = document.querySelector('#panes .pane[data-pi="1"]').getBoundingClientRect().width;
    return a / (a + b);
  });
  check('拖动窗格分隔条可改变宽度', ratioAfterDrag < ratioW - 0.05,
    `before=${ratioW.toFixed(3)} after=${ratioAfterDrag.toFixed(3)}`);
  await page.screenshot({path: path.join(outDir, '08-column-width.png')});

  // 一键「仅显示名称列」：其他列隐藏、名称占满整栏，取消后还原
  await pane0.locator('.lhead .hc-cw').click();
  await page.waitForSelector('#cw-nameonly', {timeout: 3000});
  await page.locator('#cw-nameonly').check();
  await page.waitForTimeout(150);
  const only = await pane0.evaluate(el => {
    const h = el.querySelectorAll('.lhead .hc');
    const rows = el.querySelector('.lbody .row');
    return {flag: document.documentElement.dataset.nameOnly,
      sizeVisible: getComputedStyle(h[1]).display !== 'none',
      rowCells: rows ? rows.children.length : 0,
      nameW: Math.round(h[0].getBoundingClientRect().width),
      paneW: Math.round(el.getBoundingClientRect().width)};
  });
  check('仅显示名称列模式生效', only.flag === '1' && !only.sizeVisible &&
    only.nameW > only.paneW * 0.8, JSON.stringify(only));
  await page.screenshot({path: path.join(outDir, '09-name-only.png')});

  // 长名称两行显示
  await page.locator('#cw-nameonly').uncheck();
  await page.locator('#cw-wrap').check();
  await page.waitForTimeout(150);
  const wrap = await pane0.evaluate(el => {
    const f = el.querySelector('.lbody .row .fname'), r = el.querySelector('.lbody .row');
    return {ws: f ? getComputedStyle(f).whiteSpace : '', h: r ? Math.round(r.getBoundingClientRect().height) : 0,
      flag: document.documentElement.dataset.nameWrap || ''};
  });
  check('长名称两行显示可开启', wrap.flag === '1' && wrap.ws === 'normal' && wrap.h > 30,
    JSON.stringify(wrap));

  await page.locator('.modal-foot [data-close2]').click();
  await page.waitForTimeout(150);
  const restored = await page.evaluate(() => ({
    cols: document.documentElement.style.getPropertyValue('--cols').trim(),
    flag: document.documentElement.dataset.nameOnly || '',
    wrap: document.documentElement.dataset.nameWrap || '',
  }));
  check('取消设置还原原列宽与列显示', /min\(700px/.test(restored.cols) &&
    /110px/.test(restored.cols) && /146px/.test(restored.cols) &&
    restored.flag !== '1' && restored.wrap !== '1', JSON.stringify(restored));

  // 9) 外部程序可访问性诊断（针对复制到云盘报「无权限」的排查）
  await pane0.locator('.lbody .row').first().click({button: 'right'});
  await page.waitForSelector('.ctx:not(.hidden)', {timeout: 3000});
  await page.locator('.ctx:not(.hidden) .ctx-item[data-k="access"]').click();
  await page.waitForSelector('.modal-mask', {timeout: 3000});
  const diag = await page.locator('.modal-mask').innerText();
  check('可访问性诊断弹窗显示判定结果', /任意进程可读/.test(diag) && /路径/.test(diag),
    diag.slice(0, 120).replace(/\n/g, ' '));
  await page.locator('.modal-mask .modal-foot [data-close]').click();
  await page.waitForTimeout(120);

  check('无 JS 运行时错误', report.errors.filter(x => /pageerror|console/.test(x)).length === 0,
    report.errors.filter(x => /pageerror|console/.test(x)).join(' | '));
} catch (ex) {
  report.errors.push('FATAL: ' + ex.message);
} finally {
  await browser.close();
  if (localServer) {
    localServer.kill();
    try { fs.unlinkSync(urlFile); } catch (_) {}
  }
}
report.passed = report.errors.length === 0;
fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2), 'utf-8');
console.log(JSON.stringify(report, null, 2));
process.exit(report.passed ? 0 : 1);
