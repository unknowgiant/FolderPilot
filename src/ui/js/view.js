// 渲染层：只根据 S 生成 DOM，不持有业务状态、不直接调用后端命令
import { S, tab, entriesOf, visibleCount } from './store.js';
import { $, $$, esc, fmtSize, fmtDate, iconSvg, highlight, normKey, basename,
  COLORS, COLOR_NAMES, colorVar, fileUrl } from './util.js';

const KIND_FILTERS = [
  ['', '全部类型'], ['doc;docx;xls;xlsx;ppt;pptx;pdf;wps;txt;md', '文档'],
  ['dwg;dxf;vsdx', '图纸'], ['png;jpg;jpeg;gif;bmp;webp;svg', '图片'],
  ['mp4;mkv;avi;mov;mp3;wav;flac', '音视频'], ['zip;rar;7z', '压缩包'],
];
export { KIND_FILTERS };

const LAYOUT_ICONS = {
  1: '<rect x="4" y="4" width="16" height="16" rx="2"/>',
  2: '<rect x="3" y="4" width="8" height="16" rx="1.5"/><rect x="13" y="4" width="8" height="16" rx="1.5"/>',
  3: '<rect x="4" y="3" width="16" height="8" rx="1.5"/><rect x="4" y="13" width="16" height="8" rx="1.5"/>',
  4: '<rect x="2" y="4" width="6" height="16" rx="1.5"/><rect x="9" y="4" width="6" height="16" rx="1.5"/><rect x="16" y="4" width="6" height="16" rx="1.5"/>',
  5: '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/>',
};
const LAYOUT_CLASS = {1:'lay-1', 2:'lay-2', 3:'lay-2v', 4:'lay-3', 5:'lay-4'};
const LAYOUT_NAMES = {1:'单栏', 2:'左右分屏', 3:'上下分屏', 4:'三栏', 5:'四宫格'};

export function renderLayoutButtons() {
  const box = $('#layout-switch');
  box.innerHTML = [1,2,3,4,5].map(n =>
    `<button class="lbtn${S.layout===n?' on':''}" data-layout="${n}" title="${LAYOUT_NAMES[n]} (Ctrl+${n})">
      <svg viewBox="0 0 24 24">${LAYOUT_ICONS[n]}</svg></button>`).join('');
}

function paneSkeleton(i) {
  return `<div class="pane" data-pi="${i}">
    <div class="tabs"></div>
    <div class="toolbar">
      <button class="navbtn" data-act="back" title="后退 (Alt+←)"><svg class="i"><use href="#ic-back"/></svg></button>
      <button class="navbtn" data-act="forward" title="前进 (Alt+→)"><svg class="i"><use href="#ic-fwd"/></svg></button>
      <button class="navbtn" data-act="up" title="上一级 (Backspace)"><svg class="i"><use href="#ic-up"/></svg></button>
      <button class="navbtn" data-act="refresh" title="刷新 (F5)"><svg class="i"><use href="#ic-refresh"/></svg></button>
      <button class="navbtn" data-act="home" title="转到主目录"><svg class="i"><use href="#ic-home"/></svg></button>
      <div class="addr" data-act="addr"><span class="ap"></span></div>
      <button class="navbtn" data-act="search" title="在当前文件夹内搜索 (含子目录)"><svg class="i"><use href="#ic-search"/></svg></button>
      <button class="navbtn" data-act="more" title="更多操作"><svg class="i"><use href="#ic-dots"/></svg></button>
    </div>
    <div class="searchbar hidden">
      <svg class="i sb-ic"><use href="#ic-search"/></svg>
      <input class="sb-input" placeholder="在当前文件夹（含子目录）搜索文件名…" spellcheck="false">
      <select class="sb-scope" title="搜索范围"><option value="folder">当前文件夹</option><option value="global">全盘</option></select>
      <select class="sb-kind" title="类型筛选">${KIND_FILTERS.map(([v,n])=>`<option value="${esc(v)}">${n}</option>`).join('')}</select>
      <button class="sb-btn" data-act="s-global" title="把同样的关键字改为全盘搜索">全盘再搜</button>
      <button class="sb-btn sb-close" data-act="s-exit" title="退出搜索 (Esc)"><svg class="i" style="width:13px;height:13px"><use href="#ic-x"/></svg></button>
    </div>
    <div class="searchctx hidden"></div>
    <div class="lhead"></div>
    <div class="lbody" tabindex="0"></div>
  </div>`;
}

export function buildPanes() {
  $('#panes').innerHTML = Array.from({length: 5}, (_, i) => paneSkeleton(i)).join('');
  renderPanes();
}
export function renderPanes() {
  $$('#panes .pane').forEach((el, i) => {
    el.classList.toggle('hidden', i >= visibleCount());
    el.classList.toggle('active', i === S.activePane && i < visibleCount());
  });
  const p = $('#panes');
  p.className = 'panes ' + (LAYOUT_CLASS[S.layout] || 'lay-2');
  for (let i = 0; i < visibleCount(); i++) renderPane(i);
  renderLayoutButtons();
  positionPaneSplit();
}

function headHtml(t) {
  const cols = [
    ['name', '名称'], ['size', '大小'], ['mtime', '修改时间'],
    [t.mode === 'search' ? 'parent' : 'type', t.mode === 'search' ? '位于' : '类型'],
  ];
  const html = cols.map(([k, label]) => {
    const num = (k === 'size' || k === 'mtime') ? ' num' : '';
    const on = t.sort.key === k ? ' on' : '';
    const arrow = on ? `<svg class="i" style="width:11px;height:11px;transform:${t.sort.dir === -1 ? 'rotate(180deg)' : ''}"><use href="#ic-up"/></svg>` : '';
    // 名称列也可拖：双击手柄恢复「自动填满」
    const tip = k === 'name' ? '拖动调整名称列宽，双击恢复自动' : '拖动调整列宽';
    // 搜索模式的「位于」与「类型」占用同一条网格轨道，宽度共用同一配置
    const gkey = k === 'parent' ? 'type' : k;
    const grip = `<span class="grip${k === 'name' ? ' grip-name' : ''}" data-grip="${gkey}" title="${tip}"></span>`;
    return `<div class="hc${num}${on}" data-sort="${k}"><span>${label}</span>${arrow}${grip}</div>`;
  }).join('');
  // 右侧「列宽」入口：绝对定位，不占用网格列，避免与数据行错位
  return html + `<button class="hc-cw" data-act="colwidth" title="列宽与窗格宽度设置…">
    <svg class="i"><use href="#ic-columns"/></svg><span>列宽</span></button>`;
}

// 左右分屏中间的可拖拽分隔条（按当前分栏比例定位）
export function positionPaneSplit() {
  const el = $('#pane-split');
  if (!el) return;
  const horizontal = S.layout === 2 && S.cfg.layout_mode !== 'v';
  el.classList.toggle('hidden', !horizontal);
  if (!horizontal) return;
  const p0 = $('#panes .pane[data-pi="0"]');
  const wrap = $('#workarea');
  if (!p0 || !wrap) return;
  const a = p0.getBoundingClientRect(), w = wrap.getBoundingClientRect();
  el.style.left = (a.right - w.left - 5) + 'px';
}

function tagDots(path) {
  const c = S.tags[normKey(path)];
  return `<span class="tagdots">${c ? `<i style="background:${colorVar(c)}" title="已标记"></i>` : ''}</span>`;
}

function rowHtml(e, t) {
  const sel = t.sel.has(e.path) ? ' sel' : '';
  const cut = S._cut.has(normKey(e.path)) ? ' cut' : '';
  const kw = t.mode === 'search' ? (t.query?.query || '') : '';
  const name = `<span class="fname" title="${esc(e.name)}">${highlight(e.name, kw)}</span>`;
  const first = t.mode === 'search'
    ? `<span class="nm"><span class="line1">${iconSvg(e)}<span class="fname" title="${esc(e.name)}">${highlight(e.name, kw)}</span>${tagDots(e.path)}</span>
         <span class="rel" title="${esc(e.rel || e.parent)}">${esc(e.rel || e.parent)}</span></span>`
    : `<span class="nm">${iconSvg(e)}<span class="fname" title="${esc(e.name)}">${name}</span>${tagDots(e.path)}</span>`;
  const last = t.mode === 'search'
    ? `<span class="cell dim" title="${esc(e.parent)}">${esc(basename(e.parent) || e.parent)}</span>`
    : `<span class="cell" title="${esc(e.kind)}">${esc(e.kind)}</span>`;
  // draggable 已移除：拖拽由 dragdrop.js 手动接管（HTML5 拖拽无法拖出窗口）
  return `<div class="row${sel}${cut}" data-path="${esc(e.path)}">
      ${first}
      <span class="cell num">${e.is_dir ? '' : fmtSize(e.size)}</span>
      <span class="cell num" title="${fmtDate(e.mtime)}">${fmtDate(e.mtime)}</span>
      ${last}
    </div>`;
}
function tileHtml(e, t) {
  const sel = t.sel.has(e.path) ? ' sel' : '';
  const isImg = ['png','jpg','jpeg','gif','bmp','webp','svg','ico'].includes((e.ext||'').toLowerCase()) && e.size < 25e6;
  const thumb = isImg ? `<img src="${fileUrl(e.path)}" alt="" loading="lazy">` : iconSvg(e);
  return `<div class="tile${sel}" data-path="${esc(e.path)}">
    <div class="thumb">${thumb}</div><span class="tt" title="${esc(e.name)}">${esc(e.name)}</span></div>`;
}

export function sortedEntries(t) {
  const arr = entriesOf(t).slice();
  const k = t.sort.key, d = t.sort.dir || 1;
  arr.sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
    let r = 0;
    if (k === 'size') r = (a.size || 0) - (b.size || 0);
    else if (k === 'mtime') r = (a.mtime || 0) - (b.mtime || 0);
    else if (k === 'type') r = String(a.kind).localeCompare(String(b.kind), 'zh-CN') || a.name.localeCompare(b.name, 'zh-CN');
    else if (k === 'parent') r = String(a.parent).localeCompare(String(b.parent), 'zh-CN') || a.name.localeCompare(b.name, 'zh-CN');
    else r = a.name.localeCompare(b.name, 'zh-CN', {numeric: true});
    return r * d;
  });
  return arr;
}

export function renderPane(i) {
  const el = $(`#panes .pane[data-pi="${i}"]`);
  const t = tab(i);
  if (!el || !t) return;
  const p = S.panes[i];
  el.classList.toggle('search-mode', t.mode === 'search');
  el.querySelector('.tabs').innerHTML = p.tabs.map((x, j) =>
    `<div class="tab${j === p.active ? ' on' : ''}" data-ti="${j}" title="${esc(x.path || x.title)}">
       <span class="tn">${esc(x.mode === 'search' ? '🔍 ' + (x.query?.query || '搜索') : x.title)}</span>
       <span class="tx" data-act="tab-close" data-ti="${j}">×</span></div>`).join('') +
    `<button class="tab-add" data-act="tab-add" title="新建标签页 (Ctrl+T)"><svg class="i" style="width:13px;height:13px"><use href="#ic-plus"/></svg></button>`;

  const addr = el.querySelector('.addr');
  const ap = addr.querySelector('.ap');
  if (!addr.querySelector('input')) {
    ap.textContent = t.path || '新标签页';
    ap.title = t.path || '';
    addr.title = t.path || '';
  }
  el.querySelector('[data-act="back"]').disabled = t.histIdx <= 0;
  el.querySelector('[data-act="forward"]').disabled = t.histIdx >= t.history.length - 1;
  el.querySelector('[data-act="search"]').classList.toggle('on', !!t.searchOpen);

  const sb = el.querySelector('.searchbar');
  sb.classList.toggle('hidden', !t.searchOpen);
  if (!t.searchOpen) {
    const idle = sb.querySelector('.sb-input');
    if (idle && idle.value && document.activeElement !== idle) idle.value = '';
  }
  if (t.searchOpen) {
    const sc = sb.querySelector('.sb-scope'), kd = sb.querySelector('.sb-kind');
    if (document.activeElement !== sc) sc.value = t.query?.scope || 'folder';
    if (document.activeElement !== kd) kd.value = t.query?.ext || '';
  }
  const ctx = el.querySelector('.searchctx');
  ctx.classList.toggle('hidden', t.mode !== 'search');
  if (t.mode === 'search') {
    const m = t.searchMeta || {};
    const scope = t.query?.scope === 'global' ? '全盘' :
      (t.query?.scope === 'tag' ? '颜色标签' : '当前文件夹及子目录');
    if (t.loading) {
      ctx.innerHTML = `<span class="sc-txt">🔍 正在搜索「<span class="sc-kw">${esc(t.query?.query || t.query?.ext || '')}</span>」· ${esc(scope)} · 请稍候…</span>
        <span class="sc-exit" data-act="s-exit"><svg class="i" style="width:12px;height:12px"><use href="#ic-x"/></svg>退出搜索</span>`;
    } else {
      ctx.innerHTML = `<span class="sc-txt">🔍 <span class="sc-kw">“${esc(t.query?.query || '(不限名称)')}”</span>
        · ${esc(scope)} · 命中 <b>${esc(String(m.total || t.results.length))}</b> 项
        · ${esc(m.backend || '')} ${m.elapsed != null ? '· ' + esc(String(m.elapsed)) + 'ms' : ''}
        ${m.note ? '· ' + esc(m.note) : ''}</span>
        <span class="sc-btn" data-act="s-switch">${t.query?.scope === 'global' ? '限定到当前文件夹' : '改为全盘搜索'}</span>
        <span class="sc-exit" data-act="s-exit"><svg class="i" style="width:12px;height:12px"><use href="#ic-x"/></svg>退出搜索</span>`;
    }
  }
  const head = el.querySelector('.lhead');
  head.innerHTML = headHtml(t);
  const body = el.querySelector('.lbody');
  const keepScroll = t.scroll != null ? t.scroll : body.scrollTop;
  body.className = 'lbody' + (t.view === 'icons' ? ' icons' : t.view === 'list' ? ' listview' : '');
  const arr = sortedEntries(t);
  body._items = arr;
  if (!arr.length) {
    body.innerHTML = `<div class="empty"><svg class="i"><use href="#${t.mode === 'search' ? 'ic-search' : 'ic-folder'}"/></svg>
      <span>${t.loading ? '正在搜索…' : (t.mode === 'search' ? '没有匹配的项目' : '此文件夹为空')}</span></div>`;
  } else if (t.view === 'icons') {
    body.innerHTML = arr.map(e => tileHtml(e, t)).join('');
  } else {
    body.innerHTML = arr.map(e => rowHtml(e, t)).join('');
  }
  body.scrollTop = keepScroll;
}

// 轻量选中刷新：只改 class，绝不重建行 DOM（否则双击/右键的事件链会被打断）
export function refreshSelection(i) {
  const t = tab(i);
  const el = $(`#panes .pane[data-pi="${i}"]`);
  if (!t || !el) return;
  el.querySelectorAll('.lbody [data-path]').forEach(row => {
    row.classList.toggle('sel', t.sel.has(row.dataset.path));
    row.classList.toggle('cut', S._cut.has(normKey(row.dataset.path)));
  });
  renderStatus();
}

export function renderSidebar() {
  const box = $('#side-scroll');
  if (!box) return;
  const item = (name, path, icon, extra = '') =>
    `<div class="side-item" data-nav="${esc(path)}" title="${esc(path)}">
      <svg class="i"><use href="#${icon}"/></svg><span class="si-name">${esc(name)}</span>${extra}</div>`;
  const active = tab()?.path || '';
  let html = `<div class="side-h"><span class="sh-txt">快速访问</span></div>`;
  html += item('此电脑', '::{THISPC}', 'ic-grid');
  for (const s of S.specials) html += item(s.name, s.path, 'ic-folder');
  if (S.favorites.length) {
    html += `<div class="side-h"><span class="sh-txt">收藏夹</span></div>`;
    for (const f of S.favorites) html += item(basename(f), f, 'ic-star');
  }
  html += `<div class="side-h"><span class="sh-txt">磁盘</span></div>`;
  for (const d of S.drives) {
    const pct = d.total ? Math.round((d.total - d.free) / d.total * 100) : 0;
    const cls = pct >= 90 ? 'danger' : pct >= 75 ? 'warn' : '';
    html += `<div class="side-disk${normKey(active).startsWith(d.path.toLowerCase()) ? ' on' : ''}" data-nav="${esc(d.path)}" title="${esc(d.path)}">
      <div class="sd-top"><svg class="i"><use href="#ic-drive"/></svg>
        <span class="sd-name">${esc(d.name)}</span>
        <span class="sd-free">${fmtSize(d.free)} 可用</span></div>
      <span class="sd-bar"><i class="${cls}" style="width:${pct}%"></i></span></div>`;
  }
  html += `<div class="side-h"><span class="sh-txt">颜色标签</span></div>`;
  const counts = {};
  for (const c of Object.values(S.tags)) counts[c] = (counts[c] || 0) + 1;
  COLORS.forEach((c, i) => {
    html += `<div class="color-row" data-color="${c}">
      <i class="dot" style="background:${colorVar(c)}"></i>
      <span class="cn">${COLOR_NAMES[i]}</span>
      <span class="si-badge">${counts[c] || 0}</span></div>`;
  });
  box.innerHTML = html;
}

export function renderStatus(main) {
  const st = S.searchStatus || {};
  const eng = st.engine || {};
  const be = $('#st-backend');
  if (be) {
    if (!st.sdk && eng.warming) {
      be.textContent = '内置引擎启动中…';
      be.title = '首次启动要读取全盘 MFT 建立索引，通常 10–30 秒；期间搜索结果可能不完整，完成后即为秒搜';
    } else if (eng.needs_auth) {
      be.textContent = '本地索引 · 点此启用全盘秒搜';
      be.title = '内置搜索引擎尚未启用：安装一次 NTFS 索引服务即可全盘秒搜（一次管理员授权，之后永久有效）';
    } else if (st.backend) {
      be.textContent = `${st.backend}${st.version && st.sdk ? ' ' + st.version : ''}`;
      be.title = st.sdk
        ? (eng.source === 'bundled' ? '内置搜索引擎（随程序分发，无需单独安装 Everything）' : 'Everything SDK 已连接')
        : '点击重新连接搜索内核，或启用内置全盘引擎';
    } else {
      be.textContent = '搜索服务检测中…';
      be.title = '点击重新连接搜索内核';
    }
  }
  if (main != null) $('#st-main').textContent = main;
  const t = tab(), sel = t ? t.sel.size : 0;
  const cnt = t ? entriesOf(t).length : 0;
  $('#st-sel').textContent = `${cnt} 项${sel ? ' · 选中 ' + sel : ''}`;
}
