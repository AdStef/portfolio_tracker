(function () {
  const { api, esc } = window.PT;
  const form = document.getElementById('sql_form');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const errors = document.getElementById('form_errors');
    try {
      const res = await api('POST', '/api/sql', { query: form.query.value });
      errors.innerHTML = res.truncated ? '<li>first 1000 rows</li>' : '';
      document.getElementById('sql_result').innerHTML =
        `<thead><tr>${res.columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>` +
        `<tbody>${res.rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody>`;
    } catch (e) {
      errors.innerHTML = `<li>${esc(e.message)}</li>`;
    }
  });
})();
