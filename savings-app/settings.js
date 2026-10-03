'use strict';

/* =====================  Cài đặt: trang chính + các trang con  ===================== */
const SVG = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const SI = {
  palette: SVG('<circle cx="13.5" cy="6.5" r=".6"/><circle cx="17.5" cy="10.5" r=".6"/><circle cx="8.5" cy="7.5" r=".6"/><circle cx="6.5" cy="12.5" r=".6"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.5-.7 1.5-1.5 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.8.7-1.5 1.5-1.5H16c3.3 0 6-2.7 6-6 0-4.4-4.5-8-10-8z"/>'),
  cash: SVG('<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 12h.01M18 12h.01"/>'),
  bell: SVG('<path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/>'),
  tag: SVG('<path d="M20.6 13.4l-7.2 7.2a2 2 0 01-2.8 0L2 12V2h10l8.6 8.6a2 2 0 010 2.8z"/><circle cx="7" cy="7" r="1.2"/>'),
  bank: SVG('<path d="M3 21h18M5 21V10M9 21V10M15 21V10M19 21V10M2 10l10-7 10 7z"/>'),
  users: SVG('<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8"/>'),
  up: SVG('<path d="M16 16l-4-4-4 4M12 12v9"/><path d="M20.4 18.4A5 5 0 0018 9h-1.3A8 8 0 104 16.3"/>'),
  history: SVG('<path d="M3 12a9 9 0 109-9 9.7 9.7 0 00-6.7 2.7L3 8"/><path d="M3 3v5h5M12 7v5l4 2"/>'),
  key: SVG('<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2M17 6l3 3M14 9l2 2"/>'),
  cal: SVG('<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>'),
  search: SVG('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>'),
  trash: ICON.trash,
};
const CHECK = '<svg class="ck" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5 9-10"/></svg>';
const clone = (o) => JSON.parse(JSON.stringify(o));
const THEME_NAME = { dark: 'Tối', light: 'Sáng', auto: 'Tự động' };

function renderSettings() {
  const s = state.settings;
  const row = (id, icon, label, val) => `<button class="srow" data-set="${id}"><span class="si">${SI[icon]}</span><span class="sl">${label}</span><span class="sval">${val || ''}</span>${ICON.chev}</button>`;
  const grp = (title, rows) => `<div class="sgrp">${title}</div><div class="scard">${rows.join('')}</div>`;
  const supported = 'Notification' in window;
  const notifTxt = s.notif.on && supported && Notification.permission === 'granted' ? 'Bật' : 'Tắt';
  const backup = s.lastBackup ? fmtDate(new Date(s.lastBackup)) : 'Chưa sao lưu';
  return `
  <div class="head"><div><h1>Cài đặt</h1></div></div>
  ${grp('Hiển thị', [
    row('theme', 'palette', 'Giao diện', THEME_NAME[s.theme]),
    row('format', 'cash', 'Định dạng tiền', sv(1000000)),
  ])}
  ${grp('Thông báo', [row('notif', 'bell', 'Thông báo', notifTxt)])}
  ${grp('Danh mục', [
    row('labels', 'tag', 'Nhãn', allLabels().length || ''),
    row('banks', 'bank', 'Ngân hàng', ''),
    row('owners', 'users', 'Tên chủ sổ', `${esc(state.names.vo)} · ${esc(state.names.chong)}`),
  ])}
  ${grp('Dữ liệu &amp; bảo mật', [
    row('backup', 'up', 'Sao lưu dữ liệu', backup),
    row('restore', 'history', 'Khôi phục dữ liệu', ''),
    row('lock', 'key', 'Khóa ứng dụng', s.lock.on ? 'Bật' : 'Tắt'),
  ])}
  <p class="muted" style="text-align:center;margin:18px 0 0">Sổ Tiết Kiệm · dữ liệu chỉ lưu trên điện thoại này</p>`;
}

function openSetting(id) {
  ({ theme: pickTheme, format: pageFormat, notif: pageNotif, labels: pageLabels, banks: pageBanks, owners: pageOwners, backup: pageBackup, restore: pageRestore, lock: pageLock })[id]();
}

/* ---- khung dùng chung ---- */
function openPage(title, body, { footer = '', right = '', mount } = {}) {
  sheet.className = 'sheet full';
  sheet.innerHTML = `<div class="panel full" role="dialog">
    <div class="dt-head"><button type="button" class="dt-back" id="pgBack" aria-label="Quay lại">${ICON.chev}</button><h2>${title}</h2>${right || '<span class="dt-sp"></span>'}</div>
    <div class="dt-body" id="pgBody">${body}</div>${footer ? `<div class="dt-foot">${footer}</div>` : ''}</div>`;
  sheet.hidden = false; sheet.onclick = null; sheet.onchange = null;
  const close = () => { closeForm(); if (tab === 'settings') render(true); };
  sheet.querySelector('#pgBack').onclick = close;
  if (mount) mount(sheet.querySelector('.panel'), close);
  return close;
}

function popup(html, mount) {
  const el = document.createElement('div');
  el.className = 'sheet pop';
  el.innerHTML = `<div class="panel">${html}</div>`;
  document.body.appendChild(el);
  const close = () => el.remove();
  el.addEventListener('click', (e) => { if (e.target === el) close(); });
  if (mount) mount(el, close);
  return close;
}

function choose(title, options, current, onPick) {
  popup(`<div class="pop-h"><h3>${esc(title)}</h3><button type="button" class="pop-x" aria-label="Đóng">✕</button></div>
    ${options.map((o) => `<button type="button" class="opt" data-v="${esc(String(o.v))}"><span>${esc(o.label)}${o.sub ? `<small>${esc(o.sub)}</small>` : ''}</span>${String(o.v) === String(current) ? CHECK : ''}</button>`).join('')}`,
  (el, close) => {
    el.querySelector('.pop-x').onclick = close;
    el.querySelectorAll('.opt').forEach((b) => { b.onclick = () => { const o = options.find((x) => String(x.v) === b.dataset.v); close(); onPick(o.v); }; });
  });
}

const tg = (key, on) => `<button type="button" class="tg ${on ? 'on' : ''}" role="switch" aria-checked="${on}" data-tg="${key}"></button>`;

/* ---- giao diện ---- */
function pickTheme() {
  choose('Giao diện', [{ v: 'light', label: 'Sáng' }, { v: 'dark', label: 'Tối' }, { v: 'auto', label: 'Tự động', sub: 'Theo hệ thống' }], state.settings.theme, (v) => {
    state.settings.theme = v; save(); applyTheme(); render(true);
  });
}

/* ---- định dạng tiền ---- */
function pageFormat() {
  const defaults = DEFAULTS().settings.fmt;
  let d = clone(state.settings.fmt);
  const opts = {
    sym: { title: 'Ký hiệu tiền tệ', list: [{ v: '₫', label: '₫' }, { v: 'đ', label: 'đ' }, { v: 'VND', label: 'VND' }, { v: 'none', label: 'Không hiển thị' }], show: (v) => (v === 'none' ? 'Không' : v) },
    pos: { title: 'Vị trí ký hiệu', list: [{ v: 'after', label: 'Sau số tiền' }, { v: 'before', label: 'Trước số tiền' }], show: (v) => (v === 'after' ? 'Sau số tiền' : 'Trước số tiền') },
    space: { title: 'Khoảng cách', list: [{ v: 'true', label: 'Có' }, { v: 'false', label: 'Không' }], show: (v) => (v ? 'Có' : 'Không') },
    sep: { title: 'Dấu phân cách', list: [{ v: 'dot', label: '1.000.000' }, { v: 'comma', label: '1,000,000' }, { v: 'space', label: '1 000 000' }, { v: 'none', label: '1000000' }], show: (v) => ({ dot: '1.000.000', comma: '1,000,000', space: '1 000 000', none: '1000000' })[v] },
    display: { title: 'Hiển thị số tiền', list: [{ v: 'short', label: 'Rút gọn', sub: '1,25 tỷ' }, { v: 'full', label: 'Đầy đủ', sub: '1.250.000.000' }], show: (v) => (v === 'short' ? 'Rút gọn' : 'Đầy đủ') },
    neg: { title: 'Số âm', list: [{ v: 'minus', label: 'Dấu trừ (-)' }, { v: 'paren', label: 'Ngoặc (1.000)' }], show: (v) => (v === 'minus' ? 'Dấu trừ (-)' : 'Ngoặc (1.000)') },
  };
  const icons = { sym: 'cash', pos: 'cash', space: 'cash', sep: 'cash', display: 'cash', neg: 'cash' };
  const withFmt = (fmt, fn) => { const old = F; F = fmt; try { return fn(); } finally { F = old; } };
  const dirty = () => JSON.stringify(d) !== JSON.stringify(state.settings.fmt);
  const body = () => `
    <div class="card pvcard"><div class="muted">Xem trước</div><div class="pv">${withFmt(d, () => sv(1250000000))}</div>
      <div class="muted small">${withFmt(d, () => vnd(-1250000))} · ${withFmt(d, () => vnd(35000000))}</div>
      <div class="muted small">Số tiền sẽ hiển thị theo định dạng này trong toàn ứng dụng.</div></div>
    <div class="sgrp">Định dạng</div>
    <div class="scard">${Object.entries(opts).map(([k, o]) => `<button class="srow" data-opt="${k}"><span class="si">${SI[icons[k]]}</span><span class="sl">${o.title}</span><span class="sval">${esc(o.show(d[k]))}</span>${ICON.chev}</button>`).join('')}</div>`;
  openPage('Định dạng tiền', body(), {
    footer: '<button type="button" class="btn ghost" id="fReset">Đặt lại</button><button type="button" class="dt-edit" id="fSaveF" disabled>Lưu thay đổi</button>',
    mount: (panel, close) => {
      const redraw = () => { panel.querySelector('#pgBody').innerHTML = body(); panel.querySelector('#fSaveF').disabled = !dirty(); };
      panel.querySelector('#pgBody').onclick = (e) => {
        const r = e.target.closest('[data-opt]'); if (!r) return;
        const k = r.dataset.opt, o = opts[k];
        choose(o.title, o.list, String(d[k]), (v) => { d[k] = k === 'space' ? v === 'true' : v; redraw(); });
      };
      panel.querySelector('#fReset').onclick = () => { d = clone(defaults); redraw(); };
      panel.querySelector('#fSaveF').onclick = () => { state.settings.fmt = clone(d); refreshFmt(); save(); close(); toast('Đã lưu định dạng'); };
    },
  });
}

/* ---- thông báo ---- */
const NOTIF_KEY = 'sotietkiem.notified';
function notifyState() {
  try { return JSON.parse(localStorage.getItem(NOTIF_KEY)) || {}; } catch (e) { return {}; }
}
// Hiện thông báo hệ thống cho sổ sắp/đang đáo hạn — chỉ chạy được khi app đang mở.
function checkNotify() {
  const n = state.settings.notif;
  if (!n.on || !('Notification' in window) || Notification.permission !== 'granted') return;
  const now = new Date();
  const [hh, mm] = n.time.split(':').map(Number);
  if (now.getHours() * 60 + now.getMinutes() < hh * 60 + mm) return;
  const done = notifyState(), today = iso(now);
  state.books.forEach((b) => {
    const c = calc(b);
    if (!c.mat) return;
    const left = diffDays(today0(), c.mat);
    let type = null;
    if (n.onDay && left === 0) type = 'day';
    else if (n.before && left === n.days) type = 'before';
    if (!type) return;
    const key = `${b.id}|${type}|${today}`;
    if (done[key]) return;
    done[key] = 1;
    const title = type === 'day' ? 'Sổ tiết kiệm đến hạn hôm nay' : `Sổ tiết kiệm còn ${n.days} ngày đáo hạn`;
    const body = `${b.bank} · ${ownerName(b.owner)} · gốc ${sv(b.principal)} + lãi ${sv(c.total)}`;
    const show = (reg) => (reg ? reg.showNotification(title, { body, icon: 'icons/icon-192.png', tag: key }) : new Notification(title, { body }));
    if (navigator.serviceWorker && navigator.serviceWorker.ready) navigator.serviceWorker.ready.then(show).catch(() => show(null)); else show(null);
  });
  try { localStorage.setItem(NOTIF_KEY, JSON.stringify(done)); } catch (e) { /* ignore */ }
}

function icsText(s) { return String(s).replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/,/g, '\\,').replace(/;/g, '\\;'); }
function buildICS() {
  const n = state.settings.notif, [hh, mm] = n.time.split(':');
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '');
  const out = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//SoTietKiem//VI', 'CALSCALE:GREGORIAN'];
  let count = 0;
  state.books.forEach((b) => {
    const c = calc(b);
    if (!c.mat || c.mat < today0()) return;
    const d = `${c.mat.getFullYear()}${String(c.mat.getMonth() + 1).padStart(2, '0')}${String(c.mat.getDate()).padStart(2, '0')}T${hh}${mm}00`;
    out.push('BEGIN:VEVENT', `UID:${b.id}@sotietkiem`, `DTSTAMP:${stamp}`, `DTSTART:${d}`, 'DURATION:PT30M',
      `SUMMARY:${icsText(`Đáo hạn sổ ${b.bank} (${ownerName(b.owner)})`)}`,
      `DESCRIPTION:${icsText(`Gốc ${vnd(b.principal)} + lãi ${vnd(c.total)}`)}`);
    if (n.before) out.push('BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:Sổ tiết kiệm sắp đáo hạn', `TRIGGER:-P${n.days}D`, 'END:VALARM');
    if (n.onDay) out.push('BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:Sổ tiết kiệm đáo hạn hôm nay', 'TRIGGER:PT0S', 'END:VALARM');
    out.push('END:VEVENT'); count++;
  });
  out.push('END:VCALENDAR');
  return { text: out.join('\r\n'), count };
}
function downloadFile(name, type, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function pageNotif() {
  let d = clone(state.settings.notif);
  const dirty = () => JSON.stringify(d) !== JSON.stringify(state.settings.notif);
  const supported = 'Notification' in window;
  const perm = supported ? Notification.permission : 'unsupported';
  const body = () => {
    const granted = supported && Notification.permission === 'granted';
    let head;
    if (!supported) head = '<div class="ct">Thiết bị chưa hỗ trợ</div><p class="muted">Trình duyệt này không hỗ trợ thông báo. Hãy dùng lịch nhắc ở bên dưới.</p>';
    else if (perm === 'denied' && !granted) head = '<div class="ct">Thông báo đang bị chặn</div><p class="muted">Hãy bật lại thông báo cho ứng dụng trong Cài đặt của iPhone.</p>';
    else if (d.on && granted) head = '<div class="ct">Thông báo đang bật</div><p class="muted">Ứng dụng sẽ nhắc về ngày đáo hạn khi bạn mở app.</p><button type="button" class="lnk" id="nOff">Tắt thông báo</button>';
    else head = '<div class="ct">Thông báo đang tắt</div><p class="muted">Cho phép thông báo để nhận nhắc nhở về ngày đáo hạn.</p><button type="button" class="lnk" id="nOn">Cho phép thông báo</button>';
    return `
    <div class="card">${head}</div>
    <div class="card">
      <div class="ct up">Sổ đáo hạn</div><p class="muted" style="margin:2px 0 4px">Chọn thời điểm nhắc cho ngày đáo hạn.</p>
      <div class="trow"><span>Báo trước ngày đáo hạn</span>${tg('before', d.before)}</div>
      ${d.before ? `<button type="button" class="trow sel" id="nDays"><span class="mut">Báo trước</span><b>${d.days} ngày</b>${ICON.chev}</button>` : ''}
      <div class="trow"><span>Báo vào ngày đáo hạn</span>${tg('onDay', d.onDay)}</div>
    </div>
    <div class="card">
      <div class="ct up">Thời gian</div>
      <div class="trow"><span>Giờ nhắc</span><input type="time" id="nTime" value="${d.time}"></div>
    </div>
    <div class="card">
      <div class="ct up">Lịch iPhone</div>
      <p class="muted" style="margin:2px 0 10px">iPhone không cho ứng dụng web tự gửi thông báo khi đã đóng app. Để được nhắc đúng giờ, hãy xuất lịch nhắc và thêm vào Lịch của iPhone.</p>
      <button type="button" class="btn ghost" id="nIcs" style="margin:0;width:100%">${SI.cal.replace('<svg', '<svg class="inl"')} Xuất lịch nhắc đáo hạn (.ics)</button>
    </div>`;
  };
  openPage('Cài đặt thông báo', body(), {
    footer: '<button type="button" class="dt-edit" id="nSave" disabled>Lưu cài đặt</button>',
    mount: (panel, close) => {
      const redraw = () => { panel.querySelector('#pgBody').innerHTML = body(); panel.querySelector('#nSave').disabled = !dirty(); };
      const bodyEl = panel.querySelector('#pgBody');
      bodyEl.onclick = (e) => {
        const t = e.target.closest('button'); if (!t) return;
        if (t.dataset.tg) { d[t.dataset.tg] = !d[t.dataset.tg]; return redraw(); }
        if (t.id === 'nDays') return choose('Báo trước', [1, 2, 3, 5, 7, 14, 30].map((v) => ({ v, label: v + ' ngày' })), d.days, (v) => { d.days = v; redraw(); });
        if (t.id === 'nOff') { d.on = false; return redraw(); }
        if (t.id === 'nOn') {
          return Notification.requestPermission().then((p) => { if (p === 'granted') d.on = true; else toast('Chưa được cấp quyền thông báo'); redraw(); });
        }
        if (t.id === 'nIcs') {
          const { text, count } = buildICS();
          if (!count) return toast('Chưa có sổ nào sắp đáo hạn');
          downloadFile('dao-han-so-tiet-kiem.ics', 'text/calendar', text); toast(`Đã xuất ${count} lịch nhắc`);
        }
      };
      bodyEl.onchange = (e) => { if (e.target.id === 'nTime' && e.target.value) { d.time = e.target.value; panel.querySelector('#nSave').disabled = !dirty(); } };
      panel.querySelector('#nSave').onclick = () => { state.settings.notif = clone(d); save(); close(); toast('Đã lưu cài đặt'); checkNotify(); };
    },
  });
}

/* ---- nhãn ---- */
function pageLabels() {
  let q = '';
  const counts = () => { const m = {}; state.books.forEach((b) => { if (b.note) m[b.note] = (m[b.note] || 0) + 1; }); return m; };
  const list = () => {
    const c = counts(), k = normName(q);
    const items = allLabels().filter((l) => !k || normName(l.name).includes(k));
    return items.length ? items.map((l) => `<button type="button" class="lrow" data-l="${esc(l.name)}"><i class="d" style="background:${l.color}"></i><span>${esc(l.name)}</span><small>${c[l.name] ? c[l.name] + ' sổ' : ''}</small></button>`).join('')
      : `<div class="empty"><div class="e">🏷️</div><p>${q ? 'Không tìm thấy nhãn' : 'Chưa có nhãn nào. Bấm + để tạo nhãn, ví dụ “Mua nhà”.'}</p></div>`;
  };
  openPage('Nhãn', `<div id="lbSearch" class="lsearch" hidden><input id="lbQ" placeholder="Tìm nhãn…" autocomplete="off"></div><div id="lbList">${list()}</div><button type="button" class="pgfab" id="lbAdd" aria-label="Thêm nhãn">+</button>`, {
    right: `<button type="button" class="dt-back" id="lbS" aria-label="Tìm kiếm">${SI.search}</button>`,
    mount: (panel) => {
      const redraw = () => { panel.querySelector('#lbList').innerHTML = list(); };
      panel.querySelector('#lbS').onclick = () => { const s = panel.querySelector('#lbSearch'); s.hidden = !s.hidden; if (!s.hidden) panel.querySelector('#lbQ').focus(); };
      panel.querySelector('#lbQ').oninput = (e) => { q = e.target.value; redraw(); };
      panel.querySelector('#lbList').onclick = (e) => { const r = e.target.closest('[data-l]'); if (r) editLabel(r.dataset.l, redraw); };
      panel.querySelector('#lbAdd').onclick = () => editLabel(null, redraw);
    },
  });
}

function editLabel(name, done) {
  const cur = name ? allLabels().find((l) => l.name === name) : null;
  let color = cur ? cur.color : LABEL_COLORS[allLabels().length % LABEL_COLORS.length];
  popup(`<h3 style="margin:0 0 6px">${cur ? 'Sửa nhãn' : 'Thêm nhãn'}</h3>
    <label>Tên nhãn</label><input id="lbName" value="${esc(name || '')}" placeholder="vd: Mua nhà" maxlength="30">
    <label>Màu</label><div class="swatches">${LABEL_COLORS.map((c) => `<button type="button" class="sw-c ${c === color ? 'on' : ''}" data-c="${c}" style="background:${c}" aria-label="Màu ${c}"></button>`).join('')}</div>
    <div class="actions">${cur ? '<button type="button" class="btn danger" id="lbDel">Xoá</button>' : ''}<button type="button" class="btn ghost" id="lbX">Huỷ</button><button type="button" class="btn" id="lbOk">Lưu</button></div>`,
  (el, close) => {
    el.querySelector('.swatches').onclick = (e) => { const c = e.target.closest('[data-c]'); if (!c) return; color = c.dataset.c; el.querySelectorAll('.sw-c').forEach((x) => x.classList.toggle('on', x === c)); };
    el.querySelector('#lbX').onclick = close;
    if (cur) el.querySelector('#lbDel').onclick = () => {
      if (!confirm(`Xoá nhãn “${name}”? Các sổ đang dùng nhãn này sẽ không còn nhãn.`)) return;
      state.labels = state.labels.filter((l) => l.name !== name);
      state.books.forEach((b) => { if (b.note === name) b.note = ''; });
      save(); close(); done(); toast('Đã xoá nhãn');
    };
    el.querySelector('#lbOk').onclick = () => {
      const nn = el.querySelector('#lbName').value.trim();
      if (!nn) return toast('Nhập tên nhãn');
      if (nn !== name && allLabels().some((l) => normName(l.name) === normName(nn))) return toast('Nhãn này đã tồn tại');
      if (cur) { state.books.forEach((b) => { if (b.note === name) b.note = nn; }); state.labels = state.labels.filter((l) => l.name !== name); }
      state.labels.push({ name: nn, color });
      save(); close(); done(); toast('Đã lưu nhãn');
    };
  });
}

/* ---- ngân hàng ---- */
function pageBanks() {
  let q = '';
  const used = () => { const m = {}; state.books.forEach((b) => { m[b.bank] = (m[b.bank] || 0) + 1; }); return m; };
  const list = () => {
    const u = used(), k = normName(q), hide = new Set(state.hiddenBanks);
    const mine = state.customBanks.map((n) => ({ n, custom: true }));
    const rows = [...mine, ...BANK_LIST.map((b) => ({ n: b.n, f: b.f }))].filter((b) => !k || normName(b.n + (b.f || '')).includes(k));
    return rows.map((b) => `<div class="brow">${logoHTML(b.n)}<div class="bt"><b>${esc(b.n)}</b><span>${u[b.n] ? u[b.n] + ' sổ đang gửi' : (b.custom ? 'Ngân hàng của tôi' : '')}</span></div>
      ${b.custom ? `<button type="button" class="dt-del sm" data-del="${esc(b.n)}" aria-label="Xoá">${SI.trash}</button>` : tg('hb:' + b.n, !hide.has(b.n))}</div>`).join('') || '<div class="empty"><p>Không tìm thấy ngân hàng</p></div>';
  };
  openPage('Ngân hàng', `<p class="muted" style="margin:0 0 10px">Bật các ngân hàng muốn hiện trong danh sách chọn khi thêm sổ.</p><div class="lsearch"><input id="bkQ" placeholder="Tìm ngân hàng…" autocomplete="off"></div><div id="bkList">${list()}</div><button type="button" class="pgfab" id="bkAdd" aria-label="Thêm ngân hàng">+</button>`, {
    mount: (panel) => {
      const redraw = () => { panel.querySelector('#bkList').innerHTML = list(); };
      panel.querySelector('#bkQ').oninput = (e) => { q = e.target.value; redraw(); };
      panel.querySelector('#bkList').onclick = (e) => {
        const t = e.target.closest('button'); if (!t) return;
        if (t.dataset.tg && t.dataset.tg.startsWith('hb:')) {
          const n = t.dataset.tg.slice(3), hidden = state.hiddenBanks.includes(n);
          state.hiddenBanks = hidden ? state.hiddenBanks.filter((x) => x !== n) : [...state.hiddenBanks, n]; save(); redraw();
        } else if (t.dataset.del) {
          if (state.books.some((b) => b.bank === t.dataset.del)) return toast('Đang có sổ gửi ở ngân hàng này');
          state.customBanks = state.customBanks.filter((x) => x !== t.dataset.del); save(); redraw();
        }
      };
      panel.querySelector('#bkAdd').onclick = () => popup(`<h3 style="margin:0 0 6px">Thêm ngân hàng</h3><label>Tên ngân hàng / tổ chức</label><input id="bkName" maxlength="40" placeholder="vd: Quỹ tín dụng ABC">
        <div class="actions"><button type="button" class="btn ghost" id="bkX">Huỷ</button><button type="button" class="btn" id="bkOk">Thêm</button></div>`, (el, close) => {
        el.querySelector('#bkX').onclick = close;
        el.querySelector('#bkOk').onclick = () => {
          const n = el.querySelector('#bkName').value.trim();
          if (!n) return toast('Nhập tên ngân hàng');
          if (bankInfo(n) || state.customBanks.some((x) => normName(x) === normName(n))) return toast('Ngân hàng này đã có');
          state.customBanks.push(n); save(); close(); redraw();
        };
      });
    },
  });
}

/* ---- tên chủ sổ ---- */
function pageOwners() {
  openPage('Tên chủ sổ', `<div class="card"><label class="fl">Chủ sổ thứ nhất</label><input id="oVo" value="${esc(state.names.vo)}" maxlength="20">
    <label class="fl">Chủ sổ thứ hai</label><input id="oChong" value="${esc(state.names.chong)}" maxlength="20"></div>`, {
    footer: '<button type="button" class="dt-edit" id="oSave">Lưu thay đổi</button>',
    mount: (panel, close) => {
      panel.querySelector('#oSave').onclick = () => {
        state.names.vo = panel.querySelector('#oVo').value.trim() || 'Vợ';
        state.names.chong = panel.querySelector('#oChong').value.trim() || 'Chồng';
        save(); close(); toast('Đã lưu');
      };
    },
  });
}

/* ---- sao lưu / khôi phục ---- */
const exportJSON = () => JSON.stringify(state, null, 2);
function pageBackup() {
  const when = state.settings.lastBackup ? fmtDate(new Date(state.settings.lastBackup)) : 'chưa sao lưu lần nào';
  openPage('Sao lưu dữ liệu', `
    <div class="card"><div class="ct">Dữ liệu hiện có</div>
      <div class="dt-row"><span>Số sổ tiết kiệm</span><b>${state.books.length}</b></div>
      <div class="dt-row"><span>Nhãn</span><b>${allLabels().length}</b></div>
      <div class="dt-row"><span>Lần sao lưu gần nhất</span><b>${when}</b></div></div>
    <p class="muted">Dữ liệu chỉ lưu trên điện thoại này. Hãy sao lưu thỉnh thoảng, nhất là trước khi xoá app khỏi màn hình chính hoặc đổi điện thoại.</p>
    <button type="button" class="btn" id="bFile" style="width:100%;margin:6px 0">⬇︎ Xuất file sao lưu (.json)</button>
    <button type="button" class="btn ghost" id="bCopy" style="width:100%;margin:6px 0">Sao chép dữ liệu (dán vào Ghi chú)</button>`, {
    mount: (panel, close) => {
      const mark = () => { state.settings.lastBackup = new Date().toISOString(); save(); };
      panel.querySelector('#bFile').onclick = () => { downloadFile(`so-tiet-kiem-${iso(new Date())}.json`, 'application/json', exportJSON()); mark(); toast('Đã xuất file sao lưu'); };
      panel.querySelector('#bCopy').onclick = () => {
        const done = () => { mark(); toast('Đã sao chép dữ liệu'); };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(exportJSON()).then(done).catch(() => toast('Không sao chép được')); else toast('Không sao chép được');
      };
    },
  });
}

function restoreFrom(text, close) {
  let s;
  try { s = JSON.parse(text); if (!s || !Array.isArray(s.books)) throw 0; } catch (e) { return toast('Dữ liệu không hợp lệ'); }
  if (!confirm(`Khôi phục ${s.books.length} sổ và thay thế toàn bộ dữ liệu hiện tại?`)) return;
  const keepLock = state.settings.lock;
  state = normalize(s); state.settings.lock = keepLock;
  refreshFmt(); applyTheme(); save(); close(); toast('Đã khôi phục dữ liệu');
}
function pageRestore() {
  openPage('Khôi phục dữ liệu', `
    <p class="muted" style="margin-top:0">Chọn file sao lưu (.json) hoặc dán nội dung đã sao chép. Dữ liệu hiện tại sẽ bị thay thế.</p>
    <button type="button" class="btn ghost" id="rPick" style="width:100%;margin:6px 0">Chọn file sao lưu…</button>
    <input type="file" id="rFile" accept="application/json,.json" hidden>
    <label class="fl">Hoặc dán dữ liệu</label><textarea id="rText" rows="6" placeholder='{"books": [...]}'></textarea>
    <button type="button" class="btn" id="rGo" style="width:100%;margin:10px 0 0">Khôi phục từ nội dung đã dán</button>`, {
    mount: (panel, close) => {
      panel.querySelector('#rPick').onclick = () => panel.querySelector('#rFile').click();
      panel.querySelector('#rFile').onchange = async (e) => { if (e.target.files[0]) restoreFrom(await e.target.files[0].text(), close); };
      panel.querySelector('#rGo').onclick = () => restoreFrom(panel.querySelector('#rText').value, close);
    },
  });
}

/* ---- khóa ứng dụng (mã PIN) ---- */
async function pinHash(pin, salt) {
  try {
    const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(salt + ':' + pin));
    return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, '0')).join('');
  } catch (e) { let h = 5381; for (const c of salt + pin) h = ((h << 5) + h + c.charCodeAt(0)) >>> 0; return 'x' + h; }
}
// Bàn phím nhập PIN 4 số. Trả về Promise<string|null> (null = huỷ)
function askPin(title, sub, { cancel = true, lockscreen = false } = {}) {
  return new Promise((resolve) => {
    const el = document.createElement('div');
    el.className = 'pinov' + (lockscreen ? ' lockscreen' : '');
    let v = '';
    const draw = () => {
      el.innerHTML = `<div class="pinbox"><div class="pin-ic">${SI.key}</div><h2>${esc(title)}</h2><p class="muted">${esc(sub || '')}</p>
        <div class="dots">${[0, 1, 2, 3].map((i) => `<i class="${i < v.length ? 'on' : ''}"></i>`).join('')}</div>
        <div class="pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<button type="button" data-k="${n}">${n}</button>`).join('')}
          ${cancel ? '<button type="button" data-k="x" class="aux">Huỷ</button>' : '<span></span>'}<button type="button" data-k="0">0</button><button type="button" data-k="d" class="aux" aria-label="Xoá">⌫</button></div></div>`;
    };
    draw();
    el.onclick = (e) => {
      const k = e.target.closest('[data-k]'); if (!k) return;
      const x = k.dataset.k;
      if (x === 'x') { el.remove(); return resolve(null); }
      if (x === 'd') v = v.slice(0, -1); else if (v.length < 4) v += x;
      draw();
      if (v.length === 4) { const out = v; setTimeout(() => { el.remove(); resolve(out); }, 120); }
    };
    document.body.appendChild(el);
  });
}

let locked = false;
async function lockNow() {
  const L = state.settings.lock;
  if (!L.on || locked) return;
  locked = true;
  let msg = 'Nhập mã PIN để mở ứng dụng';
  for (;;) {
    const pin = await askPin('Ứng dụng đã khóa', msg, { cancel: false, lockscreen: true });
    if (pin && (await pinHash(pin, L.salt)) === L.hash) break;
    msg = 'Mã PIN không đúng, thử lại';
  }
  locked = false;
}

async function setNewPin() {
  const a = await askPin('Đặt mã PIN', 'Nhập mã gồm 4 số'); if (a == null) return false;
  const b = await askPin('Nhập lại mã PIN', 'Để xác nhận'); if (b == null) return false;
  if (a !== b) { toast('Hai mã PIN không khớp'); return false; }
  const salt = uid() + uid();
  state.settings.lock = { ...state.settings.lock, on: true, salt, hash: await pinHash(a, salt) };
  save(); return true;
}
async function verifyPin(why) {
  const L = state.settings.lock;
  const p = await askPin('Nhập mã PIN hiện tại', why); if (p == null) return false;
  if ((await pinHash(p, L.salt)) !== L.hash) { toast('Mã PIN không đúng'); return false; }
  return true;
}

function pageLock() {
  const delayName = (s) => (s === 0 ? 'Ngay lập tức' : s < 3600 ? s / 60 + ' phút' : s / 3600 + ' giờ');
  const body = () => {
    const L = state.settings.lock;
    return L.on
      ? `<div class="card"><div class="ct">Khóa ứng dụng đang bật</div><p class="muted">Cần nhập mã PIN mỗi khi mở lại ứng dụng. Mã PIN chỉ che màn hình, không mã hoá dữ liệu.</p></div>
         <div class="scard"><button class="srow" data-a="delay"><span class="si">${SI.history}</span><span class="sl">Tự khóa sau</span><span class="sval">${delayName(L.delay)}</span>${ICON.chev}</button>
         <button class="srow" data-a="change"><span class="si">${SI.key}</span><span class="sl">Đổi mã PIN</span><span class="sval"></span>${ICON.chev}</button></div>
         <button type="button" class="btn danger" data-a="off" style="width:100%;margin-top:14px">Tắt khóa ứng dụng</button>`
      : `<div class="card"><div class="ct">Khóa ứng dụng đang tắt</div><p class="muted">Đặt mã PIN 4 số để chỉ người trong gia đình mới mở được ứng dụng.</p></div>
         <button type="button" class="btn" data-a="on" style="width:100%;margin:0">Bật khóa &amp; đặt mã PIN</button>`;
  };
  openPage('Khóa ứng dụng', body(), {
    mount: (panel) => {
      const redraw = () => { panel.querySelector('#pgBody').innerHTML = body(); };
      panel.querySelector('#pgBody').onclick = async (e) => {
        const b = e.target.closest('[data-a]'); if (!b) return;
        const a = b.dataset.a;
        if (a === 'on') { if (await setNewPin()) { redraw(); toast('Đã bật khóa ứng dụng'); } }
        else if (a === 'change') { if (await verifyPin('Để đổi mã PIN') && await setNewPin()) toast('Đã đổi mã PIN'); }
        else if (a === 'off') { if (await verifyPin('Để tắt khóa ứng dụng')) { state.settings.lock = { ...state.settings.lock, on: false, hash: '', salt: '' }; save(); redraw(); toast('Đã tắt khóa'); } }
        else if (a === 'delay') choose('Tự khóa sau', [0, 60, 300, 900].map((s) => ({ v: s, label: delayName(s) })), state.settings.lock.delay, (v) => { state.settings.lock.delay = v; save(); redraw(); });
      };
    },
  });
}

/* ---- khởi động ---- */
let hiddenAt = 0;
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { hiddenAt = Date.now(); return; }
  const L = state.settings.lock;
  if (L.on && hiddenAt && Date.now() - hiddenAt >= L.delay * 1000) lockNow();
  checkNotify();
});
lockNow();
checkNotify();
