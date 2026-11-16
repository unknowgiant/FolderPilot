// 拖放（拖出到外部程序 / 窗格之间拖拽）
//
// 为什么不用 HTML5 dragstart：
//   WebView2 里的 HTML 拖拽由 Chromium 在浏览器进程里启动自己的 OLE 循环，
//   拖到资源管理器 / 云盘客户端时外部程序拿不到 CF_HDROP；且它一旦启动，
//   我们就无法再发起自己的原生拖放。因此这里完全接管拖拽：
//
//   · pointerdown 在文件行上 → 记录选中项，进入待拖拽状态
//   · 移动超过 5px → 手动拖拽开始（行上已去掉 draggable，Chromium 不介入）
//   · 指针在窗口内移动 → 高亮可投放的窗格（内部拖放）
//   · 指针越过窗口边界（事件仍因鼠标捕获而到达）→ 调后端 drag.start，
//     由原生层 SHDoDragDrop 起真正的 OLE 拖放（系统光标 / Esc 取消 /
//     Ctrl+Shift 修饰键），云盘客户端就能收到 CF_HDROP
//   · 松开在另一窗格 → 复制（Shift 移动）；松开在窗口外 → 由原生循环收尾

import { api } from './api.js';
import { S, tab, selectedPaths } from './store.js';
import { $, $$, toast, normKey } from './util.js';
import * as A from './actions.js';

const MOVE_THRESHOLD = 5;       // 判定拖拽开始的位移（px）
const EDGE_MARGIN = 8;          // 窗口边界判定余量（px）
let st = null;                  // {paths, fromPane, fromPath, started}
let externalBusy = false;       // 原生拖放进行中

export function bindDragOut() {
  document.addEventListener('pointerdown', e => {
    if (e.button !== 0 || externalBusy) { st = null; return; }
    const row = e.target.closest('[data-path]');
    if (!row || e.target.closest('.grip, input, button')) { st = null; return; }
    // 源窗格取行所在的窗格，而不是"当前激活窗格"（两者在跨窗格操作时不一致）
    const paneEl = row.closest('.pane');
    const i = paneEl ? +paneEl.dataset.pi : S.activePane;
    const t = tab(i);
    if (!t) { st = null; return; }
    let paths = selectedPaths(t);
    if (!paths.includes(row.dataset.path)) paths = [row.dataset.path];
    st = {paths, fromPane: i, fromPath: t.path, started: false,
          x: e.clientX, y: e.clientY};
  }, true);

  document.addEventListener('pointermove', e => {
    if (!st || externalBusy || !(e.buttons & 1)) return;
    if (!st.started) {
      if (Math.abs(e.clientX - st.x) < MOVE_THRESHOLD &&
          Math.abs(e.clientY - st.y) < MOVE_THRESHOLD) return;
      st.started = true;
    }
    if (outsideWindow(e)) {          // 越界 → 原生 OLE 拖放接管
      const paths = st.paths;
      cleanup();
      startExternalDrag(paths);
      return;
    }
    // 窗口内：高亮可投放窗格 + 角标跟随
    const pane = document.elementFromPoint(e.clientX, e.clientY)?.closest('.pane');
    $$('#panes .pane.drop-ok').forEach(x => x.classList.remove('drop-ok'));
    if (pane) {
      const i = +pane.dataset.pi, t = tab(i);
      if (t && t.mode !== 'search' && i !== st.fromPane &&
          normKey(t.path) !== normKey(st.fromPath)) pane.classList.add('drop-ok');
    }
    const b = $('#drag-badge');
    if (b) { b.textContent = `${st.paths.length} 项`; b.classList.remove('hidden');
             b.style.left = (e.clientX + 14) + 'px'; b.style.top = (e.clientY + 14) + 'px'; }
  }, true);

  document.addEventListener('pointerup', e => {
    if (!st || externalBusy) { st = null; return; }
    if (st.started) {
      const pane = document.elementFromPoint(e.clientX, e.clientY)?.closest('.pane');
      if (pane) {
        const i = +pane.dataset.pi, t = tab(i);
        if (t && t.mode !== 'search' && i !== st.fromPane &&
            normKey(t.path) !== normKey(st.fromPath)) {
          A.transfer(st.paths.slice(), t.path, e.shiftKey, i);
        }
      }
    }
    cleanup();
  }, true);
  document.addEventListener('pointercancel', () => { st = null; cleanup(); }, true);
}

function cleanup() {
  st = null;
  $$('#panes .pane.drop-ok').forEach(x => x.classList.remove('drop-ok'));
  const b = $('#drag-badge');
  if (b && !externalBusy) b.classList.add('hidden');
}

function outsideWindow(e) {
  // 优先用屏幕坐标比对窗口外框；clientX 越界作为补充（两种单位都是 CSS px）
  if (e.clientX < -EDGE_MARGIN || e.clientY < -EDGE_MARGIN ||
      e.clientX > innerWidth + EDGE_MARGIN || e.clientY > innerHeight + EDGE_MARGIN) return true;
  try {
    return e.screenX < window.screenX - EDGE_MARGIN ||
           e.screenY < window.screenY - EDGE_MARGIN ||
           e.screenX > window.screenX + window.outerWidth + EDGE_MARGIN ||
           e.screenY > window.screenY + window.outerHeight + EDGE_MARGIN;
  } catch (_) { return false; }
}

async function startExternalDrag(paths) {
  if (externalBusy) return;
  externalBusy = true;
  const badge = $('#drag-badge');
  if (badge) { badge.textContent = `拖出 ${paths.length} 项`; badge.classList.remove('hidden');
               badge.style.left = (innerWidth / 2) + 'px'; badge.style.top = (innerHeight / 2) + 'px'; }
  $$('.pane.drop-ok').forEach(x => x.classList.remove('drop-ok'));
  let st = null;
  try {
    st = await callDragStart(paths);
  } catch (ex) {
    externalBusy = false;
    if (badge) badge.classList.add('hidden');
    return toast('拖出失败：' + ex.message, true);
  }
  externalBusy = false;
  if (badge) badge.classList.add('hidden');
  if (!st) return;
  // st：{started:false,reason} 或 {state,effect,count,error,paths}
  if (st.started === false) {
    if (st.reason && !/鼠标已松开/.test(st.reason)) toast(st.reason, true);
    return;
  }
  if (st.state === 'error' && st.error) return toast('拖放：' + st.error, true);
  if (st.effect) {
    const verb = st.effect === 2 ? '已移动' : '已复制';
    toast(`${verb} ${st.count || ''} 项到外部程序`);
    if (st.effect === 2 && st.paths?.length) A.refresh();
  }
}

// 拖出必须由应用线程执行（OLE 需要接管鼠标捕获），因此优先走 pywebview 桥
// （js_api 回调在应用线程）；拖拽发生在启动完成之后，不存在启动期注入竞态。
// 桥只暴露一个 drag 方法（不收整个命令对象，避免 pywebview 递归遍历属性）。
// 无桥环境（浏览器测试）退回 HTTP。
async function callDragStart(paths) {
  const payload = JSON.stringify({paths, effect: 'copyMove'});
  const bridge = window.pywebview && window.pywebview.api && window.pywebview.api.drag;
  if (typeof bridge === 'function') {
    const raw = await bridge(payload);
    const r = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return r && r.data ? r.data : r;
  }
  const r = await api('drag.start', {paths, effect: 'copyMove'});
  return r || null;
}
