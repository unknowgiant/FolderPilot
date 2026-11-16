// 命令层：所有「打开」类操作只接受绝对路径，不再按名称反查当前目录
import { api } from './api.js';
import { S, tab, entriesOf, findEntry, selectedPaths, targetDir, saveState,
  applyTheme, applyDensity, applyColWidths, applyPaneRatio, setCols, visibleCount,
  DEFAULT_COLW, MIN_COLW, MAX_COLW } from './store.js';
import { renderPane, renderPanes, renderSidebar, renderStatus, refreshSelection } from './view.js';
import { $, $$, toast, normKey, basename, dirname, joinPath, esc, fmtSize, fmtDate,
  fileUrl, iconSvg, COLORS, colorVar } from './util.js';

export async function activate(path, i = S.activePane, providedEntry = null) {
  if (!path) return;
  let e = providedEntry || findEntry(tab(i), path);
  if (!e) {
    // 兜底：即便条目不在当前列表，绝对路径依然足以打开（旧版正是在这里失效）
    try {
      const r = await api('entry.stat', {paths: [path]});
      e = r.entries?.[0];
    } catch (_) {}
  }
  const isDir = e ? e.is_dir : false;
  try {
    if (isDir) await navigate(path, i);
    else { await api('entry.open', {path}); toast('已打开：' + basename(path)); }
  } catch (ex) { toast('打开失败：' + ex.message, true); }
}

export async function navigate(path, i = S.activePane, opt = {}) {
  if (!path) return;
  const low = path.toLowerCase();
  if (['cmd', 'wt', 'powershell', 'pwsh'].includes(low)) {
    return api('entry.terminal', {path: targetDir(tab(i)) || processPath(), kind: low});
  }
  const t = tab(i), p = S.panes[i];
  if (!t || !p) return;
  if (opt.newTab) {
    const nt = (await import('./store.js')).makeTab(path);
    p.tabs.splice(p.active + 1, 0, nt);
    p.active += 1;
    return loadDir(i);
  }
  t.path = path;
  t.title = path === '::{THISPC}' ? '此电脑' : (basename(path) || path);
  t.mode = 'dir'; t.results = []; t.query = null; t.searchMeta = {}; t.scroll = 0;
  t.searchOpen = false;                 // 从搜索结果进入目录后，收起搜索条避免状态错位
  t.sel.clear(); t.anchor = '';
  if (opt.addHistory !== false && !opt.noHistory) {
    if (t.histIdx < t.history.length - 1) t.history = t.history.slice(0, t.histIdx + 1);
    if (t.history[t.histIdx] !== path) { t.history.push(path); t.histIdx = t.history.length - 1; }
  }
  S.activePane = i;
  return loadDir(i);
}
function processPath() { return S.specials[0]?.path || 'C:\\'; }

export async function loadDir(i = S.activePane) {
  const t = tab(i); if (!t) return;
  t.loading = true;
  renderPane(i);
  try {
    const r = await api('dir.list', {path: t.path, show_hidden: S.cfg.show_hidden});
    t.items = r.entries || [];
    t.path = r.path || t.path;
    t.title = t.path === '::{THISPC}' ? '此电脑' : (basename(t.path) || t.path);
  } catch (ex) {
    t.items = []; toast(ex.message, true);
  }
  t.loading = false;
  renderPane(i); renderSidebar(); renderStatus(`${t.path} · ${t.items.length} 项`);
  saveState();
  return t;
}

export async function refresh(i = S.activePane) {
  const t = tab(i); if (!t) return;
  if (t.mode === 'search' && t.query) {
    const { runPaneSearch } = await import('./search.js');
    return runPaneSearch(i, true);
  }
  return loadDir(i);
}

export function historyMove(delta, i = S.activePane) {
  const t = tab(i); if (!t) return;
  const n = t.histIdx + delta;
  if (n < 0 || n >= t.history.length) return;
  t.histIdx = n;
  return navigate(t.history[n], i, {addHistory: false});
}

export async function revealEntry(path, i = S.activePane) {
  const parent = dirname(path);
  await navigate(parent, i);
  const t = tab(i);
  if (t) { t.sel.clear(); t.sel.add(path); renderPane(i); }
  renderStatus('已定位到：' + basename(path));
}

export async function openInNewTab(path, i = S.activePane) {
  const {makeTab} = await import('./store.js');
  const p = S.panes[i];
  const nt = makeTab(path);
  p.tabs.splice(p.active + 1, 0, nt); p.active += 1; S.activePane = i;
  renderPanes(); await loadDir(i);
}

export function newTab(i = S.activePane) {
  return import('./store.js').then(m => {
    const p = S.panes[i], nt = m.makeTab(S.panes[i].tabs[p.active]?.path || '');
    p.tabs.push(nt); p.active = p.tabs.length - 1; S.activePane = i;
    renderPanes(); return loadDir(i);
  });
}
export async function closeTab(i = S.activePane, ti = null) {
  const p = S.panes[i];
  const idx = ti == null ? p.active : ti;
  if (p.tabs.length === 1) {
    const m = await import('./store.js');
    p.tabs[0] = m.makeTab(p.tabs[0].path || '');
  } else {
    p.tabs.splice(idx, 1); p.active = Math.min(p.active, p.tabs.length - 1);
  }
  renderPanes(); return loadDir(i);
}

export function setActivePane(i) {
  if (i >= visibleCount()) return;
  S.activePane = i; renderPanes();
}
export function setLayout(n) {
  S.layout = Math.min(Math.max(Number(n) || 2, 1), 5);
  S.cfg.layout = S.layout;
  if (S.activePane >= visibleCount()) S.activePane = 0;
  renderPanes();
  // 新显示出来的窗格可能尚未加载过目录，补一次加载
  for (let i = 0; i < visibleCount(); i++) {
    const t = tab(i);
    if (t && t.mode === 'dir' && (!t.path || !t.items.length)) loadDir(i);
  }
  saveState();
}
export function setView(v, i = S.activePane) {
  const t = tab(i); if (!t) return;
  t.view = v; renderPane(i); saveState();
}
export function sortBy(key, i = S.activePane) {
  const t = tab(i); if (!t) return;
  t.sort = t.sort.key === key ? {key, dir: -t.sort.dir} : {key, dir: 1};
  renderPane(i); saveState();
}
export function toggleTheme() {
  const order = ['light', 'dark', 'system'];
  S.cfg.theme = order[(order.indexOf(S.cfg.theme || 'light') + 1) % 3];
  applyTheme(); saveState(); toast('主题：' + ({light:'浅色', dark:'深色', system:'跟随系统'}[S.cfg.theme]));
}
export function setDensity(v) { S.cfg.density = v; applyDensity(); saveState(); }
export function updateColWidth(key, px) {
  S.cfg.colw = S.cfg.colw || {};
  if (key === 'name' && px <= 0) S.cfg.colw.name = 0;      // 0 = 自动填满
  else {
    const lo = (MIN_COLW[key] ?? 56), hi = (MAX_COLW[key] ?? 420);
    S.cfg.colw[key] = Math.max(lo, Math.min(hi, Math.round(px)));
  }
  // 只改 CSS 变量即可让列头与所有行同步重排，不必重建 DOM
  setCols(); applyColWidths(); saveState();
}
export function resetColWidths() {
  S.cfg.colw = {...DEFAULT_COLW};
  S.cfg.pane_ratio = 50;
  S.cfg.name_only = false;
  setCols(); applyColWidths(); saveState();
}
export function setNameOnly(on) {
  S.cfg.name_only = !!on;
  setCols(); saveState();
}
export function setPaneRatio(p) {
  S.cfg.pane_ratio = Math.max(25, Math.min(75, Math.round(p)));
  applyPaneRatio(); saveState();
}

// ---------- 选择 / 剪贴板 / 文件操作 ----------
export function setSelection(i, path, mode = 'single') {
  const t = tab(i); if (!t) return;
  const arr = entriesOf(t);
  if (mode === 'shift' && t.anchor) {
    const a = arr.findIndex(x => x.path === t.anchor), b = arr.findIndex(x => x.path === path);
    if (a >= 0 && b >= 0) {
      t.sel.clear();
      for (let k = Math.min(a, b); k <= Math.max(a, b); k++) t.sel.add(arr[k].path);
    }
  } else if (mode === 'ctrl') {
    if (t.sel.has(path)) t.sel.delete(path); else { t.sel.add(path); t.anchor = path; }
  } else {
    t.sel.clear(); t.sel.add(path); t.anchor = path;
  }
  refreshSelection(i);
}
export function selectAll(i = S.activePane) {
  const t = tab(i); if (!t) return;
  t.sel = new Set(entriesOf(t).map(e => e.path)); refreshSelection(i);
}

export async function copySel(i = S.activePane, cut = false) {
  const t = tab(i), paths = selectedPaths(t);
  if (!paths.length) return;
  S.clip = {paths, move: cut};
  S._cut = cut ? new Set(paths.map(normKey)) : new Set();
  try { await api('clip.write', {paths, move: cut}); } catch (ex) { toast('剪贴板：' + ex.message, true); }
  renderPanes(); toast(`${cut ? '已剪切' : '已复制'} ${paths.length} 项`);
}

export async function paste(i = S.activePane) {
  const t = tab(i); if (!t || t.mode === 'search') { toast('请先切换到文件夹视图再粘贴', true); return; }
  let paths = S.clip.paths, move = S.clip.move;
  if (!paths.length) {
    try { const r = await api('clip.read'); paths = r.paths || []; move = r.move; }
    catch (ex) { return toast(ex.message, true); }
  }
  if (!paths.length) return toast('剪贴板中没有文件', true);
  await transfer(paths, t.path, move, i);
  S._cut.clear();
}

export async function transfer(paths, dest, move, i = S.activePane) {
  try {
    const r = await api(move ? 'ops.move' : 'ops.copy', {paths, dest});
    toast(`${move ? '移动' : '复制'}任务已开始`);
    await pollTask(r.job, () => refresh(i));
  } catch (ex) { toast(ex.message, true); }
}
export async function pollTask(job, onDone) {
  if (!job) return;
  const box = $('#tasks');
  const card = document.createElement('div');
  card.className = 'task-card';
  card.innerHTML = `<div class="tt">正在处理…</div><div class="bar"><i style="width:0%"></i></div><div class="ts"></div>`;
  box.appendChild(card);
  for (let k = 0; k < 600; k++) {
    let s;
    try { s = await api('task.status', {id: job}); } catch (_) { break; }
    const pct = s.total ? Math.round(s.done / s.total * 100) : 0;
    card.querySelector('.tt').textContent = `${s.state === 'move' ? '移动' : '复制'}中 ${s.done}/${s.total}`;
    card.querySelector('.bar i').style.width = pct + '%';
    card.querySelector('.ts').textContent = s.current || (s.error || '');
    if (['done', 'error', 'cancelled', 'missing'].includes(s.state)) break;
    await new Promise(r => setTimeout(r, 220));
  }
  card.remove();
  if (onDone) await onDone();
  toast('任务完成');
}

export async function trashPaths(paths, i = S.activePane) {
  if (!paths.length) return;
  if (S.cfg.confirm_delete !== false && !confirm(`确定把选中的 ${paths.length} 项移入回收站？`)) return;
  try { await api('ops.trash', {paths}); toast('已移入回收站'); await refresh(i); }
  catch (ex) { toast(ex.message, true); }
}
export async function doRename(path, name, i = S.activePane) {
  try { await api('ops.rename', {path, name}); await refresh(i); toast('已重命名'); }
  catch (ex) { toast(ex.message, true); }
}
export async function makeFolder(i = S.activePane) {
  const t = tab(i); if (!t || !t.path) return;
  try { const r = await api('ops.mkdir', {parent: t.path}); await refresh(i); toast('已新建：' + basename(r.path)); }
  catch (ex) { toast(ex.message, true); }
}
export async function makeText(i = S.activePane) {
  const t = tab(i); if (!t || !t.path) return;
  try { const r = await api('ops.newtext', {parent: t.path}); await refresh(i); toast('已新建：' + basename(r.path)); }
  catch (ex) { toast(ex.message, true); }
}
export async function zipSel(i = S.activePane) {
  const t = tab(i), paths = selectedPaths(t);
  if (!paths.length) return;
  try {
    const dest = joinPath(t.path, basename(paths[0]) + '.zip');
    const r = await api('ops.zip', {paths, dest}); await refresh(i); toast('已压缩：' + basename(r.path));
  } catch (ex) { toast(ex.message, true); }
}
export async function unzipHere(path, i = S.activePane) {
  const t = tab(i);
  try { await api('ops.unzip', {path, dest: t.path}); await refresh(i); toast('已解压到当前文件夹'); }
  catch (ex) { toast(ex.message, true); }
}
export async function openTerminal(i = S.activePane, kind = 'auto') {
  const t = tab(i); if (!t?.path) return;
  try { await api('entry.terminal', {path: t.path, kind}); } catch (ex) { toast(ex.message, true); }
}
export async function copyText(text) {
  try { await api('clip.text', {text}); toast('已复制路径'); } catch (ex) { toast(ex.message, true); }
}
export async function setTag(paths, color, i = S.activePane) {
  for (const p of paths) {
    if (color) S.tags[normKey(p)] = color;
    else delete S.tags[normKey(p)];
  }
  try { await api('tags.set', {paths, color}); } catch (_) {}
  renderPane(i); renderSidebar(); saveState();
}
export async function addFavorite(path) {
  if (!path || S.favorites.includes(path)) return;
  S.favorites.push(path); renderSidebar(); saveState(); toast('已固定：' + basename(path));
}
export async function removeFavorite(path) {
  S.favorites = S.favorites.filter(x => x !== path); renderSidebar(); saveState();
}
export async function trayAdd(paths) {
  for (const p of paths) if (!S.tray.includes(p)) S.tray.push(p);
  saveState(); renderStatus(); toast(`暂存盘 +${paths.length}`);
  const b = $('#tray-count'); if (b) b.textContent = S.tray.length;
}
export async function trayRemove(path) { S.tray = S.tray.filter(x => x !== path); saveState(); }
export async function trayTransfer(move, i = S.activePane) {
  const t = tab(i); if (!t?.path || !S.tray.length) return;
  await transfer(S.tray.slice(), t.path, move, i);
  if (move) S.tray = [];
  saveState();
}

// ---------- 右侧抽屉：预览 ----------
export async function preview(path) {
  const d = $('#drawer'), body = $('#drawer-body');
  d.classList.remove('hidden');
  $('#drawer-title').textContent = '预览 · ' + basename(path);
  body.innerHTML = '<div class="hint">加载中…</div>';
  let r;
  try { r = await api('entry.preview', {path}); }
  catch (ex) { body.innerHTML = `<div class="hint">${esc(ex.message)}</div>`; return; }
  S.preview = r;
  const meta = `<div class="pv-meta">
    <span class="k">名称</span><span class="v" title="${esc(r.name)}">${esc(r.name)}</span>
    <span class="k">位置</span><span class="v" title="${esc(r.parent)}">${esc(r.parent)}</span>
    <span class="k">大小</span><span class="v">${fmtSize(r.size)}</span>
    <span class="k">修改时间</span><span class="v">${fmtDate(r.mtime)}</span></div>`;
  let content = '';
  if (r.preview === 'image') content = `<img class="pv-img" src="${fileUrl(path)}" alt="">`;
  else if (r.preview === 'video') content = `<video controls style="max-width:100%;max-height:70vh" src="${fileUrl(path)}"></video>`;
  else if (r.preview === 'audio') content = `<audio controls style="width:100%" src="${fileUrl(path)}"></audio>`;
  else if (r.preview === 'pdf') content = `<iframe class="pv-frame" src="${fileUrl(path)}"></iframe>`;
  else if (r.preview === 'text') content = `<pre class="pv-text">${esc(r.text || '')}</pre>`;
  else if (r.preview === 'archive') {
    content = `<div class="tray-actions"><button class="btn" data-act="unzip">全部解压到当前文件夹</button></div>` +
      (r.archive_entries || []).map(x => `<div class="arc-row" data-member="${esc(x.name)}">
        <svg class="i"><use href="#${x.is_dir ? 'ic-folder' : 'ic-file'}"/></svg>
        <span class="an" title="${esc(x.name)}">${esc(x.name)}</span><span class="as">${fmtSize(x.size)}</span></div>`).join('');
  } else content = `<div class="hint">此格式不提供内嵌预览，可右键用系统程序打开。</div>`;
  body.innerHTML = meta + content;
  body.querySelectorAll('[data-act="unzip"]').forEach(b => b.onclick = () => unzipHere(path));
  body.querySelectorAll('[data-member]').forEach(el => el.ondblclick = async () => {
    try { const t = tab(); await api('ops.extract', {path, member: el.dataset.member, dest: t.path}); toast('已提取'); refresh(); }
    catch (ex) { toast(ex.message, true); }
  });
}
export function closeDrawer() { $('#drawer').classList.add('hidden'); S.preview = null; }
