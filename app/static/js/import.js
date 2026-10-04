(function () {
  const { T, api, esc, num, toast } = window.PT;
  const form = document.getElementById('import_form');
  const panel = document.getElementById('preview_panel');
  const commitBtn = document.getElementById('commit_btn');
  let token = null;

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(form);
    try {
      const res = await api('POST', '/api/import/preview', fd);
      token = res.token;
      document.getElementById('form_errors').innerHTML = '';
      const s = res.summary;
      document.getElementById('preview_summary').textContent =
        `${T('status_ok')}: ${s.ok || 0} · ${T('status_duplicate')}: ${s.duplicate || 0} · ${T('status_error')}: ${s.error || 0}`;
      document.getElementById('new_instruments').textContent = res.new_instruments.length
        ? `${T('new_instruments')}: ${res.new_instruments.join(', ')}` : '';
      document.querySelector('#preview_table tbody').innerHTML = res.rows.map((r) => {
        const d = r.data || {};
        return `<tr class="${r.status === 'error' ? 'row_error' : ''}">
          <td>${r.line}</td><td class="status_${r.status}">${esc(T('status_' + r.status))}</td>
          <td>${esc(d.date)}</td><td>${esc(d.account || '')}</td><td>${esc(d.type)}</td><td>${esc(d.symbol || '')}</td>
          <td class="num">${esc(d.quantity || '')}</td><td class="num">${esc(d.price || '')}</td>
          <td class="num">${r.cash_amount != null ? num(r.cash_amount) + ' ' + esc(r.cash_currency) : esc(d.amount || '')}</td>
          <td class="txt_red">${esc((r.errors || []).join('; '))}</td></tr>`;
      }).join('');
      commitBtn.disabled = !s.ok;
      panel.hidden = false;
    } catch (e) {
      document.getElementById('form_errors').innerHTML = (e.errors || [e.message]).map((x) => `<li>${esc(x)}</li>`).join('');
    }
  });

  commitBtn.addEventListener('click', async () => {
    commitBtn.disabled = true;
    try {
      const res = await api('POST', '/api/import/commit', {
        token, profile: form.profile.value, account_id: form.account_id.value,
      });
      toast(`${T('imported')}: ${res.imported} ${T('rows')}`);
      setTimeout(() => window.location.reload(), 800);
    } catch (e) {
      toast(e.message, true);
      commitBtn.disabled = false;
    }
  });
})();
