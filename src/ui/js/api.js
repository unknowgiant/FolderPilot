// 后端桥接。业务命令只有一个入口：call(method, params)。
// ?demo=1 或脱离 pywebview 时启用纯前端 mock，便于在浏览器里做界面/交互自测。
import { normKey, basename, dirname, toast, fmtDate, TOKEN } from './util.js';

// 演示模式只能由显式 ?demo=1 开启。pywebview 的桥是异步注入的，
// 不能用「当前有没有 pywebview」来推断，否则真实程序会误跑假数据。
export const DEMO = new URLSearchParams(location.search).has('demo');

// 版本信息由服务端注入 index.html 的 meta，前端不写死版本号。
// 占位符未被替换（如直接用 file:// 打开）时回退为空，界面显示「—」。
export const APP_META = (() => {
  const read = (name, fallback) => {
    const el = document.querySelector(`meta[name="${name}"]`);
    const v = el && el.getAttribute('content');
    return v && !v.startsWith('__FMP') ? v : fallback;
  };
  return {
    title: read('fmp-title', '文件管理多面手'),
    version: read('fmp-version', ''),
    dataDir: read('fmp-data-dir', ''),
  };
})();

const T0 = Date.now() / 1000 - 86400 * 28;
const ROOT = 'D:\\移动云盘同步盘\\第二批设计';
const LONG = '8、2024年高价值宽带用户覆盖提升工程\\1、施工图设计\\第一批设计\\快扩\\家客';
const FILES = [
  '2、2025年商宽带一期工程、施工图设计、第二批施工图设计、单段落资料、伊川.xlsx',
  '8、2024年高价值宽带用户覆盖提升工程、施工图设计、第一批设计、快扩、家客、伊川.docx',
  '中国移动通信集团湖南分公司2026年家客工程施工图设计说明.pdf',
  '伊川乡镇基站光缆线路图.dwg', '第二批设计-材料表.xlsx', '设计变更联系单.docx',
  '现场踏勘照片.zip', '预算表-451定额.xlsm', '会议纪要.md', 'readme.txt',
];
const EXIST = new Set([ROOT, ROOT + '\\' + LONG]);
function E(path, isDir, size, mtime, rel = '') {
  EXIST.add(path);
  return {path, name: basename(path), parent: dirname(path), is_dir: isDir, size, mtime,
    ctime: mtime, ext: isDir ? '' : (path.split('.').pop() || '').toLowerCase(),
    kind: isDir ? '文件夹' : ((path.split('.').pop() || '').toUpperCase() + ' 文件'),
    rel, source: 'Everything SDK', tags: []};
}
function demoDir() {
  const out = [];
  for (let i = 1; i <= 6; i++) out.push(E(`${ROOT}\\${LONG}\\伊川-${i}期`, true, 0, T0 + i * 3600));
  for (let i = 0; i < FILES.length; i++) out.push(E(`${ROOT}\\${FILES[i]}`, false, 12000 + i * 31847, T0 + i * 7200));
  return out;
}
function demoSearch(req) {
  const out = [];
  for (let i = 1; i <= 14; i++) {
    const folder = `${ROOT}\\${LONG.split('\\')[0]}\\${i}、施工图设计\\第一批设计\\快扩\\家客`;
    out.push(E(`${folder}\\伊川扩容-${i}`, true, 0, T0 + i * 5400,
      `${LONG.split('\\')[0]}\\${i}、施工图设计\\第一批设计\\快扩\\家客\\伊川扩容-${i}`));
  }
  for (let i = 0; i < 9; i++) out.push(E(`${ROOT}\\${LONG}\\伊川施工图说明-${i + 1}.docx`, false,
    45000 + i * 1200, T0 + i * 3000, `${LONG}\\伊川施工图说明-${i + 1}.docx`));
  const q = (req.query || '').toLowerCase();
  if (q) {
    const hit = out.filter(x => x.name.toLowerCase().includes(q) || x.path.toLowerCase().includes(q));
    return hit.length ? hit : out.slice(0, 4);
  }
  return out;
}
const DEMO_STATE = {
  theme: 'light', skin: 'default', skin_wallpaper: true, skin_opacity: 100,
  density: 'comfortable', layout: 2, sidebar_width: 214,
  show_hidden: false, confirm_delete: true, ev_max: 500, colw: {size: 96, mtime: 146, type: 108, parent: 220},
  favorites: [ROOT], tags: {}, tray: [], history: ['伊川', '施工图设计'], session: null,
  folder_memory: {}, last_paths: [], hover_preview: true, ev_autostart: true,
};

function mockCall(method, p) {
  const R = d => ({ok: true, data: d});
  switch (method) {
    case 'app.info': return R({name: APP_META.title, version: APP_META.version,
      project: APP_META.title, app_id:'FileManagerMulti', data_dir: APP_META.dataDir,
      platform:'windows', python:'3.14'});
    case 'state.get': return R({...DEMO_STATE});
    case 'state.set': Object.assign(DEMO_STATE, p.patch || p); return R({saved:true});
    case 'dir.list': return R({path: p.path || ROOT, entries: demoDir(), count: 16});
    case 'dir.drives': return R({drives:[
      {path:'C:\\', name:'Windows SSD (C:)', letter:'C', total:512e9, free:186e9, type:'本地磁盘'},
      {path:'D:\\', name:'移动云盘同步盘 (D:)', letter:'D', total:2048e9, free:612e9, type:'本地磁盘'},
      {path:'E:\\', name:'工作资料 (E:)', letter:'E', total:1024e9, free:903e9, type:'本地磁盘'}]});
    case 'dir.special': return R({items:[{name:'桌面',path:'C:\\Users\\demo\\Desktop'},
      {name:'下载',path:'C:\\Users\\demo\\Downloads'},{name:'文档',path:'C:\\Users\\demo\\Documents'}]});
    case 'dir.exists': return R({exists: EXIST.has(normKey(p.path)) || true, is_dir: true});
    case 'entry.stat': return R({entries:(p.paths||[]).map(x => E(x, false, 1024, T0))});
    case 'entry.props': return R({path:p.path, name:basename(p.path), is_dir:false, size:128000,
      file_count:0, mtime:'2026-10-26 17:35', ctime:'2026-10-20 09:12', atime:'2026-11-12 08:10',
      attributes:['存档'], kind:'文件', parent:dirname(p.path), ext:'docx'});
    case 'entry.preview': return R({...E(p.path,false,1000,T0), preview:'text',
      text:'# ' + APP_META.title + '\n\n演示预览内容：\n统一条目模型 → 绝对路径 → 可打开。', lang:'markdown'});
    case 'entry.open': case 'entry.open_parent': case 'entry.reveal':
      toast(`已打开：${basename(p.path)}`); return R({opened:true});
    case 'entry.runas': case 'entry.terminal': return R({ok:true});
    case 'entry.parent': return R({parent: dirname(p.path)});
    case 'search.run': return R({entries: demoSearch(p), backend:'Everything SDK', elapsed:3,
      total:0, note:'', query:p.query||'', scope:p.scope||'global', root:p.root||'',
      index_ready:true, index_count:0});
    case 'search.status': return R({sdk:true, http:false, pinyin:true, version:'1.5',
      backend:'内置引擎', index_ready:true, index_count:0,
      engine:{deployed:true, external:'', service:'running', needs_auth:false,
        source:'bundled', version:'1.4', label:'内置引擎',
        dir:'%APPDATA%\\FileManagerMulti\\v1\\engine',
        exe:'%APPDATA%\\FileManagerMulti\\v1\\engine\\Everything.exe'}});
    case 'search.connect': return R({sdk:true, backend:'内置引擎'});
    case 'engine.status': return R({deployed:true, external:'', service:'running',
      needs_auth:false, source:'bundled', version:'1.4', label:'内置引擎', last_error:'',
      dir:'%APPDATA%\\FileManagerMulti\\v1\\engine'});
    case 'engine.enable': return R({sdk:true, backend:'内置引擎',
      engine:{deployed:true, service:'running', needs_auth:false, source:'bundled'}});
    case 'engine.stop': return R({sdk:false, backend:'本地索引',
      engine:{deployed:true, service:'running', needs_auth:false, source:'local'}});
    case 'ops.rename': return R({path: dirname(p.path) + '\\' + p.name});
    case 'ops.mkdir': return R({path: (p.parent||ROOT) + '\\新建文件夹'});
    case 'ops.newtext': return R({path: (p.parent||ROOT) + '\\新建文本文档.txt'});
    case 'ops.trash': return R({ok:true});
    case 'ops.copy': case 'ops.move': return R({job:'demo-job'});
    case 'ops.zip': case 'ops.unzip': case 'ops.extract': return R({path:p.dest||ROOT});
    case 'clip.check': return R({items: (p.paths || []).map(x => ({
      path: x, length: x.length, exists: true, attrs: 32,
      unsafe_attrs: [], readable: true, error: ''}))});
    case 'clip.write': case 'clip.text': return R({ok:true});
    case 'clip.read': return R({paths:[], move:false});
    case 'task.status': return R({id:'demo-job', state:'done', done:1, total:1, current:'', error:''});
    case 'task.cancel': return R({ok:true});
    case 'tags.set': return R({tags:{}});
    case 'data.export': return R({path:'C:\\demo\\export.csv'});
    default: return R({});
  }
}

// 命令通道为带 token 的本地 HTTP，不依赖 pywebview 的 js_api 注入。
// js_api 是异步注入的，启动竞态下会出现 `api.call is not a function`，
// 因此这里不再等待、也不再调用 window.pywebview。
export async function waitBridge() {
  return true;
}

export async function api(method, params = {}, attempt = 0) {
  if (DEMO) {
    await new Promise(r => setTimeout(r, 18));
    const j = mockCall(method, params);
    if (!j.ok) throw new Error(j.error);
    return j.data;
  }
  let res;
  try {
    res = await fetch('/api?t=' + encodeURIComponent(TOKEN), {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-FMP-Token': TOKEN},
      body: JSON.stringify({method, params}),
    });
  } catch (ex) {
    if (attempt < 2) {
      await new Promise(r => setTimeout(r, 180 * (attempt + 1)));
      return api(method, params, attempt + 1);
    }
    throw new Error('无法连接本地服务：' + ex.message);
  }
  let j;
  try { j = await res.json(); }
  catch (_) { throw new Error('命令返回格式异常 (HTTP ' + res.status + ')'); }
  if (!j.ok) throw new Error(j.error || '命令执行失败');
  return j.data;
}
