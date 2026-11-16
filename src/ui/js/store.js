// 单一状态源：所有窗格 / 标签 / 选择都在这里，渲染层只读不写业务状态
import { api } from './api.js';
import { $, normKey, basename, debounce } from './util.js';
import { SKINS, SKIN_KEYS, skinOf } from './skins.js';

export const S = {
  cfg: {},
  panes: [],            // 固定 5 个窗格对象，layout 决定可见数量
  activePane: 0,
  layout: 2,
  drives: [],
  specials: [],
  tags: {},
  tray: [],
  favorites: [],
  history: [],
  clip: {paths: [], move: false},
  searchStatus: {},
  pal: {open: false, results: [], sel: 0, runId: 0, scope: 'global', query: ''},
  preview: null,
  appInfo: {},
  _cut: new Set(),
};

let uid = 1;
export function makeTab(path = '') {
  return {
    id: 't' + (uid++), path, title: path ? basename(path) : '新标签页',
    mode: 'dir', items: [], results: [], query: null,
    sel: new Set(), anchor: '', view: 'details', sort: {key: 'name', dir: 1},
    history: path ? [path] : [], histIdx: path ? 0 : -1,
    searchOpen: false, searchMeta: {}, loading: false, scroll: 0,
  };
}
export function makePane(path = '') {
  const t = makeTab(path);
  return {tabs: [t], active: 0};
}
export function tab(i = S.activePane) {
  const p = S.panes[i];
  return p ? p.tabs[Math.min(p.active, p.tabs.length - 1)] : null;
}
export function pane(i = S.activePane) { return S.panes[i]; }
// 1 单栏 / 2 左右分屏 / 3 上下分屏 / 4 三栏 / 5 四宫格
export const VISIBLE = {1: 1, 2: 2, 3: 2, 4: 3, 5: 4};
export function visibleCount() { return Math.min(VISIBLE[S.layout] || 1, S.panes.length); }
export function entriesOf(t) { return t ? (t.mode === 'search' ? t.results : t.items) : []; }
export function findEntry(t, path) {
  if (!t || !path) return null;
  const k = normKey(path);
  return entriesOf(t).find(e => normKey(e.path) === k) || null;
}
export function selected(t) {
  return t ? entriesOf(t).filter(e => t.sel.has(e.path)) : [];
}
export function selectedPaths(t) { return selected(t).map(e => e.path); }
export function targetDir(t) { return t?.path || ''; }

// 界面皮肤：10 套主题（配色 + 壁纸）由 tools/gen_skins.py 生成。
// 每套皮肤自带深浅（浅字深底 / 深字浅底），选中即按它自己的底色渲染；
// 默认皮肤「晨雾蓝」才跟随「设置 → 明暗模式」。
export { SKINS, SKIN_KEYS, skinOf };

export function currentSkin() {
  return SKIN_KEYS.includes(S.cfg.skin) ? S.cfg.skin : 'default';
}
export function currentSkinOf() { return skinOf(currentSkin()); }

export function applySkin() {
  const s = currentSkinOf();
  const r = document.documentElement;
  r.dataset.skin = s.key;
  r.dataset.wallpaper = S.cfg.skin_wallpaper === false ? '0' : '1';
  // 工作面不透明度：100 = 该主题的默认厚度，0 = 面板全透、只剩壁纸与文字。
  // 壁纸那一层始终按原图显示，所以「看不到主题图」时调这里才有用。
  const op = Math.max(0, Math.min(100, Number(S.cfg.skin_surface ?? 100)));
  const k = op / 100;
  r.style.setProperty('--plate-k', k.toFixed(2));
  // 模糊跟着厚度走：面板越薄越要看清图，10px 糊在薄面板上等于把风景抹平
  r.style.setProperty('--glass-blur', (10 * k).toFixed(1));
  const b = $('#btn-theme');
  if (b) {
    b.innerHTML = '<svg class="i"><use href="#ic-palette"/></svg>';
    b.title = s.key === 'default' ? '界面皮肤：默认（晨雾蓝）'
      : `界面皮肤：${s.name} · ${s.cat}`;
  }
}

export function applyTheme() {
  const s = currentSkinOf();
  let real = s.scheme;                 // 皮肤自带深浅，优先于全局明暗
  if (!real) {
    const v = S.cfg.theme || 'light';
    real = v === 'system'
      ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : v;
  }
  document.documentElement.dataset.theme = real;
  applySkin();
}
export function applyDensity() { document.documentElement.dataset.density = S.cfg.density || 'comfortable'; }
// 列宽默认值：name=0 表示「自动填满剩余宽度」，改为正数即固定像素宽
export const DEFAULT_COLW = {name: 0, size: 96, mtime: 146, type: 108};
export const MIN_COLW = {name: 180, size: 56, mtime: 56, type: 56};
export const MAX_COLW = {name: 1600, size: 420, mtime: 420, type: 420};

export function applyColWidths() {
  const c = S.cfg.colw || {};
  const r = document.documentElement.style;
  for (const [k, v] of Object.entries(c)) r.setProperty('--cw-' + k, v + 'px');
  r.setProperty('--side-w', (S.cfg.sidebar_width || 214) + 'px');
  applyPaneRatio();
}
export function applyPaneRatio() {
  // 左右分屏下按百分比分配两栏，默认 50/50；其余布局不受影响
  const p = Math.min(75, Math.max(25, Number(S.cfg.pane_ratio) || 50));
  const r = document.documentElement.style;
  r.setProperty('--pane-a', (p / 50).toFixed(3) + 'fr');
  r.setProperty('--pane-b', ((100 - p) / 50).toFixed(3) + 'fr');
  r.setProperty('--pane-pct', (p / 100).toFixed(4));
}
export function setCols() {
  // 列头与数据行永远使用同一套 --cols，避免列错位压字
  const c = Object.assign({}, DEFAULT_COLW, S.cfg.colw || {});
  const root = document.documentElement;
  const nameOnly = !!S.cfg.name_only;
  root.dataset.nameOnly = nameOnly ? '1' : '';
  root.dataset.nameFixed = (!nameOnly && c.name > 0) ? '1' : '';
  root.dataset.nameWrap = S.cfg.name_wrap ? '1' : '';
  let first, size = c.size, mtime = c.mtime, type = c.type;
  if (nameOnly) {
    // 一键「仅显示名称列」：其余轨道收成 0，名称占满整栏
    first = 'minmax(0,1fr)'; size = mtime = type = 0;
  } else if (c.name > 0) {
    // 指定名称列宽时，其他列按剩余空间等比收缩：
    // 名称真的变宽、又永远不会把大小/时间/类型挤出可视区。
    const gap = 30, sum = c.size + c.mtime + c.type;
    const shrink = k => `minmax(0, max(0px, min(${c[k]}px, ` +
      `calc((100% - ${c.name + gap}px) * ${(c[k] / sum).toFixed(4)}))))`;
    first = `minmax(0, min(${c.name}px, calc(100% - ${gap}px)))`;
    size = shrink('size'); mtime = shrink('mtime'); type = shrink('type');
  } else {
    first = 'minmax(0,1fr)';
  }
  root.style.setProperty('--cols',
    `${first} ${typeof size === 'number' ? size + 'px' : size} ` +
    `${typeof mtime === 'number' ? mtime + 'px' : mtime} ` +
    `${typeof type === 'number' ? type + 'px' : type}`);
}

export function statePatch() {
  const session = {
    panes: S.panes.map(p => ({
      active: p.active,
      tabs: p.tabs.map(t => ({path: t.path, view: t.view, sort: t.sort,
        history: t.history.slice(-30), histIdx: t.histIdx,
        mode: t.mode === 'search' ? 'dir' : t.mode,
        query: t.query})),
    })),
    activePane: S.activePane, layout: S.layout,
  };
  return {session, favorites: S.favorites, tags: S.tags,
    tray: S.tray, history: S.history, layout: S.layout,
    theme: S.cfg.theme, density: S.cfg.density, colw: S.cfg.colw, skin: currentSkin(),
    skin_wallpaper: S.cfg.skin_wallpaper !== false,
    skin_surface: Math.max(0, Math.min(100, Number(S.cfg.skin_surface ?? 100))),
    pane_ratio: S.cfg.pane_ratio, name_only: S.cfg.name_only,
    name_wrap: S.cfg.name_wrap, sidebar_width: S.cfg.sidebar_width};
}

export const saveState = debounce(() => {
  api('state.set', {patch: statePatch()}).catch(() => {});
}, 500);

export async function loadState() {
  const cfg = await api('state.get');
  S.cfg = cfg;
  S.layout = cfg.layout || 2;
  S.activePane = 0;
  S.favorites = cfg.favorites || [];
  S.tags = cfg.tags || {};
  S.tray = cfg.tray || [];
  S.history = cfg.history || [];
  applyTheme(); applyDensity(); applyColWidths(); setCols();
  const sess = cfg.session;
  if (sess?.panes?.length) {
    S.layout = Math.min(Math.max(sess.layout || 2, 1), 5);
    S.activePane = Math.min(sess.activePane || 0, 4);
    S.panes = sess.panes.slice(0, 5).map(p => {
      const tabs = (p.tabs || []).map(x => {
        const t = makeTab(x.path || '');
        t.view = x.view || 'details'; t.sort = x.sort || t.sort;
        t.history = x.history || t.history; t.histIdx = x.histIdx ?? t.histIdx;
        t.query = x.query || null; t.title = basename(t.path) || t.title;
        return t;
      });
      return {tabs: tabs.length ? tabs : [makeTab()], active: Math.min(p.active || 0, tabs.length - 1)};
    });
  }
  while (S.panes.length < 5) S.panes.push(makePane());
  return cfg;
}
