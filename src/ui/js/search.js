// 统一搜索管线：全局命令面板与「文件夹内搜索」共用 search.run，
// 结果一律写入带 path 的 FileEntry；两者只是 scope 不同。
import { api } from './api.js';
import { S, tab, saveState, visibleCount } from './store.js';
import { renderPane, renderStatus } from './view.js';
import { $, $$, esc, fmtSize, fmtDate, iconSvg, highlight, toast, debounce, basename } from './util.js';

let paneRunId = 0;

export function paneSearchOpen(i) { return !!tab(i)?.searchOpen; }

export function togglePaneSearch(i = S.activePane) {
  const t = tab(i); if (!t) return;
  const el = $(`#panes .pane[data-pi="${i}"]`);
  t.searchOpen = !t.searchOpen;
  if (t.searchOpen) {
    renderPane(i);
    const inp = el.querySelector('.sb-input');
    if (t.query?.query && !inp.value) inp.value = t.query.query;
    inp.focus();
  } else exitPaneSearch(i);
}

export function exitPaneSearch(i = S.activePane) {
  const t = tab(i); if (!t) return;
  paneRunId++;                       // 作废在途请求
  t.searchOpen = false;
  t.mode = 'dir'; t.results = []; t.query = null; t.searchMeta = {};
  t.sel.clear();
  const el = $(`#panes .pane[data-pi="${i}"]`);
  if (el) {
    const inp = el.querySelector('.sb-input'); if (inp) inp.value = '';
    const sc = el.querySelector('.sb-scope'); if (sc) sc.value = 'folder';
    const kd = el.querySelector('.sb-kind'); if (kd) kd.value = '';
  }
  renderPane(i); renderStatus(t.path);
}

export function paneOptions(i) {
  const el = $(`#panes .pane[data-pi="${i}"]`);
  if (!el) return {};
  return {
    query: el.querySelector('.sb-input').value.trim(),
    scope: el.querySelector('.sb-scope').value,
    ext: el.querySelector('.sb-kind').value,
  };
}

export async function runPaneSearch(i = S.activePane, force = false) {
  const t = tab(i); if (!t || !t.searchOpen) return;
  const o = paneOptions(i);
  if (!o.query && !o.ext) { exitPaneSearch(i); return; }
  const req = {
    query: o.query, scope: o.scope, root: t.path || '', ext: o.ext,
    limit: S.cfg.ev_max || 500, case: false, whole_word: false, content: false,
  };
  const rid = ++paneRunId;
  // 立即进入搜索视图并给出「正在检索」反馈，避免大目录本地扫描时像卡死
  t.loading = true; t.mode = 'search'; t.scroll = 0;
  t.results = []; t.query = req; t.sel.clear();
  t.searchMeta = {backend: '正在检索'};
  renderPane(i);
  renderStatus('正在搜索「' + (o.query || o.ext) + '」…');
  try {
    const r = await api('search.run', req);
    if (rid !== paneRunId) return;              // 过期结果直接丢弃
    t.mode = 'search'; t.scroll = 0;
    t.results = r.entries || [];
    t.query = req;
    t.searchMeta = {total: r.total, backend: r.backend, elapsed: r.elapsed, note: r.note};
    t.sel.clear();
    S.searchStatus.backend = r.backend;
    if (o.query) S.history = [o.query, ...S.history.filter(x => x !== o.query)].slice(0, 40);
    saveState();
  } catch (ex) {
    t.searchMeta = {backend: '搜索失败', note: ex.message};
    toast('搜索失败：' + ex.message, true);
  }
  t.loading = false;
  renderPane(i);
  renderStatus(`搜索「${o.query || o.ext}」 · ${t.results.length} 项 · ${t.searchMeta.backend || ''} ${t.searchMeta.elapsed ?? ''}ms`);
}
export const schedulePaneSearch = debounce((i) => runPaneSearch(i), 340);

export function switchPaneScope(i = S.activePane) {
  const t = tab(i); if (!t) return;
  const el = $(`#panes .pane[data-pi="${i}"]`);
  const sc = el.querySelector('.sb-scope');
  sc.value = sc.value === 'folder' ? 'global' : 'folder';
  return runPaneSearch(i, true);
}
export function searchFolderToGlobal(i = S.activePane) {
  const el = $(`#panes .pane[data-pi="${i}"]`);
  const inp = el.querySelector('.sb-input');
  openPalette(inp.value || tab(i)?.query?.query || '', 'global');
}

// ---------- 全局命令面板 ----------
export function openPalette(initial = '', scope = 'global') {
  const pal = $('#palette');
  pal.classList.remove('hidden');
  S.pal.open = true; S.pal.scope = scope;
  $$('#pal-scope-chips .chip').forEach(c => c.classList.toggle('on', c.dataset.scope === scope));
  const inp = $('#pal-input');
  if (initial) inp.value = initial;
  inp.focus(); inp.select();
  if (initial || S.pal.results.length) palRun();
}
export function closePalette() {
  $('#palette').classList.add('hidden');
  S.pal.open = false;
}
export function palSetScope(scope) {
  S.pal.scope = scope;
  $$('#pal-scope-chips .chip').forEach(c => c.classList.toggle('on', c.dataset.scope === scope));
  palRun();
}
export function palRequest() {
  const val = id => ($(id)?.value || '').trim();
  return {
    query: $('#pal-input').value.trim(),
    scope: S.pal.scope,
    root: tab()?.path || '',
    ext: val('#pal-ext'),
    size_min: val('#pal-smin'), size_max: val('#pal-smax'),
    case: !!$('#pal-case')?.checked,
    whole_word: !!$('#pal-word')?.checked,
    content: !!$('#pal-content')?.checked,
    limit: S.cfg.ev_max || 500,
  };
}
export async function palRun() {
  const req = palRequest();
  const rid = ++S.pal.runId;
  if (!req.query && !req.ext) {
    S.pal.results = []; palRender(); $('#pal-stat').textContent = '输入关键字开始搜索'; return;
  }
  $('#pal-stat').textContent = '搜索中…';
  try {
    const r = await api('search.run', req);
    if (rid !== S.pal.runId) return;
    S.pal.results = r.entries || [];
    S.pal.query = req.query;
    S.pal.sel = 0;
    S.pal.meta = r;
    S.searchStatus.backend = r.backend;
    $('#pal-stat').textContent = `${r.backend} · ${r.elapsed}ms · ${r.total || S.pal.results.length} 项` + (r.note ? ' · ' + r.note : '');
    if (req.query) S.history = [req.query, ...S.history.filter(x => x !== req.query)].slice(0, 40);
    saveState();
  } catch (ex) {
    $('#pal-stat').textContent = '搜索失败：' + ex.message;
    S.pal.results = [];
  }
  palRender(); renderStatus();
}
export const schedulePalRun = debounce(() => palRun(), 280);

export function palRender() {
  const box = $('#pal-res');
  if (!S.pal.results.length) {
    box.innerHTML = `<div class="empty" style="height:180px"><svg class="i"><use href="#ic-search"/></svg>
      <span>输入关键字，全盘文件即刻呈现</span></div>`;
    return;
  }
  box.innerHTML = S.pal.results.map((e, i) => `
    <div class="prow${i === S.pal.sel ? ' on' : ''}" data-path="${esc(e.path)}" data-idx="${i}">
      <span class="pi">${iconSvg(e)}</span>
      <span class="pmain"><span class="pn" title="${esc(e.name)}">${highlight(e.name, S.pal.query)}</span>
        <span class="pp" title="${esc(e.parent)}">${esc(e.parent)}</span></span>
      <span class="pm" title="${esc(e.parent)}">${esc(basename(e.parent) || e.name)}</span>
      <span class="pd">${e.is_dir ? '文件夹' : fmtSize(e.size)} · ${fmtDate(e.mtime)}</span>
    </div>`).join('');
}
export function palMove(d) {
  if (!S.pal.results.length) return;
  S.pal.sel = (S.pal.sel + d + S.pal.results.length) % S.pal.results.length;
  palRender();
  $('#pal-res .prow.on')?.scrollIntoView({block: 'nearest'});
}
export function palSelectedPath() { return S.pal.results[S.pal.sel]?.path || ''; }
export function palEntryByPath(path) { return S.pal.results.find(e => e.path === path) || null; }

export async function onGlobalHotkey() {
  // Alt+Space：唤起窗口并聚焦全盘搜索
  openPalette('', 'global');
  setTimeout(() => $('#pal-input')?.focus(), 30);
}
