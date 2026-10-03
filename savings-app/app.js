'use strict';

/* =====================  Dữ liệu & lưu trữ  ===================== */
const KEY = 'sotietkiem.v1';
const normName = (s) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').replace(/[^a-z0-9]/g, '');
const BANK_INDEX = new Map();
BANK_LIST.forEach((b) => [b.n, ...b.a].forEach((k) => BANK_INDEX.set(normName(k), b)));
const bankInfo = (name) => BANK_INDEX.get(normName(name)) || null;
const PALETTE = ['#34d399', '#60a5fa', '#f472b6', '#fbbf24', '#a78bfa', '#fb923c', '#22d3ee', '#f87171'];

const DEFAULTS = () => ({ names: { vo: 'Vợ', chong: 'Chồng' }, books: [], hidden: [] });
let state = load();
let tab = 'all';
const openBanks = new Set();

function load() {
  try {
    const s = JSON.parse(localStorage.getItem(KEY));
    if (s && Array.isArray(s.books)) return { ...DEFAULTS(), ...s };
  } catch (e) { /* ignore */ }
  return DEFAULTS();
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { toast('Không lưu được dữ liệu!'); }
}
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

/* =====================  Tính toán lãi  ===================== */
const DAY = 86400000;
const pd = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const today0 = () => { const t = new Date(); return new Date(t.getFullYear(), t.getMonth(), t.getDate()); };
const diffDays = (a, b) => Math.round((Date.UTC(b.getFullYear(), b.getMonth(), b.getDate()) - Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())) / DAY);
function addMonths(d, n) {
  const r = new Date(d.getFullYear(), d.getMonth() + n, 1);
  const last = new Date(r.getFullYear(), r.getMonth() + 1, 0).getDate();
  r.setDate(Math.min(d.getDate(), last));
  return r;
}

function calc(b) {
  const t = today0();
  const start = pd(b.start);
  const mat = b.term > 0 ? addMonths(start, b.term) : null;
  const yearly = b.principal * b.rate / 100;
  const daily = yearly / 365;
  const matured = !!mat && t >= mat;
  const totalDays = mat ? diffDays(start, mat) : null;
  const elapsed = Math.max(0, diffDays(start, t));
  const used = totalDays ? Math.min(elapsed, totalDays) : elapsed;
  return {
    start, mat, matured, daily, yearly, monthly: yearly / 12,
    activeDaily: matured ? 0 : daily,
    activeMonthly: matured ? 0 : yearly / 12,
    accrued: daily * used,
    total: mat ? daily * totalDays : null,
    progress: totalDays ? Math.min(1, elapsed / totalDays) : null,
    daysLeft: mat ? diffDays(t, mat) : null,
  };
}

// Lãi rơi vào tháng [y, m] (cộng theo số ngày sổ còn hiệu lực trong tháng)
function interestInMonth(b, y, m) {
  const c = calc(b);
  const ms = new Date(y, m, 1), me = new Date(y, m + 1, 1);
  const from = c.start > ms ? c.start : ms;
  const to = c.mat && c.mat < me ? c.mat : me;
  const days = diffDays(from, to);
  return days > 0 ? c.daily * days : 0;
}

function scoped(s) { return state.books.filter((b) => s === 'all' || b.owner === s); }
function totals(list) {
  let principal = 0, daily = 0, monthly = 0;
  for (const b of list) { const c = calc(b); principal += b.principal; daily += c.activeDaily; monthly += c.activeMonthly; }
  return { principal, daily, monthly };
}

/* =====================  Định dạng  ===================== */
const nf = new Intl.NumberFormat('vi-VN');
const money = (n) => nf.format(Math.round(n));
const vnd = (n) => money(n) + ' ₫';
function compact(n) {
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toLocaleString('vi-VN', { maximumFractionDigits: 2 }) + ' tỷ';
  if (a >= 1e6) return (n / 1e6).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' tr';
  if (a >= 1e3) return (n / 1e3).toLocaleString('vi-VN', { maximumFractionDigits: 0 }) + 'k';
  return String(Math.round(n));
}
// Số rút gọn kiểu "23,1 triệu", "3 tỷ", "760,27K"
function short(n) {
  const a = Math.abs(n), f = (v, u) => v.toLocaleString('vi-VN', { maximumFractionDigits: 2 }) + u;
  if (a >= 1e9) return f(n / 1e9, ' tỷ');
  if (a >= 1e6) return f(n / 1e6, ' triệu');
  if (a >= 1e3) return f(n / 1e3, 'K');
  return String(Math.round(n));
}
// Nhãn trục biểu đồ: "3 T", "500 Tr", "20 K"
function axisLabel(v, dec = 1) {
  const a = Math.abs(v), f = (x, u) => x.toLocaleString('vi-VN', { maximumFractionDigits: dec }) + u;
  if (a >= 1e9) return f(v / 1e9, ' T');
  if (a >= 1e6) return f(v / 1e6, ' Tr');
  if (a >= 1e3) return f(v / 1e3, ' K');
  return String(Math.round(v));
}
const pct = (r) => r.toLocaleString('vi-VN', { maximumFractionDigits: 2 }) + '%';
const pctInt = (p) => Math.max(p > 0 ? 1 : 0, Math.round(p * 100));
// "5 tháng 30 ngày" còn lại đến ngày đáo hạn
function remainText(mat) {
  const t = today0();
  let m = (mat.getFullYear() - t.getFullYear()) * 12 + mat.getMonth() - t.getMonth();
  if (addMonths(t, m) > mat) m--;
  const d = diffDays(addMonths(t, Math.max(m, 0)), mat);
  return [m > 0 ? m + ' tháng' : '', d > 0 ? d + ' ngày' : ''].filter(Boolean).join(' ') || 'hôm nay';
}
const fmtDate = (d) => `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ownerName = (o) => state.names[o];

function bankColor(name) {
  let h = 0; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 55% 42%)`;
}
function logoHTML(name) {
  const i = bankInfo(name);
  if (i && i.logo) return `<div class="logo has${i.t ? ' tile' : ''}"><img src="${i.logo}" alt="${esc(name)}" loading="lazy"></div>`;
  return `<div class="logo" style="background:${bankColor(name)}">${esc(initials(name))}</div>`;
}
function initials(name) {
  const w = name.trim().split(/\s+/);
  return (w.length > 1 ? w[0][0] + w[1][0] : name.slice(0, 2)).toUpperCase();
}

/* =====================  Animation số  ===================== */
function countUp(el, to, fmt = money, dur = 1100) {
  const from = el._v || 0;
  el._v = to;
  const t0 = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - t0) / dur);
    const e = 1 - Math.pow(1 - k, 4);
    el.textContent = fmt(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function runCounters(root) {
  root.querySelectorAll('[data-count]').forEach((el) => {
    const kind = el.dataset.fmt;
    countUp(el, parseFloat(el.dataset.count), { vnd, short, pct }[kind] || money);
  });
}


/* =====================  Số liệu tổng hợp  ===================== */
// Lãi dự kiến / lãi tạm tính chỉ tính các sổ có kỳ hạn (sổ không kỳ hạn không có ngày đáo hạn).
function stats(list) {
  const s = { principal: 0, daily: 0, monthly: 0, expected: 0, accrued: 0, books: list.length, banks: 0, avgRate: 0 };
  const banks = new Set();
  let weighted = 0;
  for (const b of list) {
    const c = calc(b);
    s.principal += b.principal; s.daily += c.activeDaily; s.monthly += c.activeMonthly;
    weighted += b.principal * b.rate; banks.add(b.bank);
    if (c.total != null) { s.expected += c.total; s.accrued += c.accrued; }
  }
  s.banks = banks.size;
  s.avgRate = s.principal ? weighted / s.principal : 0;
  return s;
}

const monthKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;

// Tiền về theo tháng đáo hạn: 6 tháng đầu tiên (kể từ nay) có sổ đáo hạn
function flowData(list) {
  const m = new Map();
  for (const b of list) {
    const c = calc(b);
    if (!c.mat || c.matured) continue;
    const k = monthKey(c.mat);
    const e = m.get(k) || { k, y: c.mat.getFullYear(), m: c.mat.getMonth() + 1, principal: 0, interest: 0, books: [] };
    e.principal += b.principal; e.interest += c.total; e.books.push(b);
    m.set(k, e);
  }
  return [...m.values()].sort((a, b) => (a.k < b.k ? -1 : 1)).slice(0, 6);
}

// Sổ đã đến hạn hoặc sắp đến hạn trong 30 ngày
function alerts(list) {
  return list.map((b) => ({ b, c: calc(b) })).filter((x) => x.c.mat && (x.c.matured || x.c.daysLeft <= 30))
    .sort((a, b) => a.c.mat - b.c.mat);
}

/* =====================  Render  ===================== */
const view = document.getElementById('view');
const SECTIONS = [
  ['due', 'Sổ sắp đáo hạn'], ['month', 'Tổng nhận theo tháng'], ['flow', 'Dòng tiền sắp tới'],
  ['bank', 'Tiền gửi theo ngân hàng'], ['owner', 'Tiền gửi theo chủ sổ'], ['label', 'Tiền gửi theo nhãn'],
  ['accrued', 'Lãi tạm tính'], ['monthly', 'Lãi sinh ra mỗi tháng'],
];
const shown = (id) => !state.hidden.includes(id);
const sec = (html, id) => (html ? `<div class="sec"${id ? ` id="${id}"` : ''}>${html}</div>` : '');
const ICON = {
  bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/></svg>',
  chev: '<svg class="go" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>',
  down: '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>',
};

let flowMode = 'all';   // 'all' = gốc + lãi, 'int' = chỉ tiền lãi
let selMonth = null;    // tháng đang chọn trên biểu đồ dòng tiền ('YYYY-MM')
let ctx = { list: [], scope: 'all' };

function render(keep = false) {
  const y = window.scrollY;
  document.querySelectorAll('#tabs [data-tab]').forEach((b) => {
    b.classList.toggle('on', b.dataset.tab === tab);
    if (b.dataset.tab !== 'all') b.querySelector('.nm').textContent = ownerName(b.dataset.tab);
  });
  ctx = { list: scoped(tab), scope: tab };
  view.innerHTML = ctx.list.length ? (tab === 'all' ? renderAll() : renderOwner(tab)) : renderEmpty(tab);
  view.className = keep ? '' : 'fade-in';
  runCounters(view);
  requestAnimationFrame(() => requestAnimationFrame(animateDonut));
  window.scrollTo(0, keep ? y : 0);
}

function renderEmpty(o) {
  const title = o === 'all' ? 'Tổng quan' : 'Sổ ' + ownerName(o);
  return `<div class="head"><div><h1>${esc(title)}</h1><small>${fmtDate(new Date())}</small></div><div class="dot">💰</div></div>${emptyHTML(o === 'all' ? '' : o)}`;
}

/* ---- banner ---- */
function topHTML(list, scope, title) {
  const s = stats(list);
  const n = alerts(list).length;
  const label = scope === 'all' ? 'Tổng tiền đang gửi' : `Tổng tiền đang gửi · ${esc(ownerName(scope))}`;
  return `
  <section class="top ${scope}">
    <div class="top-row">
      <div><div class="lbl">${label}</div><div class="big"><span data-count="${s.principal}">0</span><small>₫</small></div></div>
      <button class="bell" data-bell aria-label="Sổ đến hạn">${ICON.bell}${n ? `<i>${n}</i>` : ''}</button>
    </div>
    <div class="sub">Lãi dự kiến <b data-count="${s.expected}" data-fmt="short">0</b> ₫</div>
    <div class="stats">
      <div><b><span data-count="${s.monthly}" data-fmt="short">0</span> ₫</b><span>Lãi / tháng</span></div>
      <div><b data-count="${s.avgRate}" data-fmt="pct">0</b><span>LS bình quân</span></div>
      <div><b>${s.books} sổ</b><span>${s.banks} ngân hàng</span></div>
    </div>
    <div class="live"><i class="pulse"></i><span>Lãi mỗi ngày <b><span data-count="${s.daily}">0</span> ₫</b></span><span>Hôm nay <b data-live="${s.daily}">0</b> ₫</span></div>
    ${title ? `<div class="top-title">${esc(title)}</div>` : ''}
  </section>`;
}

/* ---- sổ sắp đáo hạn ---- */
function dueHTML(list, scope, inBanner) {
  const items = list.map((b) => ({ b, c: calc(b) })).filter((x) => x.c.mat)
    .sort((a, b) => a.c.mat - b.c.mat).slice(0, 5);
  if (!items.length) return '';
  const cards = items.map(({ b, c }) => `
    <div class="due card" data-edit="${b.id}" role="button">
      <div class="due-h">${logoHTML(b.bank)}
        <div class="nm">${esc(b.bank)}${scope === 'all' ? `<small class="own ${b.owner}">${esc(ownerName(b.owner))}</small>` : ''}</div>
        <div class="amt">${short(b.principal)} ₫</div></div>
      <div class="due-r"><span>Lãi suất ${pct(b.rate)}</span><span>Lãi ${short(c.total)} ₫</span></div>
      <div class="due-r"><span>${c.matured ? '<b class="warn">Đã đến hạn</b>' : 'Còn ' + remainText(c.mat)}</span><span>Đáo hạn ${fmtDate(c.mat)}</span></div>
      <div class="prog"><i style="width:${(c.progress * 100).toFixed(1)}%"></i></div>
    </div>`).join('');
  return `${inBanner ? '' : '<div class="sec-title">Sổ sắp đáo hạn</div>'}<div class="due-scroll ${items.length > 1 ? 'many' : ''}">${cards}</div>`;
}

/* ---- tổng nhận theo tháng + dòng tiền ---- */
function monthInner(fd) {
  if (!fd.length) return '';
  const e = fd.find((x) => x.k === selMonth) || fd[0];
  selMonth = e.k;
  return `
  <div class="card tap" data-month="${e.k}">
    <div class="mh"><div class="ct">Tổng nhận tháng ${e.m}/${e.y}</div>${ICON.chev}</div>
    <div class="mbig"><span data-count="${e.principal + e.interest}" data-fmt="vnd">0</span></div>
    <div class="muted">Gốc ${short(e.principal)} ₫ · Lãi ${short(e.interest)} ₫</div>
  </div>`;
}

function niceStep(max, n = 3) {
  const raw = max / n, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

function flowInner(fd) {
  if (!fd.length) {
    return `<div class="card"><div class="ct">Dòng tiền sắp tới</div><p class="muted" style="margin:8px 0 0">Chưa có sổ nào sắp đáo hạn. Sổ có kỳ hạn sẽ hiện ở đây theo tháng tiền về.</p></div>`;
  }
  const val = (e) => (flowMode === 'all' ? e.principal + e.interest : e.interest);
  const max = Math.max(...fd.map(val), 1);
  const step = niceStep(max), n = Math.ceil(max / step), top = step * n;
  const ticks = Array.from({ length: n + 1 }, (_, i) => i);
  const yax = ticks.map((i) => `<span style="bottom:${(i / n) * 100}%">${i === 0 ? '0' : axisLabel(i * step)}</span>`).join('');
  const grid = ticks.map((i) => `<div class="gl" style="bottom:${(i / n) * 100}%"></div>`).join('');
  const cols = fd.map((e, i) => {
    const h = Math.max(2, val(e) / top * 100);
    const inner = flowMode === 'all'
      ? `<i class="si" style="flex:${e.interest}"></i><i class="sp" style="flex:${e.principal}"></i>`
      : '<i class="si" style="flex:1"></i>';
    return `<button class="fcol ${e.k === selMonth ? 'on' : ''}" data-pick="${e.k}" aria-label="Tháng ${e.m}/${e.y}">
      <span class="fv" style="bottom:calc(${h}% + 4px)">${axisLabel(val(e))}</span>
      <div class="fbw"><div class="fb" style="height:${h}%;animation-delay:${i * 80}ms">${inner}</div></div></button>`;
  }).join('');
  const months = fd.map((e) => `<span class="${e.k === selMonth ? 'on' : ''}">T${e.m}</span>`).join('');
  const years = [];
  fd.forEach((e) => { const l = years[years.length - 1]; if (l && l.y === e.y) l.n++; else years.push({ y: e.y, n: 1 }); });
  const yr = years.map((g) => `<div class="yr" style="grid-column:span ${g.n}"><i></i>${g.y}</div>`).join('');
  return `
  <div class="card">
    <div class="flow-h"><div class="ct">Dòng tiền sắp tới</div>
      <div class="toggle"><button data-mode="all" class="${flowMode === 'all' ? 'on' : ''}">Gốc + lãi</button><button data-mode="int" class="${flowMode === 'int' ? 'on' : ''}">Tiền lãi</button></div></div>
    <div class="fl">
      <div class="yx"><div class="in">${yax}</div></div>
      <div class="pl"><div class="in">${grid}<div class="cols ${fd.length > 1 ? 'multi' : ''}" style="grid-template-columns:repeat(${fd.length},1fr)">${cols}</div></div></div>
      <div></div>
      <div class="xx" style="grid-template-columns:repeat(${fd.length},1fr)">${months}${yr}</div>
    </div>
    <div class="note">${flowMode === 'all' ? '<i class="lg-p"></i>Gốc <i class="lg-i"></i>Lãi · ' : ''}Hiển thị ${fd.length >= 6 ? '6 tháng' : 'các tháng'} tiếp theo có tiền về.</div>
  </div>`;
}

function refreshFlow() {
  const fd = flowData(ctx.list);
  const m = document.getElementById('secMonth'), f = document.getElementById('secFlow');
  if (m) { m.innerHTML = monthInner(fd); runCounters(m); }
  if (f) f.innerHTML = flowInner(fd);
}

/* ---- theo ngân hàng / chủ sổ / nhãn ---- */
function bankHTML(list) {
  const byBank = {};
  list.forEach((b) => { byBank[b.bank] = (byBank[b.bank] || 0) + b.principal; });
  const rows = Object.entries(byBank).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((s, r) => s + r[1], 0);
  if (!total) return '';
  const R = 82, SW = 18, GAP = 6, C = 2 * Math.PI * R;
  let cum = 0, segs = '', leg = '';
  rows.forEach(([name, val], i) => {
    const f = val / total, col = PALETTE[i % PALETTE.length];
    const len = Math.max(0.01, f * C - SW - GAP);
    segs += `<circle class="seg" cx="100" cy="100" r="${R}" stroke="${col}" style="stroke-dasharray:0 ${C}" data-d="${len} ${C - len}" stroke-dashoffset="${-(cum * C + (SW + GAP) / 2)}"/>`;
    leg += `<div class="lg">${logoHTML(name)}<div class="lt"><b>${esc(name)}</b><span>${pctInt(f)}% · ${short(val)} ₫</span></div><i class="lb" style="width:${Math.max(14, f * 100)}px;background:${col}"></i></div>`;
    cum += f;
  });
  return `
  <div class="card">
    <div class="ct">Tiền gửi theo ngân hàng</div>
    <div class="donut"><svg viewBox="0 0 200 200"><circle cx="100" cy="100" r="${R}" class="trk"/>${segs}</svg>
      <div class="ctr"><b>${rows.length}</b><span>Ngân hàng</span></div></div>
    <div class="legend">${leg}</div>
  </div>`;
}
function animateDonut() {
  document.querySelectorAll('.donut .seg').forEach((c) => { c.style.strokeDasharray = c.dataset.d; });
}

function rowsHTML(rows, total) {
  return rows.map((r) => {
    const p = total ? r.val / total : 0;
    return `<div class="bl ${r.go ? 'tap' : ''}" ${r.go ? `data-go="${r.go}"` : ''}>
      <div class="bl-h"><span><i class="d" style="background:${r.col}"></i>${esc(r.name)} (${pctInt(p)}%)</span><b>${short(r.val)} ₫</b></div>
      <div class="bl-b"><i style="width:${(p * 100).toFixed(1)}%;background:${r.col}"></i></div></div>`;
  }).join('');
}

function ownerHTML(list) {
  const rows = ['vo', 'chong'].map((o) => ({ name: ownerName(o), go: o, col: `var(--${o})`, val: list.filter((b) => b.owner === o).reduce((s, b) => s + b.principal, 0) })).filter((r) => r.val > 0);
  const total = rows.reduce((s, r) => s + r.val, 0);
  return rows.length ? `<div class="card"><div class="ct">Tiền gửi theo chủ sổ</div>${rowsHTML(rows, total)}</div>` : '';
}

function labelHTML(list) {
  const g = {};
  list.forEach((b) => { const k = b.note || ''; g[k] = (g[k] || 0) + b.principal; });
  if (!Object.keys(g).some((k) => k)) return '';
  let i = 0;
  const rows = Object.entries(g).sort((a, b) => b[1] - a[1]).map(([k, val]) => ({ name: k || 'Chưa gắn nhãn', val, col: k ? PALETTE[i++ % PALETTE.length] : '#64748b' }));
  const total = rows.reduce((s, r) => s + r.val, 0);
  return `<div class="card"><div class="ct">Tiền gửi theo nhãn</div>${rowsHTML(rows, total)}</div>`;
}

/* ---- lãi tạm tính + lãi từng tháng ---- */
function accruedHTML(list) {
  const s = stats(list);
  if (!s.expected) return '';
  const p = Math.min(1, s.accrued / s.expected);
  return `
  <div class="card">
    <div class="ct">Lãi tạm tính</div>
    <div class="ac-top"><span>Đã tích lũy đến hôm nay</span><b class="pc">${(p * 100).toLocaleString('vi-VN', { maximumFractionDigits: 1 })}%</b></div>
    <div class="ac-big"><span data-count="${s.accrued}" data-fmt="short">0</span> ₫</div>
    <div class="prog"><i style="width:${Math.max(1, p * 100).toFixed(1)}%"></i></div>
    <div class="ac-bot"><div><span>Còn lại</span><b>${short(s.expected - s.accrued)} ₫</b></div><div class="r"><span>Tổng dự kiến</span><b>${short(s.expected)} ₫</b></div></div>
  </div>`;
}

function barsHTML(list) {
  if (!list.length) return '';
  const now = new Date();
  const items = [];
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
    const v = list.reduce((s, b) => s + interestInMonth(b, d.getFullYear(), d.getMonth()), 0);
    items.push({ v, label: 'T' + (d.getMonth() + 1), now: i === 0 });
  }
  const max = Math.max(...items.map((x) => x.v), 1);
  const bars = items.map((x, i) =>
    `<div class="bar ${x.now ? 'now' : ''}"><div class="col" style="height:${Math.max(4, x.v / max * 100)}%;animation-delay:${i * 60}ms"></div><small>${x.label}</small></div>`).join('');
  return `
  <div class="card">
    <div class="ct">Lãi sinh ra mỗi tháng</div>
    <div class="bars">${bars}</div>
    <div class="bar-note">Tháng này: <b style="color:var(--gold)">${vnd(items[0].v)}</b> · Cao nhất: ${vnd(max)}<br>Chưa tính tái tục các sổ đến hạn.</div>
  </div>`;
}

/* ---- các phần của dashboard (trừ "sổ sắp đáo hạn") ---- */
function dashSections(list, scope) {
  const fd = flowData(list);
  if (!fd.some((e) => e.k === selMonth)) selMonth = fd.length ? fd[0].k : null;
  const out = [];
  if (shown('month') && fd.length) out.push(sec(monthInner(fd), 'secMonth'));
  if (shown('flow')) out.push(sec(flowInner(fd), 'secFlow'));
  if (shown('bank')) out.push(sec(bankHTML(list)));
  if (shown('owner') && scope === 'all') out.push(sec(ownerHTML(list)));
  if (shown('label')) out.push(sec(labelHTML(list)));
  if (shown('accrued')) out.push(sec(accruedHTML(list)));
  if (shown('monthly')) out.push(sec(barsHTML(list)));
  out.push(`<div class="sec"><button class="custom" id="btnCustom">Tùy biến</button></div>`);
  return out.join('');
}

function renderAll() {
  const list = ctx.list;
  const due = shown('due') ? dueHTML(list, 'all', true) : '';
  return topHTML(list, 'all', due ? 'Sổ sắp đáo hạn' : '') + sec(due) + dashSections(list, 'all');
}

function renderOwner(o) {
  const list = ctx.list;
  const byBank = {};
  list.forEach((b) => (byBank[b.bank] = byBank[b.bank] || []).push(b));
  const sum = (arr) => arr.reduce((s, x) => s + x.principal, 0);
  const acc = Object.entries(byBank).sort((a, b) => sum(b[1]) - sum(a[1])).map(([name, arr]) => {
    const t = totals(arr);
    const key = o + '|' + name;
    return `
    <div class="bank ${openBanks.has(key) ? 'open' : ''}" data-key="${esc(key)}">
      <button class="bank-h" data-toggle>
        ${logoHTML(name)}
        <div class="mid"><div class="nm">${esc(name)}</div><div class="sub">${arr.length} sổ</div></div>
        <div class="amt">${vnd(t.principal)}<small>+${vnd(t.daily)}/ngày</small></div>
        ${ICON.down}
      </button>
      <div class="acc"><div><div class="books">${arr.sort((a, b) => b.principal - a.principal).map(bookHTML).join('')}</div></div></div>
    </div>`;
  }).join('');
  const due = shown('due') ? dueHTML(list, o, false) : '';
  return topHTML(list, o, 'Ngân hàng đang gửi') + sec(acc) + sec(due) + dashSections(list, o);
}

function bookHTML(b) {
  const c = calc(b);
  const termTxt = b.term > 0 ? `${b.term} tháng` : 'Không kỳ hạn';
  let foot;
  if (c.mat) {
    foot = c.matured
      ? `<span class="badge">Đã đến hạn ${fmtDate(c.mat)}</span>`
      : `<span>Đáo hạn ${fmtDate(c.mat)}</span><span class="badge ${c.daysLeft <= 14 ? 'soon' : ''}">còn ${c.daysLeft} ngày</span>`;
  } else foot = '<span>Rút bất cứ lúc nào</span>';
  return `
  <div class="book" data-edit="${b.id}" role="button">
    <div class="r1"><span class="p">${vnd(b.principal)}</span><span class="rate">${pct(b.rate)}/năm</span></div>
    <div class="meta">${termTxt} · gửi ${fmtDate(c.start)}${b.note ? ' · ' + esc(b.note) : ''}</div>
    <div class="grid">
      <div><span>Lãi mỗi ngày</span><b>${vnd(c.daily)}</b></div>
      <div><span>Lãi mỗi tháng</span><b>${vnd(c.monthly)}</b></div>
      <div><span>Đã sinh lãi</span><b>${vnd(c.accrued)}</b></div>
      <div><span>${c.total != null ? 'Lãi khi đáo hạn' : 'Lãi mỗi năm'}</span><b>${vnd(c.total != null ? c.total : c.yearly)}</b></div>
    </div>
    ${c.progress != null ? `<div class="prog"><i style="width:${(c.progress * 100).toFixed(1)}%"></i></div>` : ''}
    <div class="foot">${foot}</div>
    ${c.matured ? `<button class="renew" data-renew="${b.id}">↻ Tái tục (tính lại từ ngày đáo hạn)</button>` : ''}
  </div>`;
}

function emptyHTML(o) {
  return `<div class="empty"><div class="e">🐷</div><h2>Chưa có sổ tiết kiệm nào</h2>
    <p>Bấm nút <b>+</b> để thêm sổ${o ? ' của ' + esc(ownerName(o)) : ''}.</p>
    <button class="btn" data-add>＋ Thêm sổ</button>
    <button class="btn ghost" id="btnDemo">Xem thử với dữ liệu mẫu</button></div>`;
}

/* =====================  Bảng phụ: thông báo, tháng, tùy biến  ===================== */
function openBell() {
  const items = alerts(ctx.list);
  sheet.innerHTML = `<div class="panel"><h2>Sổ đến hạn</h2>${items.length ? items.map(({ b, c }) => `
    <div class="mrow">${logoHTML(b.bank)}
      <div class="mt"><b>${esc(b.bank)} · ${esc(ownerName(b.owner))}</b><span>${short(b.principal)} ₫ · đáo hạn ${fmtDate(c.mat)}</span></div>
      <span class="badge ${c.matured || c.daysLeft <= 14 ? 'soon' : ''}">${c.matured ? 'Đã đến hạn' : 'còn ' + remainText(c.mat)}</span></div>`).join('')
    : '<p class="muted">Không có sổ nào đến hạn trong 30 ngày tới.</p>'}
    <div class="actions"><button class="btn" id="mClose" type="button">Đóng</button></div></div>`;
  sheet.hidden = false;
  sheet.onclick = (e) => { if (e.target === sheet || e.target.id === 'mClose') closeForm(); };
}

function openMonth(k) {
  const e = flowData(ctx.list).find((x) => x.k === k);
  if (!e) return;
  sheet.innerHTML = `<div class="panel"><h2>Đáo hạn tháng ${e.m}/${e.y}</h2>${e.books.map((b) => {
    const c = calc(b);
    return `<div class="mrow">${logoHTML(b.bank)}
      <div class="mt"><b>${esc(b.bank)} · ${esc(ownerName(b.owner))}</b><span>${fmtDate(c.mat)} · gốc ${short(b.principal)} ₫ + lãi ${short(c.total)} ₫</span></div>
      <b class="gain">${short(b.principal + c.total)} ₫</b></div>`;
  }).join('')}<div class="actions"><button class="btn" id="mClose" type="button">Đóng</button></div></div>`;
  sheet.hidden = false;
  sheet.onclick = (ev) => { if (ev.target === sheet || ev.target.id === 'mClose') closeForm(); };
}

function openCustomize() {
  sheet.innerHTML = `<div class="panel"><h2>Tùy biến trang tổng quan</h2><p class="muted" style="margin:0 0 6px">Chọn các phần muốn hiển thị.</p>
    ${SECTIONS.map(([id, name]) => `<label class="swrow"><span>${name}</span><input type="checkbox" class="sw" data-sec="${id}" ${shown(id) ? 'checked' : ''}></label>`).join('')}
    <div class="actions"><button class="btn" id="cDone" type="button">Xong</button></div></div>`;
  sheet.hidden = false;
  const done = () => { closeForm(); render(true); };
  sheet.onclick = (e) => { if (e.target === sheet || e.target.id === 'cDone') done(); };
  sheet.onchange = (e) => {
    const id = e.target.dataset.sec; if (!id) return;
    state.hidden = state.hidden.filter((x) => x !== id);
    if (!e.target.checked) state.hidden.push(id);
    save();
  };
}


/* =====================  Số "đang chạy" trong ngày  ===================== */
setInterval(() => {
  const el = document.querySelector('[data-live]');
  if (!el) return;
  const n = new Date();
  const frac = (n - today0()) / DAY;
  el.textContent = (parseFloat(el.dataset.live) * frac).toLocaleString('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}, 250);

/* =====================  Form thêm / sửa  ===================== */
const sheet = document.getElementById('sheet');

function openForm(id, defOwner) {
  const b = id ? state.books.find((x) => x.id === id) : null;
  const d = b || { owner: defOwner || (tab !== 'all' ? tab : 'vo'), bank: '', principal: '', rate: '', term: 12, start: iso(new Date()), note: '' };
  sheet.innerHTML = `
  <div class="panel" role="dialog">
    <h2>${b ? 'Sửa sổ tiết kiệm' : 'Thêm sổ tiết kiệm'}</h2>
    <label>Chủ sổ</label>
    <div class="seg" id="fOwner">
      ${['vo', 'chong'].map((o) => `<button type="button" data-v="${o}" class="${d.owner === o ? 'on' : ''}">${o === 'vo' ? '♀' : '♂'} ${esc(ownerName(o))}</button>`).join('')}
    </div>
    <label>Ngân hàng</label>
    <button type="button" class="pickbtn" id="fBank"></button>
    <label>Tiền gốc (₫)</label>
    <input id="fPrincipal" inputmode="numeric" placeholder="vd: 500.000.000" value="${d.principal ? money(d.principal) : ''}">
    <div class="row2">
      <div><label>Lãi suất (%/năm)</label><input id="fRate" inputmode="decimal" placeholder="vd: 5,6" value="${d.rate !== '' ? String(d.rate).replace('.', ',') : ''}"></div>
      <div><label>Kỳ hạn (tháng)</label><input id="fTerm" inputmode="numeric" placeholder="0 = không kỳ hạn" value="${d.term}"></div>
    </div>
    <label>Ngày gửi</label>
    <input id="fStart" type="date" value="${d.start}">
    <label>Nhãn (tuỳ chọn)</label>
    <input id="fNote" placeholder="vd: Mua nhà, Quỹ học phí" value="${esc(d.note || '')}">
    <div class="chips" id="fChips">${[...new Set(state.books.map((x) => x.note).filter(Boolean))].map((l) => `<button type="button" class="lchip" data-l="${esc(l)}">${esc(l)}</button>`).join('')}</div>
    <div class="preview" id="fPrev"></div>
    <div class="actions">
      ${b ? '<button class="btn danger" id="fDel" type="button">Xoá</button>' : ''}
      <button class="btn ghost" id="fCancel" type="button">Huỷ</button>
      <button class="btn" id="fSave" type="button">Lưu</button>
    </div>
  </div>`;
  sheet.hidden = false;
  let owner = d.owner, bank = d.bank;
  const $ = (s) => sheet.querySelector(s);

  const read = () => ({
    principal: parseInt(($('#fPrincipal').value || '').replace(/\D/g, ''), 10) || 0,
    rate: parseFloat(($('#fRate').value || '').replace(',', '.')) || 0,
    term: parseInt($('#fTerm').value, 10) || 0,
    start: $('#fStart').value,
  });
  const preview = () => {
    const v = read();
    if (!v.principal || !v.rate || !v.start) { $('#fPrev').innerHTML = 'Nhập tiền gốc & lãi suất để xem lãi dự kiến.'; return; }
    const c = calc({ ...v, owner });
    $('#fPrev').innerHTML = `Lãi mỗi ngày: <b>${vnd(c.daily)}</b><br>Lãi mỗi tháng: <b>${vnd(c.monthly)}</b>` +
      (c.total != null ? `<br>Lãi khi đáo hạn (${fmtDate(c.mat)}): <b>${vnd(c.total)}</b>` : '');
  };
  preview();

  $('#fOwner').addEventListener('click', (e) => {
    const bt = e.target.closest('button'); if (!bt) return;
    owner = bt.dataset.v;
    $('#fOwner').querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === bt));
    preview();
  });
  const showBank = () => {
    $('#fBank').innerHTML = bank
      ? `${logoHTML(bank)}<span class="pn">${esc(bank)}</span><span class="pc">Đổi ›</span>`
      : '<span class="pn" style="color:var(--mut)">Chọn ngân hàng…</span><span class="pc">›</span>';
  };
  showBank();
  $('#fBank').onclick = () => openBankPicker(bank, (v) => { bank = v; showBank(); });
  $('#fPrincipal').addEventListener('input', (e) => {
    const n = e.target.value.replace(/\D/g, '');
    e.target.value = n ? nf.format(parseInt(n, 10)) : '';
    preview();
  });
  ['#fRate', '#fTerm', '#fStart'].forEach((s) => $(s).addEventListener('input', preview));
  $('#fChips').onclick = (e) => { const c = e.target.closest('.lchip'); if (c) $('#fNote').value = c.dataset.l; };
  $('#fCancel').onclick = closeForm;
  sheet.onclick = (e) => { if (e.target === sheet) closeForm(); };
  if (b) $('#fDel').onclick = () => {
    if (confirm('Xoá sổ tiết kiệm này?')) { state.books = state.books.filter((x) => x.id !== b.id); save(); closeForm(); render(true); toast('Đã xoá sổ'); }
  };
  $('#fSave').onclick = () => {
    const v = read();
    if (!bank) return toast('Chọn ngân hàng');
    if (v.principal <= 0) return toast('Nhập tiền gốc');
    if (v.rate <= 0) return toast('Nhập lãi suất');
    if (!v.start) return toast('Chọn ngày gửi');
    const rec = { id: b ? b.id : uid(), owner, bank, principal: v.principal, rate: v.rate, term: Math.max(0, v.term), start: v.start, note: $('#fNote').value.trim() };
    if (b) state.books[state.books.findIndex((x) => x.id === b.id)] = rec; else state.books.push(rec);
    save(); closeForm();
    openBanks.add(rec.owner + '|' + rec.bank);
    if (tab !== 'all') tab = rec.owner;
    render(true); toast('Đã lưu ✓');
  };
}
function openBankPicker(current, onPick) {
  const pk = document.createElement('div');
  pk.className = 'sheet pick';
  pk.innerHTML = `<div class="panel"><div class="pk-head"><input id="pkQ" placeholder="Tìm ngân hàng (vd: vcb, techcom…)" autocomplete="off"><button type="button" class="btn ghost" id="pkX">Đóng</button></div><div id="pkList"></div></div>`;
  sheet.appendChild(pk);
  const list = pk.querySelector('#pkList'), q = pk.querySelector('#pkQ');
  const row = (b) => `<button type="button" class="pkrow ${b.n === current ? 'on' : ''}" data-n="${esc(b.n)}">${logoHTML(b.n)}<span class="pn">${esc(b.n)}${b.f ? `<small>${esc(b.f)}</small>` : ''}</span></button>`;
  const draw = () => {
    const k = normName(q.value);
    const hit = BANK_LIST.filter((b) => !k || normName(b.n + b.f + b.a.join('')).includes(k));
    let html = '', g = '';
    hit.forEach((b) => { if (b.g !== g) { g = b.g; html += `<div class="pkgrp">${esc(g)}</div>`; } html += row(b); });
    const raw = q.value.trim();
    if (raw && !BANK_LIST.some((b) => normName(b.n) === k)) html += `<button type="button" class="pkrow" data-n="${esc(raw)}"><div class="logo" style="background:${bankColor(raw)}">${esc(initials(raw))}</div><span class="pn">Dùng tên “${esc(raw)}”<small>Ngân hàng / tổ chức khác</small></span></button>`;
    list.innerHTML = html || '<div class="empty">Không tìm thấy</div>';
  };
  const close = () => pk.remove();
  q.addEventListener('input', draw);
  pk.querySelector('#pkX').onclick = close;
  pk.onclick = (e) => { if (e.target === pk) close(); };
  list.onclick = (e) => { const r = e.target.closest('.pkrow'); if (r) { onPick(r.dataset.n); close(); } };
  draw();
}

function closeForm() { sheet.hidden = true; sheet.innerHTML = ''; }

/* =====================  Cài đặt / sao lưu  ===================== */
function openSettings() {
  sheet.innerHTML = `
  <div class="panel">
    <h2>Sao lưu & cài đặt</h2>
    <label>Tên chủ sổ</label>
    <div class="row2"><input id="nVo" value="${esc(state.names.vo)}"><input id="nChong" value="${esc(state.names.chong)}"></div>
    <p style="color:var(--mut);font-size:13px;margin:14px 0 0">Dữ liệu chỉ lưu trên điện thoại này. Hãy xuất file sao lưu thỉnh thoảng (và trước khi xoá app khỏi màn hình chính) để không bị mất.</p>
    <div class="actions" style="flex-wrap:wrap">
      <button class="btn ghost" id="sExport" type="button">⬇︎ Xuất sao lưu</button>
      <button class="btn ghost" id="sImport" type="button">⬆︎ Nhập sao lưu</button>
    </div>
    <input type="file" id="sFile" accept="application/json,.json" hidden>
    <div class="actions"><button class="btn" id="sClose" type="button">Xong</button></div>
  </div>`;
  sheet.hidden = false;
  const $ = (s) => sheet.querySelector(s);
  sheet.onclick = (e) => { if (e.target === sheet) $('#sClose').click(); };
  $('#sClose').onclick = () => {
    state.names.vo = $('#nVo').value.trim() || 'Vợ';
    state.names.chong = $('#nChong').value.trim() || 'Chồng';
    save(); closeForm(); render(true);
  };
  $('#sExport').onclick = () => {
    const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `so-tiet-kiem-${iso(new Date())}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  $('#sImport').onclick = () => $('#sFile').click();
  $('#sFile').onchange = async (e) => {
    try {
      const s = JSON.parse(await e.target.files[0].text());
      if (!Array.isArray(s.books)) throw 0;
      if (!confirm(`Nhập ${s.books.length} sổ và thay thế dữ liệu hiện tại?`)) return;
      state = { ...DEFAULTS(), ...s }; save(); closeForm(); render(); toast('Đã nhập dữ liệu');
    } catch (err) { toast('File không hợp lệ'); }
  };
}

function loadDemo() {
  const t = new Date();
  const ago = (m, d = 0) => iso(new Date(t.getFullYear(), t.getMonth() - m, t.getDate() - d));
  state.books = [
    { id: uid(), owner: 'vo', bank: 'Vietcombank', principal: 300000000, rate: 4.7, term: 12, start: ago(4), note: 'Dự phòng' },
    { id: uid(), owner: 'vo', bank: 'Techcombank', principal: 500000000, rate: 5.6, term: 13, start: ago(2), note: 'Mua xe' },
    { id: uid(), owner: 'vo', bank: 'MBBank', principal: 150000000, rate: 5.2, term: 6, start: ago(6, 3), note: '' },
    { id: uid(), owner: 'chong', bank: 'BIDV', principal: 700000000, rate: 5.0, term: 12, start: ago(7), note: 'Mua nhà' },
    { id: uid(), owner: 'chong', bank: 'ACB', principal: 250000000, rate: 5.4, term: 9, start: ago(1), note: 'Mua nhà' },
    { id: uid(), owner: 'chong', bank: 'ACB', principal: 120000000, rate: 4.9, term: 6, start: ago(3), note: 'Học phí' },
  ];
  save(); render();
}

/* =====================  Sự kiện chung  ===================== */
let toastT;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove('show'), 2000);
}

document.getElementById('tabs').addEventListener('click', (e) => {
  const b = e.target.closest('[data-tab]'); if (!b) return;
  tab = b.dataset.tab; render();
});
document.getElementById('fab').addEventListener('click', () => openForm(null));
document.getElementById('navSettings').addEventListener('click', openSettings);
view.addEventListener('click', (e) => {
  const t = e.target;
  const renew = t.closest('[data-renew]');
  if (renew) {
    const b = state.books.find((x) => x.id === renew.dataset.renew);
    const c = calc(b); b.start = iso(c.mat); save(); render(true); toast('Đã tái tục ↻'); return;
  }
  const tg = t.closest('[data-toggle]');
  if (tg) {
    const bank = tg.closest('.bank'); const key = bank.dataset.key;
    bank.classList.toggle('open');
    bank.classList.contains('open') ? openBanks.add(key) : openBanks.delete(key);
    return;
  }
  const ed = t.closest('[data-edit]'); if (ed) return openForm(ed.dataset.edit);
  const go = t.closest('[data-go]'); if (go) { tab = go.dataset.go; return render(); }
  if (t.closest('[data-add]')) return openForm(null);
  if (t.closest('#btnDemo')) return loadDemo();
  const pick = t.closest('[data-pick]'); if (pick) { selMonth = pick.dataset.pick; return refreshFlow(); }
  const mode = t.closest('[data-mode]'); if (mode) { flowMode = mode.dataset.mode; return refreshFlow(); }
  const mo = t.closest('[data-month]'); if (mo) return openMonth(mo.dataset.month);
  if (t.closest('[data-bell]')) return openBell();
  if (t.closest('#btnCustom')) return openCustomize();
});

// Cập nhật lại khi qua ngày mới / mở lại app
document.addEventListener('visibilitychange', () => { if (!document.hidden && sheet.hidden) render(true); });

render();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
