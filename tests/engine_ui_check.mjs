// 内置搜索引擎弹窗专项检查（临时脚本，不属于常规回归）
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
await page.goto(base + '?demo=1', {waitUntil: 'domcontentloaded'});
await page.waitForSelector('body[data-ready="1"]', {timeout: 20000});
await page.click('#btn-settings');
await page.waitForTimeout(300);
await page.click('#set-engine');
await page.waitForTimeout(400);
const title = await page.textContent('#modal-root .modal-head .mt');
const body = await page.textContent('#modal-root .modal-body');
const btns = await page.$$eval('#modal-root .modal-foot .btn', xs => xs.map(x => x.textContent.trim()));
const statusText = await page.textContent('#st-backend');
await page.screenshot({path: path.join(__dirname, 'output', 'engine_modal.png')});
console.log(JSON.stringify({title, btns, statusText, bodyLen: body.length,
  hasNoInstall: body.includes('不需要单独安装'), errs}, null, 2));
await browser.close();
if (srv) srv.kill();
