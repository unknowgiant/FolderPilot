// 启动与事件绑定：全局只有一处事件委托入口，避免重复绑定与状态漂移
import { api, waitBridge, DEMO, APP_META } from './api.js';
import { S, tab, entriesOf, selectedPaths, findEntry, visibleCount, loadState, saveState,
  statePatch, applyColWidths, setCols, makeTab } from './store.js';
import { buildPanes, renderPanes, renderPane, renderSidebar, renderStatus,
  renderLayoutButtons, refreshSelection, positionPaneSplit } from './view.js';
import * as A from './actions.js';
import * as M from './menus.js';
import * as Q from './search.js';
import * as D from './dragdrop.js';
import { $, $$, esc, toast, normKey, basename, dirname, joinPath, COLORS, COLOR_NAMES, TOKEN } from './util.js';

function uiLog(msg) {
  try { fetch('/log?t=' + encodeURIComponent(TOKEN) + '&m=' + encodeURIComponent(String(msg).slice(0, 1200))); }
  catch (_) {}
}

// 关闭时用 sendBeacon 异步落盘会话：不执行 JS 调用、不等待后端响应，
// 因此不会在窗口销毁阶段与 UI 线程互等（这是关闭卡死的关键）。
function persistOnExit() {
  try {
    const body = JSON.stringify({method: 'state.set', params: {patch: statePatch()}});
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api?t=' + encodeURIComponent(TOKEN),
        new Blob([body], {type: 'application/json'}));
    }
  } catch (_) {}
}
window.addEventListener('pagehide', persistOnExit);
window.addEventListener('beforeunload', persistOnExit);

function isTyping(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}

function bindTopbar() {
  $('#layout-switch').addEventListener('click', e => {
    const b = e.target.closest('[data-layout]');
    if (b) A.setLayout(Number(b.dataset.layout));
  });
  $('#btn-global-search').onclick = () => Q.openPalette('', 'global');
  $('#btn-tray').onclick = () => M.showTray();
  $('#btn-theme').onclick = () => M.skinModal();
  $('#btn-settings').onclick = () => M.settingsModal();
  $('#btn-about').onclick = () => M.aboutModal();
  $('#btn-pin').onclick = () => A.addFavorite(tab()?.path);
  $('#st-backend').onclick = async () => {
    // 未启用内置引擎时，点状态栏直接引导一次授权；已连接则重连
    if (S.searchStatus?.engine?.needs_auth) return M.engineModal();
    try { S.searchStatus = await api('search.connect'); renderStatus(); toast('搜索服务：' + S.searchStatus.backend); }
    catch (ex) { toast(ex.message, true); }
  };
}

async function showColor(c) {
  const paths = Object.keys(S.tags).filter(k => S.tags[k] === c);
  if (!paths.length) return toast('该颜色下暂无文件');
  const i = S.activePane, t = tab(i);
  try {
    const r = await api('entry.stat', {paths});
    t.mode = 'search'; t.results = r.entries || [];
    t.query = {query: COLOR_NAMES[COLORS.indexOf(c)] + '标签', scope: 'tag'};
    t.searchMeta = {total: t.results.length, backend: '颜色标签'};
    t.sel.clear(); t.searchOpen = false;
    renderPane(i); renderStatus(`颜色标签：${COLOR_NAMES[COLORS.indexOf(c)]} · ${t.results.length} 项`);
  } catch (ex) { toast(ex.message, true); }
}

function bindSidebar() {
  $('#side-scroll').addEventListener('click', e => {
    const nav = e.target.closest('[data-nav]');
    if (nav) return A.navigate(nav.dataset.nav, S.activePane);
    const col = e.target.closest('[data-color]');
    if (col) return showColor(col.dataset.color);
  });
  const sp = $('#splitter');
  sp.addEventListener('mousedown', e => {
    e.preventDefault(); sp.classList.add('on');
    const x0 = e.clientX, w0 = S.cfg.sidebar_width || 214;
    const move = ev => {
      const w = Math.max(150, Math.min(420, w0 + ev.clientX - x0));
      S.cfg.sidebar_width = w; applyColWidths(); positionPaneSplit();
    };
    const up = () => {
      sp.classList.remove('on');
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up); saveState();
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
}

function bindAddr(addr, i) {
  addr.addEventListener('click', e => {
    if (e.target.closest('input')) return;
    const t = tab(i); if (!t) return;
    const span = addr.querySelector('.ap');
    const inp = document.createElement('input');
    inp.value = t.path || '';
    span.replaceWith(inp);
    inp.focus(); inp.select();
    const done = (go) => {
      if (inp.dataset.closed) return;   // replaceWith 移除 input 会同步触发 blur 重入，必须幂等
      inp.dataset.closed = '1';
      const v = inp.value.trim();
      const s = document.createElement('span'); s.className = 'ap';
      inp.replaceWith(s);
      if (go && v) A.navigate(v, i);
      else renderPane(i);
    };
    inp.onkeydown = ev => {
      if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); done(true); }
      if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); done(false); }
    };
    inp.onblur = () => { if (inp.isConnected) done(false); };
  });
}

function bindColumnGrip(head, i) {
  head.addEventListener('mousedown', e => {
    const g = e.target.closest('[data-grip]');
    if (!g) return;
    e.preventDefault(); e.stopPropagation();
    const key = g.dataset.grip;
    const x0 = e.clientX;
    // 名称列默认「自动填满」，开始拖拽时先把当前实际宽度固化下来
    const w0 = key === 'name'
      ? ((S.cfg.colw || {}).name > 0 ? S.cfg.colw.name
         : Math.round(head.querySelector('[data-sort="name"]').getBoundingClientRect().width))
      : ((S.cfg.colw || {})[key] || 100);
    let moved = false;
    g.classList.add('on');
    const move = ev => {
      moved = true;
      A.updateColWidth(key, w0 + ev.clientX - x0);
    };
    const up = () => {
      g.classList.remove('on');
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      if (moved) head.dataset.suppressSort = '1';
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
  // 双击名称列分隔线 → 恢复自动宽度
  head.addEventListener('dblclick', e => {
    const g = e.target.closest('[data-grip="name"]');
    if (!g) return;
    e.preventDefault(); e.stopPropagation();
    A.updateColWidth('name', 0);
    toast('名称列已恢复自动宽度');
  });
}

// 左右分屏中间的拖拽分隔条
function bindPaneSplit() {
  const el = $('#pane-split');
  if (!el) return;
  el.addEventListener('mousedown', e => {
    e.preventDefault(); e.stopPropagation();
    el.classList.add('on');
    const box = $('#panes').getBoundingClientRect();
    const x0 = e.clientX, r0 = S.cfg.pane_ratio || 50;
    const move = ev => {
      const p = r0 + (ev.clientX - x0) / Math.max(1, box.width - 9) * 100;
      A.setPaneRatio(p);
      positionPaneSplit();
    };
    const up = () => {
      el.classList.remove('on');
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
  el.addEventListener('dblclick', e => {
    e.preventDefault(); e.stopPropagation();
    A.setPaneRatio(50); positionPaneSplit();
    toast('窗格已恢复均分');
  });
}

function bindPane(el, i) {
  el.addEventListener('mousedown', e => {
    if (S.activePane !== i) A.setActivePane(i);
  }, true);

  el.querySelector('.tabs').addEventListener('click', e => {
    const close = e.target.closest('[data-act="tab-close"]');
    if (close) { e.stopPropagation(); return A.closeTab(i, Number(close.dataset.ti)); }
    if (e.target.closest('[data-act="tab-add"]')) return A.newTab(i);
    const t = e.target.closest('.tab');
    if (t) {
      S.panes[i].active = Number(t.dataset.ti);
      S.activePane = i;
      renderPane(i); renderStatus();
      if (!tab(i)?.items.length && tab(i)?.mode === 'dir') A.loadDir(i);
    }
  });
  el.querySelector('.tabs').addEventListener('auxclick', e => {
    if (e.button !== 1) return;
    const t = e.target.closest('.tab');
    if (t) { e.preventDefault(); A.closeTab(i, Number(t.dataset.ti)); }
  });

  el.querySelector('.toolbar').addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const t = tab(i);
    switch (b.dataset.act) {
      case 'back': return A.historyMove(-1, i);
      case 'forward': return A.historyMove(1, i);
      case 'up': return A.navigate(dirname(t.path), i);
      case 'refresh': return A.refresh(i);
      case 'home': return A.navigate(S.specials[0]?.path || '::{THISPC}', i);
      case 'search': return Q.togglePaneSearch(i);
      case 'more': { const r = b.getBoundingClientRect(); return M.moreMenu(r.left, r.bottom + 4, i); }
      case 'addr': break;
    }
  });
  bindAddr(el.querySelector('.addr'), i);

  const sb = el.querySelector('.searchbar');
  const inp = sb.querySelector('.sb-input');
  inp.addEventListener('input', () => Q.schedulePaneSearch(i));
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); Q.runPaneSearch(i, true); }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); Q.exitPaneSearch(i); }
  });
  sb.querySelector('.sb-scope').addEventListener('change', () => Q.runPaneSearch(i, true));
  sb.querySelector('.sb-kind').addEventListener('change', () => Q.runPaneSearch(i, true));
  sb.addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    if (b.dataset.act === 's-exit') Q.exitPaneSearch(i);
    if (b.dataset.act === 's-global') Q.searchFolderToGlobal(i);
  });
  el.querySelector('.searchctx').addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    if (b.dataset.act === 's-exit') Q.exitPaneSearch(i);
    if (b.dataset.act === 's-switch') Q.switchPaneScope(i);
  });

  const head = el.querySelector('.lhead');
  head.addEventListener('click', e => {
    if (e.target.closest('[data-act="colwidth"]')) return M.columnWidthModal();
    if (head.dataset.suppressSort) { head.dataset.suppressSort = ''; return; }
    const c = e.target.closest('[data-sort]');
    if (c && !e.target.closest('.grip')) A.sortBy(c.dataset.sort, i);
  });
  bindColumnGrip(head, i);

  const body = el.querySelector('.lbody');
  body.addEventListener('scroll', () => { const t = tab(i); if (t) t.scroll = body.scrollTop; });
  body.addEventListener('mousedown', e => {
    if (e.button === 2) return;
    const row = e.target.closest('[data-path]');
    if (!row) return;
    const mode = e.shiftKey ? 'shift' : e.ctrlKey ? 'ctrl' : 'single';
    A.setSelection(i, row.dataset.path, mode);
  });
  body.addEventListener('click', e => {
    if (e.target === body) { const t = tab(i); if (t?.sel.size) { t.sel.clear(); refreshSelection(i); } }
  });
  // 双击 / 右键：路径来自 data-path，与列表来源完全无关
  body.addEventListener('dblclick', e => {
    const row = e.target.closest('[data-path]'); if (!row) return;
    A.activate(row.dataset.path, i, findEntry(tab(i), row.dataset.path));
  });
  body.addEventListener('contextmenu', e => {
    e.preventDefault();
    const row = e.target.closest('[data-path]');
    if (!row) return M.emptyMenu(e.clientX, e.clientY, i);
    const t = tab(i);
    if (!t.sel.has(row.dataset.path)) A.setSelection(i, row.dataset.path, 'single');
    M.itemMenu(e.clientX, e.clientY, row.dataset.path, findEntry(t, row.dataset.path), i);
  });

  // 拖拽（窗格间互拖 / 拖出到外部程序）由 dragdrop.js 全局接管
}

function bindPalette() {
  const pal = $('#palette'), inp = $('#pal-input');
  $('#pal-close').onclick = Q.closePalette;
  pal.addEventListener('mousedown', e => { if (e.target === pal) Q.closePalette(); });
  inp.addEventListener('input', () => Q.schedulePalRun());
  inp.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); Q.palMove(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); Q.palMove(-1); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const path = Q.palSelectedPath();
      if (!path) return;
      if (e.ctrlKey) { Q.closePalette(); A.revealEntry(path); }
      else { Q.closePalette(); A.activate(path, S.activePane, Q.palEntryByPath(path)); }
    } else if (e.key === 'Escape') { e.preventDefault(); Q.closePalette(); }
  });
  $('#pal-scope-chips').addEventListener('click', e => {
    const c = e.target.closest('[data-scope]'); if (c) Q.palSetScope(c.dataset.scope);
  });
  $('#pal-filter').onclick = () => $('#pal-adv').classList.toggle('hidden');
  $('#pal-adv').addEventListener('change', () => Q.palRun());
  $('#pal-adv').addEventListener('input', e => { if (e.target.type !== 'text' && e.target.type !== 'number') Q.palRun(); });
  const res = $('#pal-res');
  res.addEventListener('mousedown', e => {
    const r = e.target.closest('[data-path]'); if (!r) return;
    S.pal.sel = Number(r.dataset.idx);
    // 只切 class，不重建 DOM：否则会打断浏览器合成的 dblclick / contextmenu 事件链
    res.querySelectorAll('.prow.on').forEach(x => x.classList.remove('on'));
    r.classList.add('on');
  });
  res.addEventListener('dblclick', e => {
    const r = e.target.closest('[data-path]'); if (!r) return;
    Q.closePalette(); A.activate(r.dataset.path, S.activePane, Q.palEntryByPath(r.dataset.path));
  });
  res.addEventListener('contextmenu', e => {
    e.preventDefault();
    const r = e.target.closest('[data-path]'); if (!r) return;
    M.itemMenu(e.clientX, e.clientY, r.dataset.path, Q.palEntryByPath(r.dataset.path), S.activePane);
  });
  $('#drawer-close').onclick = A.closeDrawer;
}

function bindKeys() {
  document.addEventListener('keydown', async e => {
    const k = e.key;
    if (k === 'Escape') {
      if ($('#modal-root .modal-mask')) return M.closeAllModals();
      if (S.pal.open) return Q.closePalette();
      if ($('.ctx')) { M.closeCtx(); return; }
      if (!$('#drawer').classList.contains('hidden')) { A.closeDrawer(); return; }
      if (Q.paneSearchOpen(S.activePane)) return Q.exitPaneSearch(S.activePane);
      const t = tab(); if (t?.sel.size) { t.sel.clear(); refreshSelection(S.activePane); }
      return;
    }
    if (isTyping(e)) return;
    const ctrl = e.ctrlKey || e.metaKey, alt = e.altKey, shift = e.shiftKey;
    if (ctrl && ['1','2','3','4','5'].includes(k)) { e.preventDefault(); return A.setLayout(Number(k)); }
    if (ctrl && k.toLowerCase() === 'f') { e.preventDefault(); return Q.openPalette('', 'global'); }
    if (ctrl && k.toLowerCase() === 't') { e.preventDefault(); return A.newTab(); }
    if (ctrl && k.toLowerCase() === 'w') { e.preventDefault(); return A.closeTab(); }
    if (ctrl && shift && k.toLowerCase() === 'n') { e.preventDefault(); return A.makeFolder(); }
    if (ctrl && shift && k.toLowerCase() === 'c') { e.preventDefault(); return A.copyText(tab()?.path || ''); }
    if (ctrl && k.toLowerCase() === 'c') { e.preventDefault(); return A.copySel(S.activePane, false); }
    if (ctrl && k.toLowerCase() === 'x') { e.preventDefault(); return A.copySel(S.activePane, true); }
    if (ctrl && k.toLowerCase() === 'v') { e.preventDefault(); return A.paste(S.activePane); }
    if (ctrl && k.toLowerCase() === 'a') { e.preventDefault(); return A.selectAll(); }
    if (alt && k === 'ArrowLeft') { e.preventDefault(); return A.historyMove(-1); }
    if (alt && k === 'ArrowRight') { e.preventDefault(); return A.historyMove(1); }
    if (k === 'Backspace') { e.preventDefault(); const t = tab(); if (t) return A.navigate(dirname(t.path)); }
    if (k === 'F5') { e.preventDefault(); return A.refresh(); }
    if (k === 'F2') { e.preventDefault(); const p = selectedPaths(tab())[0]; if (p) return M.renameModal(p); }
    if (k === 'Delete') { e.preventDefault(); return A.trashPaths(selectedPaths(tab())); }
    if (k === ' ') { e.preventDefault(); const p = selectedPaths(tab())[0]; if (p) return A.preview(p); }
    if (k === 'ArrowDown' || k === 'ArrowUp') {
      const t = tab(); if (!t) return;
      const arr = entriesOf(t); if (!arr.length) return;
      const cur = arr.findIndex(x => t.sel.has(x.path));
      const n = Math.max(0, Math.min(arr.length - 1, (cur < 0 ? 0 : cur) + (k === 'ArrowDown' ? 1 : -1)));
      e.preventDefault(); A.setSelection(S.activePane, arr[n].path, shift ? 'shift' : 'single');
      $(`#panes .pane[data-pi="${S.activePane}"] .row.sel`)?.scrollIntoView({block:'nearest'});
      return;
    }
    if (k === 'Enter') {
      const p = selectedPaths(tab())[0]; if (!p) return;
      e.preventDefault();
      if (ctrl) return A.revealEntry(p);
      return A.activate(p, S.activePane, findEntry(tab(), p));
    }
  });
  addEventListener('resize', () => { M.closeCtx(); positionPaneSplit(); });
}

async function boot() {
  try {
    if (!DEMO) await waitBridge();
    S.appInfo = await api('app.info');
    await loadState();
    const [d, sp, st] = await Promise.all([
      api('dir.drives'), api('dir.special'), api('search.status', {probe: true}),
    ]);
    S.drives = d.drives || []; S.specials = sp.items || []; S.searchStatus = st || {};
    buildPanes();
    renderSidebar(); renderStatus();
    bindTopbar(); bindSidebar(); bindPalette(); bindKeys(); bindPaneSplit(); D.bindDragOut();
    $$('#panes .pane').forEach((el, i) => bindPane(el, i));
    for (let i = 0; i < visibleCount(); i++) {
      const t = tab(i);
      if (t && !t.path) { /* 后端会把空路径展开为用户主目录 */ }
      await A.loadDir(i);
    }
    renderPanes(); renderStatus('就绪 · 目录 / 全盘搜索 / 文件夹内搜索共用同一套打开逻辑');
    window.FMP = {
      onGlobalHotkey: Q.onGlobalHotkey,
      persist: () => saveState(),
      version: APP_META.version,
    };
    // 启动握手：验证前端 → js_api → 配置层的链路，并记录本次启动时间
    await api('state.set', {patch: {last_launch: Date.now()}});
    document.body.dataset.ready = '1';
    uiLog('boot ok | transport=http | panes=' + visibleCount());
  } catch (ex) {
    uiLog('BOOT FAILED: ' + (ex.stack || ex.message));
    document.body.innerHTML = `<div style="padding:40px;font:14px/1.8 sans-serif;color:#c33">
      <b>启动失败</b>：${esc(ex.message)}<br><br>
      本地命令服务未就绪。请关闭本窗口后重新启动程序；若仍失败，
      可查看 ${APP_META.dataDir}\\ui.log 中的诊断信息。<br><br>
      <button id="fmp-retry" style="padding:7px 16px;border:1px solid #d66;border-radius:7px;
        background:#fff;color:#c33;cursor:pointer">重新加载</button></div>`;
    const rb = document.getElementById('fmp-retry');
    if (rb) rb.onclick = () => location.reload();
  }
}
boot();
