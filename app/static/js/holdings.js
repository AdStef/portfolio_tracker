(function () {
  const { T, money, nativeMoney, num, pct, signClass, esc, toast, initScope, loadSnapshot, scopeAccounts } = window.PT;
  let snap = null;
  let scope = initScope((s) => { scope = s; render(); });

  function render() {
    if (!snap) return;
    const accounts = scopeAccounts(snap, scope);
    const rows = [];
    for (const a of accounts) {
      for (const p of a.positions) rows.push({ ...p, account: a.name });
      for (const [ccy, amount] of Object.entries(a.cash || {})) {
        rows.push({ cash: true, symbol: `${T('cash')} ${ccy}`, currency: ccy, account: a.name, quantity: amount,
          value: amount * (ccy === 'PLN' ? 1 : (snap.fx[ccy] || 0)), asset_class: 'CASH' });
      }
    }
    const total = rows.reduce((s, r) => s + r.value, 0);
    rows.sort((x, y) => y.value - x.value);
    document.querySelector('#holdings_table tbody').innerHTML = rows.map((r) => {
      if (r.cash) {
        return `<tr><td>${esc(r.symbol)}</td><td>${esc(T('class_CASH'))}</td><td>${esc(r.account)}</td>
          <td class="num">${nativeMoney(r.quantity, r.currency)}</td><td></td><td></td>
          <td class="num">${money(r.value)}</td><td></td><td></td><td></td><td class="num">${pct(total ? r.value / total : null, { signed: false })}</td></tr>`;
      }
      const stale = r.stale ? ` <span class="badge badge_warn">${esc(T('stale'))}</span>` : '';
      const bond = r.bond ? `<span class="sub">${r.bond.rate != null ? num(r.bond.rate) + '% · ' : ''}#${r.bond.period}</span>` : '';
      return `<tr>
        <td><a href="/instruments/${r.instrument_id}">${esc(r.symbol)}</a><span class="sub">${esc(r.name || '')}</span></td>
        <td>${esc(T('class_' + r.asset_class))}</td><td>${esc(r.account)}</td>
        <td class="num">${num(r.quantity, 6)}</td>
        <td class="num">${nativeMoney(r.avg_price, r.currency)}</td>
        <td class="num">${nativeMoney(r.price, r.currency)}${stale}<span class="sub">${esc(r.price_date || '')}</span>${bond}</td>
        <td class="num">${money(r.value)}</td><td class="num">${money(r.cost)}</td>
        <td class="num ${signClass(r.unrealized)}">${money(r.unrealized, { signed: true })}<span class="sub">${pct(r.unrealized_pct)}</span></td>
        <td class="num ${signClass(r.day_change)}">${money(r.day_change, { signed: true })}</td>
        <td class="num">${pct(total ? r.value / total : null, { signed: false })}</td></tr>`;
    }).join('');
    const sum = (k) => rows.reduce((s, r) => s + (r[k] || 0), 0);
    document.querySelector('#holdings_table tfoot').innerHTML = rows.length ? `<tr><td colspan="6"></td>
      <td class="num">${money(total)}</td><td class="num">${money(sum('cost'))}</td>
      <td class="num ${signClass(sum('unrealized'))}">${money(sum('unrealized'), { signed: true })}</td>
      <td class="num ${signClass(sum('day_change'))}">${money(sum('day_change'), { signed: true })}</td><td></td></tr>` : '';
  }

  loadSnapshot().then((d) => { snap = d.snapshot; render(); }).catch((e) => toast(e.message, true));
})();
