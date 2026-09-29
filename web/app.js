const $ = id => document.getElementById(id);
const form = $('run-form');
const button = $('run-button');

$('offline').addEventListener('change', () => {
  if ($('offline').checked) {
    $('refresh').checked = false;
    $('auto-refresh').checked = false;
  }
});
$('refresh').addEventListener('change', () => {
  if ($('refresh').checked) $('offline').checked = false;
});
$('auto-refresh').addEventListener('change', () => {
  if ($('auto-refresh').checked) $('offline').checked = false;
});

function selectedSource() {
  return document.querySelector('input[name="source"]:checked').value;
}

function updateSource() {
  const upload = selectedSource() === 'upload';
  $('sample-fields').hidden = upload;
  $('upload-fields').hidden = !upload;
}

document.querySelectorAll('input[name="source"]').forEach(input => input.addEventListener('change', updateSource));

function formatMoney(value, currency) {
  if (value === null || value === undefined) return 'Unknown';
  return new Intl.NumberFormat(undefined, { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));
}

function message(text, isError = true) {
  const box = $('form-message');
  box.textContent = text;
  box.style.color = isError ? '#a34221' : '#17663a';
  box.style.background = isError ? '#fff2ed' : '#eaf7ed';
  box.style.borderColor = isError ? '#ffddcf' : '#c9e9d1';
  box.hidden = !text;
}

function cell(row, text, className = '') {
  const td = document.createElement('td');
  td.textContent = text;
  if (className) td.className = className;
  row.appendChild(td);
}

function addEvidence(resource) {
  const proofs = resource.proofs.filter(Boolean);
  if (!proofs.length) return;
  const details = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = `Pricing evidence · ${resource.address}`;
  details.appendChild(summary);
  proofs.forEach((proof, index) => {
    const item = document.createElement('div');
    item.className = 'proof-item';
    const meter = proof.meter;
    const side = resource.proofs[0] === proof ? 'Before' : 'After';
    const source = proof.source === 'api' ? 'Azure API' : proof.source === 'stale-cache' ? 'stale SQLite cache' : 'SQLite cache';
    item.textContent = `${side}: ${meter.productName} / ${meter.meterName} · ${meter.retailPrice} ${meter.currencyCode} per ${meter.unitOfMeasure} · meter ID ${meter.meterId} · ${source} · `;
    const link = document.createElement('a');
    link.href = proof.source_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open Azure price query';
    item.appendChild(link);
    details.appendChild(item);
  });
  $('proofs').appendChild(details);
}

function showReport(data) {
  $('empty-state').hidden = true;
  $('report').hidden = false;
  const verdict = $('verdict');
  verdict.className = 'verdict ' + (data.status === 'PASSED' ? 'pass' : data.status === 'FAILED' ? 'fail' : 'incomplete');
  $('verdict-icon').textContent = data.status === 'PASSED' ? '✓' : data.status === 'FAILED' ? '!' : '?';
  $('verdict-title').textContent = data.status === 'PASSED' ? 'Within budget' : data.status === 'FAILED' ? 'Budget exceeded' : 'Estimate incomplete';
  $('verdict-message').textContent = data.status === 'PASSED'
    ? 'The known monthly increase is within the limit you set.'
    : data.status === 'FAILED'
      ? `The projected increase exceeds your ${formatMoney(data.threshold, data.currency)} monthly limit by ${formatMoney(data.overage, data.currency)}. Circuit breaker: deployment blocked. A CI check would exit with code 1.`
      : 'One or more prices could not be determined. A strict CI check would exit with code 2.';
  $('prior-cost').textContent = formatMoney(data.prior, data.currency);
  $('new-cost').textContent = formatMoney(data.proposed, data.currency);
  $('delta-cost').textContent = `${Number(data.delta) > 0 ? '+' : ''}${formatMoney(data.delta, data.currency)}`;
  $('resource-count').textContent = `${data.resources.length} changed supported resource${data.resources.length === 1 ? '' : 's'}`;
  const body = $('resource-body');
  body.replaceChildren();
  $('proofs').replaceChildren();
  if (!data.resources.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 7;
    td.textContent = 'No billable changes in this plan.';
    tr.appendChild(td);
    body.appendChild(tr);
  }
  data.resources.forEach(resource => {
    const tr = document.createElement('tr');
    cell(tr, resource.address);
    cell(tr, resource.action);
    cell(tr, resource.region || '—');
    cell(tr, resource.sku);
    cell(tr, formatMoney(resource.old, data.currency));
    cell(tr, formatMoney(resource.new, data.currency));
    cell(tr, `${Number(resource.delta) > 0 ? '+' : ''}${formatMoney(resource.delta, data.currency)}`,
      resource.delta === null ? '' : Number(resource.delta) > 0 ? 'positive' : Number(resource.delta) < 0 ? 'negative' : '');
    body.appendChild(tr);
    addEvidence(resource);
  });
  $('warnings').hidden = !data.warnings.length;
  const warningList = $('warning-list');
  warningList.replaceChildren();
  data.warnings.forEach(text => {
    const li = document.createElement('li');
    li.textContent = text;
    warningList.appendChild(li);
  });
  $('cache-stat').textContent = `${data.cache_hits} cache hits · ${data.api_calls} Azure API requests`;
  $('skip-stat').textContent = `${data.skipped} free or unchanged resources skipped`;
  $('budget-stat').textContent = `Budget limit ${formatMoney(data.threshold, data.currency)}/month`;
}

async function post(path, data) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'The request failed.');
  return payload;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  message('');
  const limit = $('limit').value;
  if (limit === '' || !Number.isFinite(Number(limit)) || Number(limit) < 0) {
    message('Enter a non-negative monthly budget limit.');
    return;
  }
  const request = {
    source: selectedSource(),
    max_increase: limit,
    currency: $('currency').value,
    offline: $('offline').checked,
    refresh: $('refresh').checked,
    auto_refresh: $('auto-refresh').checked
  };
  try {
    if (request.source === 'sample') {
      request.sample = $('sample').value;
    } else {
      const file = $('plan-file').files[0];
      if (!file) throw new Error('Choose a Terraform plan JSON file first.');
      if (file.size > 10 * 1024 * 1024) throw new Error('The plan file must be 10 MB or smaller.');
      try { request.plan = JSON.parse(await file.text()); }
      catch { throw new Error('This file is not valid JSON. Use terraform show -json to generate it.'); }
    }
    button.disabled = true;
    button.textContent = 'Checking Azure prices…';
    showReport(await post('/api/analyze', request));
  } catch (error) {
    message(error.message || 'The check could not finish.');
  } finally {
    button.disabled = false;
    button.textContent = 'Run cost check →';
  }
});

$('clear-cache').addEventListener('click', async () => {
  try {
    const response = await post('/api/clear-cache', { clear: true });
    message(response.message, false);
  } catch (error) {
    message(error.message || 'Could not clear the cache.');
  }
});

updateSource();
