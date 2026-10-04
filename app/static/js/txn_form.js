(function () {
  const form = document.getElementById('txn_form');
  const typeSel = document.getElementById('txn_type');
  const accountSel = form.querySelector('[name=account_id]');
  const ccySel = document.getElementById('cash_currency');
  const symbol = form.querySelector('[name=symbol]');
  const newInst = document.getElementById('new_instrument');
  const known = new Set(window.KNOWN_SYMBOLS || []);
  const isEdit = form.dataset.method === 'PUT';

  function update() {
    const type = typeSel.value;
    form.querySelectorAll('[data-show]').forEach((el) => {
      el.hidden = !el.dataset.show.split(' ').includes(type);
    });
    const s = symbol.value.trim();
    newInst.hidden = !s || known.has(s) || symbol.closest('[data-show]').hidden;
  }

  function syncCurrency() {
    const opt = accountSel.selectedOptions[0];
    if (opt && opt.dataset.currency) ccySel.value = opt.dataset.currency;
  }

  typeSel.addEventListener('change', update);
  symbol.addEventListener('input', update);
  accountSel.addEventListener('change', syncCurrency);
  if (!isEdit) {
    syncCurrency();
    const d = form.querySelector('[name=date]');
    if (!d.value) d.value = new Date().toISOString().slice(0, 10);
  }
  update();
})();
