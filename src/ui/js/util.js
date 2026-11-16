// 通用工具
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const TOKEN = document.querySelector('meta[name="fmp-token"]')?.content || '';

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
export function escReg(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

export function fmtSize(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' B';
  if (n < 1024 ** 2) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 ** 3) return (n / 1024 ** 2).toFixed(1) + ' MB';
  return (n / 1024 ** 3).toFixed(2) + ' GB';
}
export function fmtDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000), now = new Date();
  const p = x => String(x).padStart(2, '0');
  if (d.getFullYear() === now.getFullYear()) return `${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`;
}
export function fmtDateTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000), p = x => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function fileUrl(path) { return `/file?p=${encodeURIComponent(path)}&t=${encodeURIComponent(TOKEN)}`; }

const ICON = {folder:'ic-folder', image:'ic-image', doc:'ic-doc', zip:'ic-zip', video:'ic-video',
              audio:'ic-audio', exe:'ic-exe', cad:'ic-cad', pdf:'ic-pdf', file:'ic-file'};
export function iconOf(e) {
  if (e.is_dir) return 'ic-folder';
  const x = (e.ext || '').toLowerCase();
  if (['png','jpg','jpeg','gif','bmp','webp','svg','ico','avif'].includes(x)) return 'ic-image';
  if (['pdf'].includes(x)) return 'ic-pdf';
  if (['zip','rar','7z'].includes(x)) return 'ic-zip';
  if (['mp4','mkv','avi','mov','webm'].includes(x)) return 'ic-video';
  if (['mp3','wav','flac','aac','m4a'].includes(x)) return 'ic-audio';
  if (['exe','msi','bat','cmd'].includes(x)) return 'ic-exe';
  if (['dwg','dxf','vsdx','psd'].includes(x)) return 'ic-cad';
  if (['doc','docx','txt','md','xls','xlsx','ppt','pptx','wps'].includes(x)) return 'ic-doc';
  return ICON.file;
}
export function iconSvg(e, cls = '') {
  return `<svg class="i ic ${cls}${e.is_dir?' dir':''}"><use href="#${iconOf(e)}"/></svg>`;
}
export function highlight(name, kw) {
  const s = esc(name);
  if (!kw) return s;
  const parts = kw.trim().split(/\s+/).filter(Boolean).map(escReg);
  if (!parts.length) return s;
  try { return s.replace(new RegExp('(' + parts.join('|') + ')', 'ig'), '<b>$1</b>'); }
  catch (_) { return s; }
}
export function debounce(fn, ms = 260) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
let toastT;
export function toast(msg, err = false) {
  const el = $('#toast'); if (!el) return;
  el.textContent = msg; el.className = 'toast' + (err ? ' err' : '');
  clearTimeout(toastT); toastT = setTimeout(() => el.classList.add('hidden'), 2600);
}
export function normKey(p) { return String(p || '').replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase(); }
export function basename(p) { return String(p || '').replace(/\\+$/, '').split('\\').pop() || p; }
export function dirname(p) {
  const s = String(p || '').replace(/\\+$/, '');
  const i = s.lastIndexOf('\\');
  return i < 0 ? s : (i === 2 ? s.slice(0, 3) : s.slice(0, i));
}
export function joinPath(dir, name) {
  const d = String(dir || '').replace(/\\+$/, '');
  return d.endsWith(':') ? d + '\\' + name : d + '\\' + name;
}
export const COLORS = ['c1','c2','c3','c4','c5','c6','c7'];
export const COLOR_NAMES = ['红色','橙色','黄色','绿色','蓝色','紫色','粉色'];
export function colorVar(c) { return `var(--${c})`; }
