(function () {
  const { T, money, pct, signClass, esc, api, toast, initScope, loadSnapshot, scopeAccounts, scopeTotals } = window.PT;
  const COLORS = { gross: '#89b4fa', invested: '#fab387', grid: 'rgba(147,153,178,0.15)', text: '#a6adc8' };
  let snap = null;
  let chart = null;
  let history = null;
  let range = 'ALL';
  let scope = initScope((s) => { scope = s; render(); loadHistory(); });

  function card(key, main, sub, subClass = '') {
    const el = document.querySelector(`[data-metric="${key}"]`);
    el.querySelector('.topbar_metric_amount').textContent = main;
    el.querySelector('.topbar_metric_changes').innerHTML = sub ? `<span class="${subClass}">${sub}</span>` : '';
  }

  function render() {
    if (!snap) return;
    const t = scopeTotals(snap, scope);
    if (!t) return;
    card('gross', money(t.gross), `${money(t.day_change, { signed: true })} (${pct(t.day_change_pct)})`, signClass(t.day_change));
    card('net', money(t.net), `${T('exit_tax')}: ${money(-t.exit_tax - t.liquidation_fees)}`, 'muted');
    card('profit', money(t.profit, { signed: true }), `${pct(t.profit_pct)} · ${T('xirr')} ${pct(t.xirr, { signed: false })}`, signClass(t.profit));
    card('retirement_net', money(t.retirement_net), `${T('gross')}: ${money(t.retirement_gross)}`, 'muted');

    const people = snap.by_person;
    const rows = scopeAccounts(snap, scope).filter((a) => Math.abs(a.totals.gross) > 0.005 || Math.abs(a.totals.invested) > 0.005);
    document.querySelector('#accounts_table tbody').innerHTML = rows.map((a) => {
      const x = a.totals;
      return `<tr>
        <td>${esc(a.name)}</td><td>${esc(people[a.person_id] ? people[a.person_id].name : '')}</td><td>${esc(T('kind_' + a.kind))}</td>
        <td class="num">${money(x.gross)}</td><td class="num">${money(x.net)}</td><td class="num">${money(x.invested)}</td>
        <td class="num ${signClass(x.profit)}">${money(x.profit, { signed: true })}<span class="sub">${pct(x.profit_pct)}</span></td>
        <td class="num ${signClass(x.day_change)}">${money(x.day_change, { signed: true })}</td>
        <td class="num">${pct(x.xirr, { signed: false })}</td></tr>`;
    }).join('');

    renderAllocation();

    const warnings = snap.warnings || [];
    document.getElementById('warnings_panel').hidden = !warnings.length;
    const grouped = {};
    for (const w of warnings) {
      const what = [w.instrument, w.account, w.currency].filter(Boolean).join('/');
      (grouped[w.code] = grouped[w.code] || []).push(what + (w.detail != null ? ` (${w.detail})` : ''));
    }
    document.getElementById('warnings').innerHTML = Object.entries(grouped).map(([code, items]) =>
      `<li>${esc(T('warn_' + code))}: <span class="muted">${esc(items.filter(Boolean).join(', '))}</span></li>`).join('');
  }

  function allocationFor() {
    if (scope === 'all') return snap.allocation;
    const [kind, id] = scope.split(':');
    return kind === 'person' ? snap.by_person[id].allocation : snap.by_account[id].allocation;
  }

  function renderAllocation() {
    const alloc = allocationFor();
    const groups = [['asset_class', (k) => T('class_' + k)], ['currency', (k) => k]];
    if (alloc.account_kind) groups.push(['account_kind', (k) => T('kind_' + k)]);
    document.getElementById('allocation').innerHTML = groups.map(([dim, label]) => {
      const entries = Object.entries(alloc[dim] || {}).filter(([, v]) => Math.abs(v) > 0.005).sort((a, b) => b[1] - a[1]);
      const total = entries.reduce((s, [, v]) => s + v, 0);
      if (!entries.length || total <= 0) return '';
      const title = { asset_class: T('asset_class'), currency: T('currency'), account_kind: T('kind') }[dim];
      return `<div class="alloc_group"><h3>${esc(title)}</h3>` + entries.map(([k, v]) => {
        const share = v / total;
        return `<div class="alloc_row" title="${esc(money(v))}"><span>${esc(label(k))}</span>
          <div class="alloc_bar"><span style="width:${Math.max(0, share * 100).toFixed(2)}%"></span></div>
          <span class="num">${pct(share, { signed: false })}</span></div>`;
      }).join('') + '</div>';
    }).join('');
  }

  async function loadHistory() {
    history = await api('GET', `/api/history?scope=${encodeURIComponent(scope)}`);
    drawChart();
  }

  function rangeStart(dates) {
    if (range === 'ALL' || !dates.length) return 0;
    const end = new Date(dates[dates.length - 1]);
    const start = new Date(end);
    if (range === 'YTD') { start.setMonth(0, 1); }
    else {
      const months = { '1M': 1, '3M': 3, '1Y': 12, '3Y': 36 }[range];
      start.setMonth(start.getMonth() - months);
    }
    const iso = start.toISOString().slice(0, 10);
    const i = dates.findIndex((d) => d >= iso);
    return i < 0 ? 0 : i;
  }

  function drawChart() {
    const canvas = document.getElementById('history_chart');
    if (!history || !history.series || !history.series.gross || !window.Chart) {
      if (chart) { chart.destroy(); chart = null; }
      return;
    }
    const ccy = window.PT.displayCcy();
    const fxSeries = ccy === 'PLN' ? null : history.fx[ccy];
    const from = rangeStart(history.dates);
    const conv = (arr) => arr.slice(from).map((v, i) => (fxSeries ? v / fxSeries[i + from] : v));
    const labels = history.dates.slice(from);
    const datasets = [
      { label: T('gross'), data: conv(history.series.gross), borderColor: COLORS.gross, backgroundColor: COLORS.gross },
      { label: T('invested'), data: conv(history.series.invested), borderColor: COLORS.invested,
        backgroundColor: COLORS.invested, borderDash: [6, 4] },
    ].map((d) => Object.assign(d, { borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0 }));

    const fmt = new Intl.NumberFormat(window.PT.locale, { style: 'currency', currency: ccy, maximumFractionDigits: 0 });
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: COLORS.text, boxWidth: 14, boxHeight: 2 } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt.format(c.parsed.y)}` } },
        },
        scales: {
          x: { ticks: { color: COLORS.text, maxTicksLimit: 8, maxRotation: 0 }, grid: { display: false } },
          y: { ticks: { color: COLORS.text, callback: (v) => fmt.format(v) }, grid: { color: COLORS.grid } },
        },
      },
    });
  }

  document.getElementById('range_buttons').addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-range]');
    if (!b) return;
    range = b.dataset.range;
    document.querySelectorAll('#range_buttons button').forEach((x) => x.classList.toggle('active', x === b));
    drawChart();
  });

  async function runAction(btn, url, describe) {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = T('working');
    try {
      const res = await api('POST', url);
      toast(describe(res));
      await refresh();
    } catch (e) {
      toast(e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  document.getElementById('recalc_btn').addEventListener('click', (ev) =>
    runAction(ev.currentTarget, '/api/recalculate', (r) => `${T('computed_at')} (${r.meta.duration_ms} ms)`));
  document.getElementById('refresh_btn').addEventListener('click', (ev) =>
    runAction(ev.currentTarget, '/api/prices/refresh', (r) => {
      const rep = r.report;
      if (!rep.updated.length && !rep.failed.length) return T('no_auto_sources');
      let msg = `${T('prices_refreshed')}: ${rep.updated.length} (${rep.points})`;
      if (rep.failed.length) msg += ` · ✗ ${rep.failed.map((f) => f.symbol).join(', ')}`;
      return msg;
    }));

  async function refresh() {
    const data = await loadSnapshot();
    snap = data.snapshot;
    render();
    await loadHistory();
  }

  refresh().catch((e) => toast(e.message, true));
})();
