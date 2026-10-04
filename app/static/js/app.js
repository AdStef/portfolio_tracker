// Shared helpers: i18n, number/currency formatting, API calls, generic forms, settings switches.
(function () {
  const T = (key) => (window.I18N && window.I18N[key]) || key;
  const locale = window.LANG === 'pl' ? 'pl-PL' : 'en-GB';
  let fx = { PLN: 1 };  // PLN per unit of currency, filled from the snapshot
  let fxWarned = false;

  function displayCcy() {
    const c = window.DISPLAY_CCY || 'PLN';
    if (c === 'PLN' || fx[c]) return c;
    if (!fxWarned) { fxWarned = true; toast(`${T('fx_unavailable')}: ${c}`, true); }
    return 'PLN';
  }

  // All amounts in snapshots are PLN; convert to the selected display currency.
  function toDisplay(pln, rate) {
    if (pln == null) return null;
    const c = displayCcy();
    const r = rate != null ? rate : (c === 'PLN' ? 1 : fx[c]);
    return pln / r;
  }

  function money(pln, { signed = false, rate = null, digits = 2 } = {}) {
    const v = toDisplay(pln, rate);
    if (v == null || Number.isNaN(v)) return '—';
    const s = new Intl.NumberFormat(locale, {
      style: 'currency', currency: displayCcy(), minimumFractionDigits: digits, maximumFractionDigits: digits,
      signDisplay: signed ? 'exceptZero' : 'auto',
    }).format(v);
    return s;
  }

  function nativeMoney(v, ccy, digits = 2) {
    if (v == null) return '—';
    return new Intl.NumberFormat(locale, { style: 'currency', currency: ccy, minimumFractionDigits: digits,
      maximumFractionDigits: Math.max(digits, 2) }).format(v);
  }

  function num(v, digits = 2) {
    if (v == null) return '—';
    return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(v);
  }

  function pct(v, { signed = true } = {}) {
    if (v == null || !Number.isFinite(v)) return '—';
    return new Intl.NumberFormat(locale, { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2,
      signDisplay: signed ? 'exceptZero' : 'auto' }).format(v);
  }

  function signClass(v) { return v > 0 ? 'txt_green' : v < 0 ? 'txt_red' : ''; }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function api(method, url, body) {
    const opts = { method, headers: {} };
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    if (!res.ok) {
      const err = new Error((data && data.errors && data.errors.join('; ')) || res.statusText);
      err.errors = (data && data.errors) || [res.statusText];
      throw err;
    }
    return data;
  }

  let toastTimer;
  function toast(msg, isError = false) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('error', isError);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 8000 : 3000);
  }

  function setCookie(name, value) {
    document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=31536000; SameSite=Lax`;
  }

  function storage(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { return null; }
    return value;
  }

  function showErrors(form, errors) {
    const ul = form.querySelector('.form_errors') || document.getElementById('form_errors');
    if (ul) ul.innerHTML = errors.map((e) => `<li>${esc(e)}</li>`).join('');
    else toast(errors.join('; '), true);
  }

  // <form data-api="/api/..." data-method="POST" [data-redirect="/x"]>: submit as JSON.
  document.addEventListener('submit', async (ev) => {
    const form = ev.target;
    if (!form.dataset.api) return;
    ev.preventDefault();
    const body = {};
    for (const [k, v] of new FormData(form).entries()) body[k] = v;
    form.querySelectorAll('input[type=checkbox][name]').forEach((cb) => { if (!cb.checked) body[cb.name] = ''; });
    form.querySelectorAll('[data-show][hidden] [name], [hidden] > [name]').forEach((el) => { delete body[el.name]; });
    const btn = form.querySelector('[type=submit]');
    if (btn) btn.disabled = true;
    try {
      await api(form.dataset.method || 'POST', form.dataset.api, body);
      showErrors(form, []);
      if (form.dataset.redirect) window.location = form.dataset.redirect;
      else { toast(T('saved')); setTimeout(() => window.location.reload(), 400); }
    } catch (e) {
      showErrors(form, e.errors || [e.message]);
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // <button data-delete="/api/..."> anywhere
  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-delete]');
    if (!btn) return;
    ev.preventDefault();
    if (!window.confirm(T('confirm_delete'))) return;
    try {
      await api('DELETE', btn.dataset.delete);
      if (btn.dataset.redirect) window.location = btn.dataset.redirect;
      else window.location.reload();
    } catch (e) { toast(e.message, true); }
  });

  // Add menu
  const addBtn = document.getElementById('add_button');
  const addMenu = document.getElementById('add_menu');
  if (addBtn && addMenu) {
    addBtn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      addMenu.hidden = !addMenu.hidden;
      addBtn.setAttribute('aria-expanded', String(!addMenu.hidden));
    });
    document.addEventListener('click', (ev) => { if (!addMenu.contains(ev.target)) addMenu.hidden = true; });
  }

  // Language & currency
  const langSel = document.getElementById('lang_switch');
  if (langSel) langSel.addEventListener('change', () => { setCookie('lang', langSel.value); window.location.reload(); });
  const ccySel = document.getElementById('ccy_switch');
  if (ccySel) ccySel.addEventListener('change', () => { setCookie('ccy', ccySel.value); window.location.reload(); });

  // Scope selector shared by dashboard & holdings
  function initScope(onChange) {
    const sel = document.getElementById('scope_select');
    if (!sel) return 'all';
    const saved = storage('scope');
    if (saved && [...sel.options].some((o) => o.value === saved)) sel.value = saved;
    sel.addEventListener('change', () => { storage('scope', sel.value); onChange(sel.value); });
    return sel.value;
  }

  async function loadSnapshot() {
    const data = await api('GET', '/api/dashboard');
    const snap = data.snapshot;
    if (snap) fx = Object.assign({ PLN: 1 }, snap.fx);
    const info = document.getElementById('snapshot_info');
    if (info && snap) {
      const at = new Date(snap.meta.computed_at).toLocaleString(locale);
      info.textContent = `${T('computed_at')}: ${at} · ${T('prices_as_of')}: ${snap.market_date || '—'}`;
    }
    const badge = document.getElementById('stale_badge');
    if (badge) badge.hidden = !(snap && data.stale);
    const empty = document.getElementById('empty_state');
    if (empty) empty.hidden = !!snap;
    return data;
  }

  // Accounts/positions belonging to a scope string: all | person:<id> | account:<id>
  function scopeAccounts(snap, scope) {
    const accounts = Object.values(snap.by_account);
    if (scope === 'all') return accounts;
    const [kind, id] = scope.split(':');
    if (kind === 'person') return accounts.filter((a) => String(a.person_id) === id);
    return accounts.filter((a) => String(a.id) === id);
  }

  function scopeTotals(snap, scope) {
    if (scope === 'all') return snap.totals;
    const [kind, id] = scope.split(':');
    if (kind === 'person') return snap.by_person[id] && snap.by_person[id].totals;
    return snap.by_account[id] && snap.by_account[id].totals;
  }

  window.PT = { T, money, nativeMoney, num, pct, signClass, esc, api, toast, storage, initScope, loadSnapshot,
    scopeAccounts, scopeTotals, displayCcy, getFx: () => fx, locale };
})();

// Instrument page: live check of saved bond parameters
(function () {
  const el = document.getElementById('bond_preview');
  if (!el) return;
  window.PT.api('GET', el.dataset.url).then((b) => {
    const { num, T } = window.PT;
    el.textContent = `${b.date}: ${num(b.value, 2)} PLN · accrued ${num(b.accrued, 2)} · ${T('fee')} ${num(b.fee, 2)} · ` +
      `#${b.period} @ ${b.rate != null ? num(b.rate, 2) + '%' : '—'} · ${b.purchase_date} → ${b.maturity}` +
      (b.warnings.length ? ` · ⚠ ${b.warnings.join(', ')}` : '');
  }).catch(() => {});
})();
