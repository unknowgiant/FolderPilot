// 右键菜单与弹窗。菜单项全部以 path 为参数，不依赖「当前目录 + 名称」反查
import { api, APP_META } from './api.js';
import { S, tab, selectedPaths, saveState, applyTheme, applySkin, applyDensity,
  applyColWidths, applyPaneRatio, setCols, DEFAULT_COLW,
  SKINS, currentSkin } from './store.js';
import { renderPane, renderPanes, renderSidebar, renderStatus } from './view.js';
import * as A from './actions.js';
import { $, $$, esc, fmtSize, fmtDate, basename, dirname, toast, COLORS, COLOR_NAMES,
  colorVar, iconSvg } from './util.js';

let ctx = null;
export function closeCtx() { if (ctx) { ctx.remove(); ctx = null; } }

function showCtx(x, y, items) {
  closeCtx();
  const el = document.createElement('div');
  el.className = 'ctx';
  el.innerHTML = items.map(it => {
    if (it === '-') return '<div class="ctx-sep"></div>';
    if (it.type === 'colors') return `<div class="ctx-colors">${COLORS.map(c =>
      `<i style="background:${colorVar(c)}" data-color="${c}" title="${COLOR_NAMES[COLORS.indexOf(c)]}"></i>`).join('')}</div>`;
    return `<div class="ctx-item${it.danger ? ' danger' : ''}${it.disabled ? ' disabled' : ''}" data-k="${esc(it.key || '')}">
      <svg class="i"><use href="#${it.icon || 'ic-file'}"/></svg>
      <span class="cl">${esc(it.label)}</span>${it.hint ? `<span class="ck">${esc(it.hint)}</span>` : ''}</div>`;
  }).join('');
  document.body.appendChild(el);
  const w = el.offsetWidth, h = el.offsetHeight;
  el.style.left = Math.min(x, innerWidth - w - 8) + 'px';
  el.style.top = Math.min(y, innerHeight - h - 8) + 'px';
  ctx = el;
  el.addEventListener('click', e => {
    const col = e.target.closest('[data-color]');
    if (col) { el._onColor?.(col.dataset.color); closeCtx(); return; }
    const row = e.target.closest('.ctx-item');
    if (!row || row.classList.contains('disabled')) return;
    const fn = el._handlers?.[row.dataset.k];
    closeCtx();
    if (fn) fn();
  });
  return el;
}
document.addEventListener('mousedown', e => { if (ctx && !ctx.contains(e.target)) closeCtx(); }, true);
document.addEventListener('blur', closeCtx);

export function itemMenu(x, y, path, entry, i = S.activePane) {
  const e = entry || {path, name: basename(path), is_dir: false, ext: ''};
  const many = () => {
    const t = tab(i), sel = selectedPaths(t);
    return sel.includes(path) && sel.length > 1 ? sel : [path];
  };
  const items = [
    {key:'open', label:'打开', icon: e.is_dir ? 'ic-folder' : 'ic-file', hint:'Enter'},
    e.is_dir ? {key:'newtab', label:'在新标签页打开', icon:'ic-plus', hint:'Ctrl+T'} : null,
    {key:'locate', label:'跳转到所在目录', icon:'ic-folder', hint:'Ctrl+Enter'},
    {key:'reveal', label:'在资源管理器中显示', icon:'ic-eye'},
    {key:'preview', label:'预览', icon:'ic-eye', hint:'Space'},
    '-',
    {key:'copy', label:'复制', icon:'ic-copy', hint:'Ctrl+C'},
    {key:'cut', label:'剪切', icon:'ic-copy', hint:'Ctrl+X'},
    {key:'paste', label:'粘贴到当前文件夹', icon:'ic-copy', hint:'Ctrl+V'},
    {key:'tray', label:'加入暂存盘', icon:'ic-tray'},
    {key:'copypath', label:'复制完整路径', icon:'ic-copy'},
    '-',
    {key:'taghead', label:'标记颜色：', icon:'ic-tag', disabled:true},
    {type:'colors'},
    '-',
    {key:'rename', label:'重命名', icon:'ic-doc', hint:'F2'},
    {key:'trash', label:'移入回收站', icon:'ic-x', hint:'Del', danger:true},
    (e.ext === 'zip') ? {key:'unzip', label:'解压到当前文件夹', icon:'ic-zip'} :
      {key:'zip', label:'压缩为 ZIP', icon:'ic-zip'},
    /\.(exe|msi|bat|cmd)$/i.test(e.path) ? {key:'runas', label:'以管理员身份运行', icon:'ic-exe'} : null,
    {key:'terminal', label:'在此打开终端', icon:'ic-terminal'},
    {key:'access', label:'检查外部程序可访问性', icon:'ic-info'},
    {key:'props', label:'属性', icon:'ic-info'},
  ].filter(Boolean);
  const el = showCtx(x, y, items);
  const H = {
    open: () => A.activate(path, i),
    newtab: () => A.openInNewTab(path, i),
    locate: () => A.revealEntry(path, i),
    reveal: () => api('entry.reveal', {path}).catch(ex => toast(ex.message, true)),
    preview: () => A.preview(path),
    copy: () => A.copySel(i, false).then(() => many()),
    cut: () => A.copySel(i, true),
    paste: () => A.paste(i),
    tray: () => A.trayAdd(many()),
    copypath: () => A.copyText(path),
    rename: () => renameModal(path, i),
    trash: () => A.trashPaths(many(), i),
    zip: () => A.zipSel(i),
    unzip: () => A.unzipHere(path, i),
    runas: () => api('entry.runas', {path}).catch(ex => toast(ex.message, true)),
    terminal: () => api('entry.terminal', {path: dirname(path), kind:'auto'}).catch(ex => toast(ex.message, true)),
    access: () => accessModal(many()),
    props: () => propsModal(path),
  };
  // 多选复制/剪切时先把目标行纳入选择
  const t = tab(i);
  if (t && !t.sel.has(path)) A.setSelection(i, path, 'single');
  H.copy = () => { if (!tab(i)?.sel.has(path)) A.setSelection(i, path, 'single'); return A.copySel(i, false); };
  H.cut = () => { if (!tab(i)?.sel.has(path)) A.setSelection(i, path, 'single'); return A.copySel(i, true); };
  el._handlers = H;
  el._onColor = c => A.setTag(many(), c, i);
}

export function emptyMenu(x, y, i = S.activePane) {
  const t = tab(i), path = t?.path || '';
  const items = [
    {key:'mkdir', label:'新建文件夹', icon:'ic-folder', hint:'Ctrl+Shift+N'},
    {key:'newtext', label:'新建文本文档', icon:'ic-doc'},
    {key:'paste', label:'粘贴', icon:'ic-copy', hint:'Ctrl+V'},
    '-',
    {key:'refresh', label:'刷新', icon:'ic-refresh', hint:'F5'},
    {key:'terminal', label:'在此打开终端', icon:'ic-terminal'},
    {key:'pin', label:'固定当前目录', icon:'ic-star'},
    '-',
    {key:'details', label:'详细信息视图', icon:'ic-list'},
    {key:'list', label:'紧凑列表视图', icon:'ic-list'},
    {key:'icons', label:'图标视图', icon:'ic-grid'},
    '-',
    {key:'search', label:'在当前文件夹内搜索', icon:'ic-search'},
    {key:'props', label:'当前文件夹属性', icon:'ic-info'},
  ];
  const el = showCtx(x, y, items);
  el._handlers = {
    mkdir: () => A.makeFolder(i), newtext: () => A.makeText(i), paste: () => A.paste(i),
    refresh: () => A.refresh(i), terminal: () => A.openTerminal(i),
    pin: () => A.addFavorite(path), details: () => A.setView('details', i),
    list: () => A.setView('list', i), icons: () => A.setView('icons', i),
    search: () => (import('./search.js')).then(m => m.togglePaneSearch(i)),
    props: () => propsModal(path),
  };
}

export function moreMenu(x, y, i = S.activePane) {
  const t = tab(i);
  const el = showCtx(x, y, [
    {key:'newtab', label:'新建标签页', icon:'ic-plus', hint:'Ctrl+T'},
    {key:'search', label:'当前文件夹内搜索', icon:'ic-search'},
    {key:'terminal', label:'在此打开终端', icon:'ic-terminal'},
    {key:'pin', label:'固定当前目录', icon:'ic-star'},
    {key:'colwidth', label:'列宽与窗格宽度…', icon:'ic-columns'},
    {key:'nameonly', label: S.cfg.name_only ? '恢复显示其他列' : '仅显示名称列', icon:'ic-list',
      hint: S.cfg.name_only ? '当前已开启' : '名称占满整栏'},
    '-',
    {key:'v1', label:'单栏布局', icon:'ic-grid', hint:'Ctrl+1'},
    {key:'v2', label:'左右分屏', icon:'ic-grid', hint:'Ctrl+2'},
    {key:'v3', label:'上下分屏', icon:'ic-grid', hint:'Ctrl+3'},
    {key:'v4', label:'三栏', icon:'ic-grid', hint:'Ctrl+4'},
    {key:'v5', label:'四宫格', icon:'ic-grid', hint:'Ctrl+5'},
  ]);
  el._handlers = {
    newtab: () => A.newTab(i),
    search: () => import('./search.js').then(m => m.togglePaneSearch(i)),
    terminal: () => A.openTerminal(i), pin: () => A.addFavorite(t?.path),
    colwidth: () => columnWidthModal(),
    nameonly: () => {
      A.setNameOnly(!S.cfg.name_only);
      toast(S.cfg.name_only ? '已仅显示名称列' : '已恢复显示所有列');
    },
    v1: () => A.setLayout(1), v2: () => A.setLayout(2), v3: () => A.setLayout(3),
    v4: () => A.setLayout(4), v5: () => A.setLayout(5),
  };
}

// ---------- 弹窗 ----------
export function modal(title, body, foot = '', onMount = null) {
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  mask.innerHTML = `<div class="modal">
    <div class="modal-head"><span class="mt">${esc(title)}</span>
      <button class="navbtn" data-close><svg class="i"><use href="#ic-x"/></svg></button></div>
    <div class="modal-body">${body}</div>
    ${foot ? `<div class="modal-foot">${foot}</div>` : ''}</div>`;
  $('#modal-root').appendChild(mask);
  const close = () => mask.remove();
  mask.querySelector('[data-close]').onclick = close;
  mask.addEventListener('mousedown', e => { if (e.target === mask) close(); });
  if (onMount) onMount(mask, close);
  return {mask, close};
}
export function closeAllModals() { $$('#modal-root .modal-mask').forEach(x => x.remove()); }

export function renameModal(path, i = S.activePane) {
  modal('重命名', `<div class="form-row"><label>新名称</label>
      <input type="text" id="rn-input" value="${esc(basename(path))}" spellcheck="false"></div>
    <div class="hint">名称不能包含 \\ / : * ? " &lt; &gt; | 等字符。</div>`,
    `<button class="btn" data-close2>取消</button><button class="btn primary" data-ok>确定</button>`,
    (m, close) => {
      const inp = m.querySelector('#rn-input');
      inp.focus(); inp.select();
      const ok = async () => { close(); await A.doRename(path, inp.value.trim(), i); };
      m.querySelector('[data-ok]').onclick = ok;
      m.querySelector('[data-close2]').onclick = close;
      inp.onkeydown = e => {
        if (e.key === 'Enter') { e.preventDefault(); ok(); }
        if (e.key === 'Escape') { e.preventDefault(); close(); }
      };
    });
}

export async function propsModal(path) {
  let r;
  try { r = await api('entry.props', {path}); } catch (ex) { return toast(ex.message, true); }
  modal('属性', `<div class="kv">
    <span class="k">名称</span><span class="ell">${esc(r.name)}</span>
    <span class="k">类型</span><span class="ell">${esc(r.kind)}</span>
    <span class="k">位置</span><span class="ell" title="${esc(r.parent)}">${esc(r.parent)}</span>
    <span class="k">大小</span><span class="ell">${fmtSize(r.size)}${r.is_dir ? ` · ${r.file_count} 个文件` : ''}</span>
    <span class="k">创建时间</span><span class="ell">${esc(r.ctime)}</span>
    <span class="k">修改时间</span><span class="ell">${esc(r.mtime)}</span>
    <span class="k">访问时间</span><span class="ell">${esc(r.atime)}</span>
    <span class="k">属性</span><span class="ell">${esc((r.attributes || []).join('、') || '无')}</span>
    <span class="k">完整路径</span><span class="ell" title="${esc(r.path)}" style="user-select:text">${esc(r.path)}</span>
  </div>`, `<button class="btn" data-cp>复制路径</button><button class="btn primary" data-ok>关闭</button>`,
  (m, close) => {
    m.querySelector('[data-ok]').onclick = close;
    m.querySelector('[data-cp]').onclick = () => { A.copyText(r.path); close(); };
  });
}

// ---------- 外部程序可访问性诊断 ----------
export async function accessModal(paths) {
  if (!paths?.length) return;
  let items = [];
  try { items = (await api('clip.check', {paths})).items || []; }
  catch (ex) { return toast('诊断失败：' + ex.message, true); }
  const rows = items.map(x => `
    <div class="acc-item">
      <div class="acc-name" title="${esc(x.path)}">${esc(basename(x.path))}</div>
      <div class="acc-kv">路径 ${x.length} 字符 ·
        ${x.readable ? '<b style="color:var(--ok,#2e9e6b)">✓ 任意进程可读</b>'
                     : '<b style="color:var(--danger)">✗ 不可读：' + esc(x.error || '未知') + '</b>'}
        ${x.unsafe_attrs?.length ? ' · 特殊属性 ' + esc(x.unsafe_attrs.join('/')) : ''}
      </div>
      <div class="acc-path">${esc(x.path)}</div>
    </div>`).join('');
  const {mask, close: closeAccess} = modal('外部程序可访问性诊断', `
    <div class="hint" style="margin-bottom:12px">用于排查「复制到云盘 / 微信 / WPS 等外部程序提示无权限」。
      下面检查的是文件本身能否被任何进程以只读方式打开，以及是否带云盘占位、重解析点等特殊属性。</div>
    ${rows}
    <div class="hint" style="margin-top:14px"><b>若这里显示「可读」但云盘仍报无权限</b>，说明问题在云盘客户端或云端目录，
      与本机文件无关。<b>快速定性</b>：在云盘客户端的同一个目标文件夹里，用客户端自带的「上传」按钮
      传同一个文件——同样报错就是云端权限/容量限制，任何本地工具（包括资源管理器）都无法绕过。<br>
      <b>移动云盘群组空间</b>（报「当前无权访问该文件夹，请检查文件权限后重试」时最常见）：
      群组成员分 7 种角色（管理员 / 编辑 / 上传+下载 / 预览+上传 / 上传 / 下载 / 预览），
      其中「下载」「预览」角色<b>没有上传权限</b>；群组盘容量已满也会报错。处理顺序：<br>
      ① 换到有写入权限的目录（自己的「文件」个人空间，或群组中有上传权的文件夹）；<br>
      ② 请群管理员把你的角色调到「编辑」或「上传」及以上；<br>
      ③ 个人文件可放入云盘同步目录（如 D:\移动云盘同步盘），由同步客户端自动上传；<br>
      ④ 改用网页版 yun.139.com 上传；⑤ 重启云盘客户端后重试。</div>`,
    `<button class="btn primary" data-close>知道了</button>`);
  const okBtn = mask.querySelector('.modal-foot [data-close]');
  if (okBtn) okBtn.onclick = closeAccess;
}

// 十六进制转带透明度的底色，给缩略图里那层「玻璃顶栏」用
function tint(hex, a) {
  const h = String(hex || '#ffffff').replace('#', '');
  const n = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
  const r = parseInt(n.slice(0, 2), 16), g = parseInt(n.slice(2, 4), 16), b = parseInt(n.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

export function skinModal() {
  const card = s => {
    const chrome = s.scheme === 'dark' ? tint(s.sur, .82) : tint(s.sur, .92);
    const bg = s.wall ? `background-image:url('${s.wall}')` : `background-image:${s.prev}`;
    return `<div class="skin-card" data-skin="${s.key}" title="${esc(s.name + ' · ' + s.cat)}">
      <span class="sk-prev" style="${bg};background-color:${s.scheme === 'dark' ? '#1b2230' : '#f2f5fb'}">
        <i class="sk-top" style="background:${chrome}"></i>
        <i class="sk-side" style="background:${chrome}"></i>
        <i class="sk-ln" style="top:17px;background:${chrome}"></i>
        <i class="sk-ln" style="top:26px;background:${chrome}"></i>
        <i class="sk-ln" style="top:35px;width:46%;background:${chrome}"></i>
        <i class="sk-dot" style="background:${s.acc}"></i>
      </span>
      <span class="sk-meta"><span class="sk-name">${esc(s.name)}</span>
        <span class="sk-tag">${esc(s.cat)}</span></span>
      <span class="sk-check"><svg class="i" style="width:10px;height:10px"><use href="#ic-check"/></svg></span>
    </div>`;
  };
  modal('界面皮肤', `
    <div class="sk-row">
      <span class="sk-label">明暗</span>
      <div class="seg" id="sk-seg">
        <button data-th="light">浅色</button><button data-th="dark">深色</button>
        <button data-th="system">跟随系统</button>
      </div>
      <label class="sk-switch"><input type="checkbox" id="sk-wall">显示壁纸</label>
      <label class="sk-range" id="sk-op-wrap">壁纸不透明度
        <input type="range" id="sk-op" min="0" max="100" step="5" value="100"
          title="100% 原样显示，0% 只剩配色">
        <span class="sk-op-v" id="sk-op-v">100%</span></label>
      <span class="sk-note" id="sk-note"></span>
    </div>
    <div class="skin-grid">${SKINS.map(card).join('')}</div>
    <div class="skin-tip">共 ${SKINS.length - 1} 套主题，点一下即时生效，可以来回对比；窗口关闭后自动记住。
      每套主题自带深浅（深字浅底或浅字深底），选中后按它自己的底色渲染，文字对比度已按 WCAG AA 核对。</div>`,
    `<button class="btn" data-reset>恢复默认</button><button class="btn primary" data-done>完成</button>`,
    (m, close) => {
      m.querySelector('.modal').classList.add('wide');
      const sync = () => {
        m.querySelectorAll('.skin-card').forEach(c =>
          c.classList.toggle('on', c.dataset.skin === currentSkin()));
        const own = currentSkin() !== 'default';
        m.querySelectorAll('#sk-seg button').forEach(b =>
          b.classList.toggle('on', !own && b.dataset.th === (S.cfg.theme || 'light')));
        m.querySelector('#sk-note').textContent = own
          ? '当前主题自带底色，切换明暗会回到默认皮肤' : '仅默认皮肤跟随明暗';
        const w = m.querySelector('#sk-wall');
        w.checked = S.cfg.skin_wallpaper !== false;
        w.disabled = currentSkin() === 'default';
        w.closest('.sk-switch').style.opacity = w.disabled ? .45 : 1;
        // 不透明度滑杆：默认皮肤没有壁纸，关掉壁纸时也无意义
        const op = Math.max(0, Math.min(100, Number(S.cfg.skin_opacity ?? 100)));
        const rng = m.querySelector('#sk-op');
        rng.value = op;
        m.querySelector('#sk-op-v').textContent = op + '%';
        const off = w.disabled || !w.checked;
        rng.disabled = off;
        const wrap = m.querySelector('#sk-op-wrap');
        wrap.style.opacity = off ? .45 : 1;
        wrap.title = off ? '先打开「显示壁纸」' : '';
      };
      m.querySelectorAll('.skin-card').forEach(c => {
        c.onclick = () => {
          S.cfg.skin = c.dataset.skin;
          applyTheme(); saveState(); sync();
        };
      });
      m.querySelectorAll('#sk-seg button').forEach(b => {
        b.onclick = () => {
          const back = currentSkin() !== 'default';
          S.cfg.skin = 'default';
          S.cfg.theme = b.dataset.th;
          applyTheme(); saveState(); sync();
          if (back) toast('已切回默认皮肤（' + b.textContent + '）');
        };
      });
      m.querySelector('#sk-wall').onchange = e => {
        S.cfg.skin_wallpaper = e.target.checked;
        applySkin(); saveState(); sync();
      };
      // 拖动即时预览：只改壁纸那一层的 opacity，不重新算色、不重排
      m.querySelector('#sk-op').oninput = e => {
        S.cfg.skin_opacity = Number(e.target.value);
        m.querySelector('#sk-op-v').textContent = e.target.value + '%';
        applySkin(); saveState();
      };
      m.querySelector('[data-reset]').onclick = () => {
        S.cfg.skin = 'default'; S.cfg.theme = 'light'; S.cfg.skin_wallpaper = true;
        S.cfg.skin_opacity = 100;
        applyTheme(); saveState(); sync(); toast('已恢复默认外观');
      };
      m.querySelector('[data-done]').onclick = close;
      sync();
    });
}

export function settingsModal() {
  const c = S.cfg;
  modal('设置', `
    <div class="form-row"><label>明暗模式</label><select id="set-theme">
      <option value="light">浅色</option><option value="dark">深色</option><option value="system">跟随系统</option></select></div>
    <div class="form-row"><label>界面皮肤</label><span class="fv">${esc((SKINS.find(x => x.key === currentSkin()) || SKINS[0]).name)}
      <button class="btn" id="set-skin" style="margin-left:8px">选择皮肤…</button></span></div>
    <div class="form-row"><label>行高</label><select id="set-density">
      <option value="comfortable">舒适</option><option value="compact">紧凑</option></select></div>
    <div class="form-row"><label>搜索上限</label><input type="number" id="set-max" min="50" max="3000" value="${esc(c.ev_max || 500)}"></div>
    <div class="form-row"><label>显示隐藏文件</label><input type="checkbox" id="set-hidden" ${c.show_hidden ? 'checked' : ''}></div>
    <div class="form-row"><label>删除前确认</label><input type="checkbox" id="set-confirm" ${c.confirm_delete !== false ? 'checked' : ''}></div>
    <div class="form-row"><label>列宽 / 窗格</label><span class="fv">
      <button class="btn" id="set-colwidth">调整列宽与窗格宽度…</button></span></div>
    <div class="form-row"><label>搜索服务</label><span class="fv">${esc(S.searchStatus.backend || '检测中')}
      <button class="btn" id="set-engine" style="margin-left:8px">内置引擎…</button>
      <button class="btn" id="set-reconnect" style="margin-left:8px">重新连接</button></span></div>
    <div class="hint" style="margin-top:14px">数据仅保存在本机 ${esc(S.appInfo.data_dir || APP_META.dataDir)}，
      不联网、不上传。导出：标签 / 收藏 / 暂存 / 搜索历史（CSV，带 BOM）。</div>
    <div class="tray-actions"><button class="btn" data-exp="tags">导出标签</button>
      <button class="btn" data-exp="favorites">导出收藏</button><button class="btn" data-exp="tray">导出暂存盘</button>
      <button class="btn" data-exp="history">导出搜索历史</button></div>`,
    `<button class="btn" data-close2>取消</button><button class="btn primary" data-ok>保存</button>`,
    (m, close) => {
      m.querySelector('#set-theme').value = c.theme || 'light';
      m.querySelector('#set-skin').onclick = () => { close(); skinModal(); };
      m.querySelector('#set-density').value = c.density || 'comfortable';
      m.querySelectorAll('[data-exp]').forEach(b => b.onclick = async () => {
        try { const r = await api('data.export', {name: b.dataset.exp}); toast('已导出：' + r.path); }
        catch (ex) { toast(ex.message, true); }
      });
      m.querySelector('#set-reconnect').onclick = async () => {
        try { const r = await api('search.connect'); S.searchStatus = r; toast('已连接：' + r.backend); }
        catch (ex) { toast(ex.message, true); }
      };
      m.querySelector('#set-engine').onclick = () => { close(); engineModal(); };
      m.querySelector('#set-colwidth').onclick = () => { close(); columnWidthModal(); };
      m.querySelector('[data-close2]').onclick = close;
      m.querySelector('[data-ok]').onclick = () => {
        c.theme = m.querySelector('#set-theme').value;
        c.density = m.querySelector('#set-density').value;
        c.ev_max = Number(m.querySelector('#set-max').value) || 500;
        c.show_hidden = m.querySelector('#set-hidden').checked;
        c.confirm_delete = m.querySelector('#set-confirm').checked;
        applyTheme(); applyDensity(); saveState(); A.refresh(); close(); toast('设置已保存');
      };
    });
}

// ---------- 内置搜索引擎 ----------
const SVC_TEXT = {running: '运行中', stopped: '已停止', absent: '未安装', unknown: '查询不到'};

export function engineModal() {
  const st = S.searchStatus || {};
  const e = st.engine || {};
  const src = e.external ? '系统已安装的 Everything（直接复用，不改它的配置）'
    : (e.deployed ? '随程序内置的 Everything 内核' : '尚未释放（安装包可能不完整）');
  const body = `
    <div class="form-row"><label>当前后端</label><span class="fv">${esc(st.backend || '检测中')}</span></div>
    <div class="form-row"><label>内核来源</label><span class="fv">${src}</span></div>
    <div class="form-row"><label>内核位置</label><span class="fv" style="word-break:break-all">${esc(e.dir || '—')}</span></div>
    <div class="form-row"><label>NTFS 索引服务</label><span class="fv">${esc(SVC_TEXT[e.service] || '—')}
      ${e.needs_auth ? '<b style="color:#C0612A">· 需要一次管理员授权</b>' : ''}</span></div>
    <div class="form-row"><label>内核版本</label><span class="fv">${esc(e.version || st.version || '—')}</span></div>
    <div class="hint" style="margin-top:10px">
      内置引擎就是 Everything 的内核（MIT 许可，随程序分发），<b>不需要单独安装 Everything</b>。<br>
      全盘秒搜依赖 NTFS 的 MFT / USN 日志，读取它必须是管理员权限；Everything 的标准做法是装一个
      约 1MB 的常驻索引服务。点「启用全盘秒搜」会弹一次 UAC，装好后永久静默、随系统启动，
      管理器退出时内核也随之退出。
      ${e.last_error ? '<br><b>最近一次提示：</b>' + esc(e.last_error) : ''}
    </div>`;
  const foot = `<button class="btn" data-stop>停止内核</button>
    <button class="btn" data-close2>关闭</button>
    <button class="btn primary" data-enable>启用全盘秒搜</button>`;
  modal('内置搜索引擎', body, foot, (m, close) => {
    const btn = m.querySelector('[data-enable]');
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = '等待授权…';
      toast('如弹出管理员授权，请选择「是」');
      try {
        const r = await api('engine.enable', {interactive: true});
        S.searchStatus = r;
        renderStatus();
        toast(r.sdk ? '已启用：' + r.backend : (r.engine?.last_error || '未能启用，可稍后重试'), !r.sdk);
      } catch (ex) { toast(ex.message, true); }
      close(); engineModal();
    };
    m.querySelector('[data-stop]').onclick = async () => {
      try { S.searchStatus = await api('engine.stop'); toast('已停止内置内核'); }
      catch (ex) { toast(ex.message, true); }
      close(); engineModal();
    };
    m.querySelector('[data-close2]').onclick = close;
  });
}

// ---------- 列宽与窗格宽度设置 ----------
export function columnWidthModal() {
  const c = S.cfg;
  const backup = {colw: {...(c.colw || {})}, pane_ratio: c.pane_ratio,
    name_only: c.name_only, name_wrap: c.name_wrap};
  const w = Object.assign({}, DEFAULT_COLW, c.colw || {});
  const auto = !(w.name > 0);
  const ratio = Math.min(75, Math.max(25, Number(c.pane_ratio) || 50));
  const row = (key, label, min, max, val, unit = 'px') =>
    `<div class="cw-row"><label>${label}</label>
      <input type="range" id="cw-r-${key}" min="${min}" max="${max}" step="5" value="${val}">
      <input type="number" id="cw-n-${key}" min="${min}" max="${max}" value="${val}">
      <span class="unit">${unit}</span></div>`;

  modal('列宽与窗格宽度', `
    <div class="hint">调宽「名称」列即可完整显示长文件名。也可直接拖动列头右侧的分隔线、
      或拖动左右窗格中间的分隔条；双击名称列分隔线恢复自动宽度。</div>
    <div class="cw-sec">名称列</div>
    <div class="cw-row"><label>宽度模式</label><label class="cw-auto">
      <input type="checkbox" id="cw-auto" ${auto ? 'checked' : ''}>自动填满剩余宽度（跟随窗格变化）</label></div>
    <div class="cw-row"><label>专注名称</label><label class="cw-auto">
      <input type="checkbox" id="cw-nameonly" ${c.name_only ? 'checked' : ''}>仅显示名称列（隐藏大小 / 时间 / 类型，长文件名占满整栏）</label></div>
    <div class="cw-row"><label>长名称换行</label><label class="cw-auto">
      <input type="checkbox" id="cw-wrap" ${c.name_wrap ? 'checked' : ''}>文件名两行显示（行高自动加高，长中文名不再被截断）</label></div>
    ${row('name', '固定宽度', 180, 1200, w.name > 0 ? w.name : 420)}
    <div class="cw-sec">其他列</div>
    ${row('size', '大小', 56, 420, w.size)}
    ${row('mtime', '修改时间', 56, 420, w.mtime)}
    ${row('type', '类型 / 位于', 56, 420, w.type)}
    <div class="cw-sec">左右分屏的窗格宽度</div>
    ${row('pane', '左窗格占比', 25, 75, ratio, '%')}
    <div class="hint" style="margin-top:6px">所有改动即时预览并自动记忆，点「应用」确认；「取消」可还原。</div>`,
    `<button class="btn" data-cw-reset>恢复默认</button>
     <button class="btn" data-close2>取消</button>
     <button class="btn primary" data-ok>应用</button>`,
    (m, close) => {
      const keys = ['name', 'size', 'mtime', 'type', 'pane'];
      const num = k => m.querySelector('#cw-n-' + k);
      const rng = k => m.querySelector('#cw-r-' + k);
      const live = () => {
        const isAuto = m.querySelector('#cw-auto').checked;
        const only = m.querySelector('#cw-nameonly').checked;
        // 专注名称模式下其余控件禁用，避免给出无效数值
        m.querySelector('#cw-auto').disabled = only;
        num('name').disabled = rng('name').disabled = isAuto || only;
        ['size', 'mtime', 'type', 'pane'].forEach(k => {
          num(k).disabled = rng(k).disabled = only;
        });
        c.name_only = only;
        c.name_wrap = m.querySelector('#cw-wrap').checked;
        c.colw = {
          name: isAuto ? 0 : (+num('name').value || 420),
          size: +num('size').value, mtime: +num('mtime').value, type: +num('type').value,
        };
        c.pane_ratio = +num('pane').value;
        setCols(); applyPaneRatio();
      };
      const restore = () => {
        c.colw = backup.colw; c.pane_ratio = backup.pane_ratio;
        c.name_only = backup.name_only;
        c.name_wrap = backup.name_wrap;
        setCols(); applyPaneRatio();
      };
      keys.forEach(k => {
        rng(k).oninput = () => { num(k).value = rng(k).value; live(); };
        num(k).oninput = () => { rng(k).value = num(k).value; live(); };
      });
      m.querySelector('#cw-auto').onchange = live;
      m.querySelector('#cw-nameonly').onchange = live;
      m.querySelector('#cw-wrap').onchange = live;
      m.querySelector('[data-close]').onclick = () => { restore(); close(); };
      m.addEventListener('mousedown', e => { if (e.target === m) restore(); });
      m.querySelector('[data-cw-reset]').onclick = () => {
        m.querySelector('#cw-auto').checked = true;
        m.querySelector('#cw-nameonly').checked = false;
        m.querySelector('#cw-wrap').checked = false;
        num('name').value = rng('name').value = 420;
        num('size').value = rng('size').value = DEFAULT_COLW.size;
        num('mtime').value = rng('mtime').value = DEFAULT_COLW.mtime;
        num('type').value = rng('type').value = DEFAULT_COLW.type;
        num('pane').value = rng('pane').value = 50;
        live();
      };
      m.querySelector('[data-close2]').onclick = () => { restore(); close(); };
      m.querySelector('[data-ok]').onclick = () => {
        live(); saveState(); close(); toast('列宽已保存');
      };
      live();
    });
}

export function aboutModal() {
  // 名称与版本统一取注入值，避免每次发版都要改文案
  const title = S.appInfo.name || APP_META.title;
  const ver = S.appInfo.version || APP_META.version || '—';
  modal('关于 · ' + title, `
    <div class="about-logo"><div class="lg">◆</div><div>
      <div style="font-size:16px;font-weight:650">${esc(title)}</div>
      <div class="hint">项目编号：${esc(title)} · Windows 64 位</div></div></div>
    <div class="hint">
      本版本从底层架构重写：所有列表条目（目录、全盘搜索、文件夹内搜索、暂存盘）
      统一为「绝对路径 + 元数据」模型，双击 / 右键 / Enter / 预览共用同一套处理器，
      因此搜索结果不会再出现「打不开」；列头与数据行共用同一套网格列定义，
      长中文名称自动省略并显示相对路径副标题，不再压字。
    </div>
    <div class="kv" style="margin-top:16px">
      <span class="k">应用版本</span><span>${esc(ver)}</span>
      <span class="k">运行内核</span><span>Python ${esc((S.appInfo.python || '3.x'))} + WebView2</span>
      <span class="k">搜索后端</span><span>${esc(S.searchStatus.backend || '检测中')}</span>
      <span class="k">数据目录</span><span class="ell" style="user-select:text">${esc(S.appInfo.data_dir || '')}</span>
    </div>
    <div class="hint" style="margin-top:14px"><b>快捷键</b><br>
      <span class="kbd">Ctrl+F</span> / <span class="kbd">Alt+Space</span> 全盘搜索 ·
      <span class="kbd">Ctrl+1~5</span> 布局 · <span class="kbd">Ctrl+T/W</span> 标签 ·
      <span class="kbd">Space</span> 预览 · <span class="kbd">F2</span> 重命名 ·
      <span class="kbd">Del</span> 回收站 · <span class="kbd">Ctrl+C/X/V</span> 复制剪切粘贴 ·
      <span class="kbd">Ctrl+Enter</span> 跳转所在目录 · <span class="kbd">Alt+←/→</span> 前进后退
    </div>`, `<button class="btn primary" data-ok>知道了</button>`,
    (m, close) => { m.querySelector('[data-ok]').onclick = close; });
}

export function showTray() {
  const d = $('#drawer'), body = $('#drawer-body');
  d.classList.remove('hidden');
  $('#drawer-title').textContent = `暂存盘 · ${S.tray.length} 项`;
  body.innerHTML = `<div class="tray-actions">
      <button class="btn primary" data-t="copy">全部复制到活动窗格</button>
      <button class="btn" data-t="move">全部移动到活动窗格</button>
      <button class="btn danger" data-t="clear">清空</button></div>` +
    (S.tray.length ? S.tray.map((p, i) => `<div class="tray-row" data-p="${esc(p)}" data-i="${i}">
        ${iconSvg({path:p, name:basename(p), is_dir:false, ext:p.split('.').pop()})}
        <span class="tn" title="${esc(p)}">${esc(basename(p))}</span>
        <span class="tp" title="${esc(dirname(p))}">${esc(dirname(p))}</span>
        <button class="navbtn" data-rm="${i}" title="移除"><svg class="i" style="width:13px;height:13px"><use href="#ic-x"/></svg></button>
      </div>`).join('') : '<div class="hint">暂存盘为空。选中文件后右键「加入暂存盘」，或复制 / 剪切自动收集。</div>');
  body.querySelector('[data-t="copy"]').onclick = () => A.trayTransfer(false);
  body.querySelector('[data-t="move"]').onclick = () => A.trayTransfer(true);
  body.querySelector('[data-t="clear"]').onclick = () => { S.tray = []; saveState(); showTray(); };
  body.querySelectorAll('[data-rm]').forEach(b => b.onclick = async e => {
    e.stopPropagation(); await A.trayRemove(S.tray[Number(b.dataset.rm)]); showTray();
  });
  body.querySelectorAll('[data-p]').forEach(r => r.ondblclick = () => A.activate(r.dataset.p));
}
