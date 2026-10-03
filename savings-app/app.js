'use strict';

/* =====================  Dữ liệu & lưu trữ  ===================== */
const KEY = 'sotietkiem.v1';
const normName = (s) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').replace(/[^a-z0-9]/g, '');
const BANK_INDEX = new Map();
BANK_LIST.forEach((b) => [b.n, ...b.a].forEach((k) => BANK_INDEX.set(normName(k), b)));
const bankInfo = (name) => BANK_INDEX.get(normName(name)) || null;
const PALETTE = ['#34d399', '#60a5fa', '#f472b6', '#fbbf24', '#a78bfa', '#fb923c', '#22d3ee', '#f87171'];

let state = load();
let tab = 'all';
const openBanks = new Set();

function load() {
  try {
    const s = JSON.parse(localStorage.getItem(KEY));
    if (s && Array.isArray(s.books)) return { names: { vo: 'Vợ', chong: 'Chồng' }, ...s };
  } catch (e) { /* ignore */ }
  return { names: { vo: 'Vợ', chong: 'Chồng' }, books: [] };
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
const fmtDate = (d) => `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ownerName = (o) => state.names[o];

function bankColor(name) {
  let h = 0; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 55% 42%)`;
}
function logoHTML(name) {
  const i = bankInfo(name);
  if (i && i.logo) return `<div class="logo has"><img src="${i.logo}" alt="${esc(name)}" loading="lazy"></div>`;
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
    countUp(el, parseFloat(el.dataset.count), kind === 'vnd' ? vnd : money);
  });
}

/* =====================  Render  ===================== */
const view = document.getElementById('view');

function render() {
  document.querySelectorAll('#tabs button').forEach((b) => {
    b.classList.toggle('on', b.dataset.tab === tab);
    if (b.dataset.tab !== 'all') b.querySelector('.nm').textContent = ownerName(b.dataset.tab);
  });
  document.getElementById('fab').style.display = 'block';
  view.innerHTML = tab === 'all' ? renderAll() : renderOwner(tab);
  view.className = 'fade-in';
  runCounters(view);
  requestAnimationFrame(() => requestAnimationFrame(() => animateDonut()));
  window.scrollTo(0, 0);
}

function heroHTML(title, sub, list) {
  const t = totals(list);
  return `
  <section class="card hero">
    <div class="lbl">${esc(sub)}</div>
    <div class="big"><span data-count="${t.principal}">0</span><small>₫</small></div>
    <div class="pair">
      <div class="chip"><div class="k">Lãi mỗi ngày</div><div class="v"><span data-count="${t.daily}">0</span> ₫</div></div>
      <div class="chip"><div class="k">Lãi mỗi tháng</div><div class="v"><span data-count="${t.monthly}">0</span> ₫</div></div>
    </div>
    <div class="live"><i class="pulse"></i><span>Hôm nay đã sinh lãi</span><b data-live="${t.daily}">0</b><span>₫</span></div>
  </section>`;
}

function donutHTML(list) {
  const byBank = {};
  list.forEach((b) => { byBank[b.bank] = (byBank[b.bank] || 0) + b.principal; });
  const rows = Object.entries(byBank).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((s, r) => s + r[1], 0);
  if (!total) return '';
  const R = 60, C = 2 * Math.PI * R;
  let cum = 0, segs = '', leg = '';
  rows.forEach(([name, val], i) => {
    const f = val / total, col = PALETTE[i % PALETTE.length];
    const len = Math.max(0, f * C - (rows.length > 1 ? 3 : 0));
    segs += `<circle class="seg" cx="80" cy="80" r="${R}" stroke="${col}" stroke-dasharray="0 ${C}" data-d="${len} ${C - len}" stroke-dashoffset="${-cum * C}" stroke-linecap="butt"/>`;
    leg += `<div><i style="background:${col}"></i><span>${esc(name)}</span><em>${Math.round(f * 100)}%</em></div>`;
    cum += f;
  });
  return `
  <section class="card">
    <h3>Phân bổ theo ngân hàng</h3>
    <div class="donut-wrap">
      <div class="donut"><svg viewBox="0 0 160 160"><circle cx="80" cy="80" r="${R}" stroke="rgba(255,255,255,.06)"/>${segs}</svg>
        <div class="ctr"><div><b>${compact(total)}</b>${rows.length} ngân hàng</div></div></div>
      <div class="legend">${leg}</div>
    </div>
  </section>`;
}
function animateDonut() {
  document.querySelectorAll('.donut .seg').forEach((c) => c.setAttribute('stroke-dasharray', c.dataset.d));
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
  <section class="card">
    <h3>Lãi dự kiến 12 tháng tới</h3>
    <div class="bars">${bars}</div>
    <div class="bar-note">Tháng này: <b style="color:var(--gold)">${vnd(items[0].v)}</b> · Cao nhất: ${vnd(max)}<br>Chưa tính tái tục các sổ đến hạn.</div>
  </section>`;
}

function upcomingHTML(list) {
  const up = list.map((b) => ({ b, c: calc(b) })).filter((x) => x.c.mat && !x.c.matured)
    .sort((a, b) => a.c.daysLeft - b.c.daysLeft).slice(0, 3);
  if (!up.length) return '';
  return `<section class="card"><h3>Sắp đến hạn</h3>${up.map(({ b, c }) => `
    <div style="display:flex;align-items:center;gap:12px;padding:6px 0">
      ${logoHTML(b.bank)}
      <div style="flex:1;min-width:0"><b>${esc(b.bank)}</b> · ${esc(ownerName(b.owner))}<div class="meta" style="font-size:12px;color:var(--mut)">${vnd(b.principal)} — ${fmtDate(c.mat)}</div></div>
      <span class="badge ${c.daysLeft <= 14 ? 'soon' : ''}">${c.daysLeft} ngày</span>
    </div>`).join('')}</section>`;
}

function renderAll() {
  const list = scoped('all');
  if (!list.length) return emptyHTML();
  const split = ['vo', 'chong'].map((o) => {
    const t = totals(scoped(o));
    return `<button class="who ${o}" data-go="${o}"><div class="n">${o === 'vo' ? '♀' : '♂'} ${esc(ownerName(o))}</div><div class="a">${compact(t.principal)}</div><div class="d">+${vnd(t.daily)}/ngày</div></button>`;
  }).join('');
  return `
  <div class="head"><div><h1>Tổng quan</h1><small>${fmtDate(new Date())}</small></div><div class="dot">💰</div></div>
  ${heroHTML('', 'Tổng tiền gửi cả nhà', list)}
  <div class="split" style="margin-bottom:14px">${split}</div>
  ${donutHTML(list)}
  ${barsHTML(list)}
  ${upcomingHTML(list)}
  <div style="text-align:center;margin-top:8px">
    <button class="btn ghost" id="btnSettings">⚙︎ Sao lưu & cài đặt</button>
  </div>`;
}

function renderOwner(o) {
  const list = scoped(o);
  const icon = o === 'vo' ? '♀' : '♂';
  const head = `<div class="head"><div><h1>Sổ ${esc(ownerName(o))}</h1><small>${list.length} sổ tiết kiệm</small></div><div class="dot" style="color:var(--${o})">${icon}</div></div>`;
  if (!list.length) return head + emptyHTML(o);

  const byBank = {};
  list.forEach((b) => (byBank[b.bank] = byBank[b.bank] || []).push(b));
  const banks = Object.entries(byBank).sort((a, b) => sum(b[1]) - sum(a[1]));
  function sum(arr) { return arr.reduce((s, x) => s + x.principal, 0); }

  const acc = banks.map(([name, arr]) => {
    const t = totals(arr);
    const key = o + '|' + name;
    return `
    <div class="bank ${openBanks.has(key) ? 'open' : ''}" data-key="${esc(key)}">
      <button class="bank-h" data-toggle>
        ${logoHTML(name)}
        <div class="mid"><div class="nm">${esc(name)}</div><div class="sub">${arr.length} sổ</div></div>
        <div class="amt">${vnd(t.principal)}<small>+${vnd(t.daily)}/ngày</small></div>
        <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
      </button>
      <div class="acc"><div><div class="books">${arr.sort((a, b) => b.principal - a.principal).map(bookHTML).join('')}</div></div></div>
    </div>`;
  }).join('');

  return `${head}
  ${heroHTML('', 'Tổng tiền gửi', list)}
  ${donutHTML(list)}
  ${barsHTML(list)}
  <div class="sec-title">Ngân hàng đang gửi</div>
  ${acc}`;
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
    <div class="r1"><span class="p">${vnd(b.principal)}</span><span class="rate">${String(b.rate).replace('.', ',')}%/năm</span></div>
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
    <label>Ghi chú (tuỳ chọn)</label>
    <input id="fNote" placeholder="vd: Sổ mua nhà" value="${esc(d.note || '')}">
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
  $('#fCancel').onclick = closeForm;
  sheet.onclick = (e) => { if (e.target === sheet) closeForm(); };
  if (b) $('#fDel').onclick = () => {
    if (confirm('Xoá sổ tiết kiệm này?')) { state.books = state.books.filter((x) => x.id !== b.id); save(); closeForm(); render(); toast('Đã xoá sổ'); }
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
    render(); toast('Đã lưu ✓');
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
    save(); closeForm(); render();
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
      state = { names: { vo: 'Vợ', chong: 'Chồng' }, ...s }; save(); closeForm(); render(); toast('Đã nhập dữ liệu');
    } catch (err) { toast('File không hợp lệ'); }
  };
}

function loadDemo() {
  const t = new Date();
  const ago = (m, d = 0) => iso(new Date(t.getFullYear(), t.getMonth() - m, t.getDate() - d));
  state.books = [
    { id: uid(), owner: 'vo', bank: 'Vietcombank', principal: 300000000, rate: 4.7, term: 12, start: ago(4), note: 'Sổ dự phòng' },
    { id: uid(), owner: 'vo', bank: 'Techcombank', principal: 500000000, rate: 5.6, term: 13, start: ago(2), note: '' },
    { id: uid(), owner: 'vo', bank: 'MBBank', principal: 150000000, rate: 5.2, term: 6, start: ago(6, 3), note: 'Đã đáo hạn' },
    { id: uid(), owner: 'chong', bank: 'BIDV', principal: 700000000, rate: 5.0, term: 12, start: ago(7), note: 'Mua nhà' },
    { id: uid(), owner: 'chong', bank: 'ACB', principal: 250000000, rate: 5.4, term: 9, start: ago(1), note: '' },
    { id: uid(), owner: 'chong', bank: 'ACB', principal: 120000000, rate: 4.9, term: 6, start: ago(3), note: 'Quỹ học phí' },
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
  const b = e.target.closest('button'); if (!b) return;
  tab = b.dataset.tab; render();
});
document.getElementById('fab').addEventListener('click', () => openForm(null));
view.addEventListener('click', (e) => {
  const t = e.target;
  const renew = t.closest('[data-renew]');
  if (renew) {
    const b = state.books.find((x) => x.id === renew.dataset.renew);
    const c = calc(b); b.start = iso(c.mat); save(); render(); toast('Đã tái tục ↻'); return;
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
  if (t.closest('#btnSettings')) return openSettings();
});

// Cập nhật lại khi qua ngày mới / mở lại app
document.addEventListener('visibilitychange', () => { if (!document.hidden && sheet.hidden) render(); });

render();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
