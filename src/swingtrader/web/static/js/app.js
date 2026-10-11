// Swing Trader India — client helpers
async function api(url, method, body) {
  const opts = { method: method || 'GET', headers: {'Content-Type': 'application/json'} };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  return r.json();
}
function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show alert alert-' + (type || 'info');
  setTimeout(() => t.className = '', 3000);
}
function fmt(v, d) { return v == null ? '—' : Number(v).toLocaleString('en-IN', {minimumFractionDigits: d||2, maximumFractionDigits: d||2}); }
function badge(action) {
  const m = {BUY_SETUP:'buy', WAIT:'wait', NO_TRADE:'no', SELL_EXIT_SETUP:'sell'};
  return `<span class="badge badge-${m[action]||'no'}">${action}</span>`;
}
