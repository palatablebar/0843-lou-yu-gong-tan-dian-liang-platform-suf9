(function () {
  var state = { payload: null, kind: 'bars', run: null, approved: false };
  var $ = function (id) { return document.getElementById(id); };
  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch];
    });
  }
  async function request(url, options) {
    var response = await fetch(url, Object.assign({headers: {'Content-Type': 'application/json'}}, options || {}));
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
    return data;
  }
  function setNotice(text) { $('notice').textContent = text || ''; }
  function renderIssues(data) {
    $('issue-count').textContent = data.issues.length + ' 条';
    $('issue-list').innerHTML = data.issues.length ? data.issues.map(function (item) {
      return '<li><span>' + esc(item.line || '-') + '</span><span>' + esc(item.key || '无主键') + '</span><code>' + esc(item.code) + '</code></li>';
    }).join('') : '<li class="empty">暂无异常</li>';
  }
  function renderBreakdown(items) {
    if (!items || !items.length) return '';
    return '<details><summary>' + items.length + ' 项</summary><ul>' + items.map(function (item) {
      return '<li>' + esc(item) + '</li>';
    }).join('') + '</ul></details>';
  }
  function renderRows(data) {
    var labels = Object.assign({label: '记录'}, state.resultColumns);
    var source = data.row_kind === 'source';
    var hasBreakdown = data.rows.some(function (row) { return row.breakdown && row.breakdown.length; });
    var keys = source ? state.inputColumns : Object.keys(labels).filter(function (key) {
      return data.rows.some(function (row) { return Object.hasOwn(row, key); });
    });
    $('row-count').textContent = source ? data.rows.length + ' 行预览' :
      data.summary.PASS + ' 通过 / ' + data.summary.REVIEW + ' 复核 / ' + data.summary.REJECT + ' 阻断';
    var tail = source ? '' : '<th>结论</th>' + (hasBreakdown ? '<th>计算分项</th>' : '');
    $('row-head').innerHTML = '<tr>' + keys.map(function (key) { return '<th>' + esc(labels[key] || key) + '</th>'; }).join('') + tail + '</tr>';
    $('row-body').innerHTML = data.rows.length ? data.rows.map(function (row) {
      var values = keys.map(function (key) { return '<td class="' + (typeof row[key] === 'number' ? 'num' : '') + '">' + esc(row[key]) + '</td>'; }).join('');
      var verdict = source ? '' : '<td><span class="verdict" data-v="' + esc(row.verdict) + '">' + esc(row.verdict || '') + '</span><br><small>' + esc(row.reason || '') + '</small></td>';
      var breakdown = hasBreakdown ? '<td>' + renderBreakdown(row.breakdown) + '</td>' : '';
      return '<tr>' + values + verdict + breakdown + '</tr>';
    }).join('') : '<tr><td class="empty" colspan="' + (keys.length + (source ? 0 : 1)) + '">没有可展示条目</td></tr>';
  }
  function renderLedger(data) {
    if (!data.ledger) { $('ledger-list').innerHTML = '<p class="empty">运行对账后显示</p>'; return; }
    var values = data.ledger;
    $('ledger-list').innerHTML = [
      ['来源行', values.counts.input], ['采信行', values.counts.accepted], ['隔离行', values.counts.isolated],
      ['精确重复', values.counts.duplicates], ['忽略行', values.counts.ignored], ['计算条目', values.counts.computed]
    ].map(function (row) { return '<div class="ledger-row"><span>' + row[0] + '</span><strong>' + row[1] + '</strong></div>'; }).join('') +
      '<div class="ledger-row"><span>' + esc(values.metric_field) + '</span><strong>' + esc(values.metric_total) + '</strong></div>' +
      values.checks.map(function (check) { return '<div class="ledger-row"><span>' + esc(check.label) + '</span><strong class="' + (check.ok ? 'check-ok' : 'check-bad') + '">' + (check.ok ? '通过' : '异常') + '</strong></div>'; }).join('');
  }
  function parseLimits() {
    var text = ($('contract-limits') ? $('contract-limits').value : '') || '';
    var period = $('period') ? $('period').value : '';
    var limits = null;
    if (text.trim()) {
      try {
        var parsed = JSON.parse(text);
        if (parsed && typeof parsed === 'object') {
          limits = parsed.contract_limits || parsed.limits || parsed;
        }
      } catch (err) {
        limits = {};
        text.split(/\n+/).forEach(function (line) {
          var match = line.match(/^\s*([^=#\s]+)\s*[=:：]\s*(-?\d+(?:\.\d+)?)\s*(kwh|wh)?\s*$/i);
          if (match) {
            var key = match[1], value = parseFloat(match[2]), unit = (match[3] || '').toLowerCase();
            limits[key] = unit === 'wh' ? {wh: value} : value;
          }
        });
        if (!Object.keys(limits).length) throw new Error('合同上限格式无法识别，请用 R1=30 或 JSON');
      }
    }
    return {limits: limits, period: period || null};
  }
  function issuanceMap(data) {
    var map = {};
    (data.issuances || data.postings || []).forEach(function (item) { map[item.building_id] = item; });
    return map;
  }
  function renderBuildings(data) {
    var body = $('building-body');
    if (!body) return;
    var buildings = data.buildings || data.results || [];
    var issued = issuanceMap(data);
    var canIssue = !!(state.run && state.run.run_id);
    var issueAllBtn = $('issue-all');
    if (issueAllBtn) issueAllBtn.disabled = !canIssue || !buildings.some(function (b) {
      return (b.issuable !== false && b.verdict !== 'REJECT') && !issued[b.building_id];
    });
    if (!buildings.length) {
      body.innerHTML = '<tr><td class="empty" colspan="8">执行到“公摊分摊”后显示楼栋</td></tr>';
      var summary0 = $('issuance-summary');
      if (summary0) summary0.textContent = '执行批次后显示各楼栋签发结果';
      return;
    }
    var done = 0, blocked = 0;
    body.innerHTML = buildings.map(function (b) {
      var bid = b.building_id || b.label;
      var rec = issued[bid] || b.issuance || b.posting;
      var shortfall = b.shortfall != null ? b.shortfall : (b.shortfall_mwh || 0);
      var issuable = b.issuable !== false && b.verdict !== 'REJECT' && !shortfall;
      var resultCell, action;
      if (rec && (rec.status === 'ISSUED' || rec.issued || rec.posted)) {
        done += 1;
        resultCell = '<span class="verdict" data-v="PASS">已签发</span><br><small>' + esc(rec.posting_no || rec.issuance_no || rec.id) + (rec.duplicate ? ' · 重试返回原单' : '') + '</small>';
        action = '<button type="button" disabled>已出账</button>';
      } else if (!issuable) {
        blocked += 1;
        resultCell = '<span class="verdict" data-v="REJECT">不能签发</span><br><small>' + esc(b.reason || b.issue_blocker || '') + '</small>';
        action = '<button type="button" disabled>阻断</button>';
      } else {
        resultCell = '<span class="hint">对平，待签发</span>';
        action = canIssue ? '<button type="button" data-issue="' + esc(bid) + '">签发该栋</button>' : '<small>执行批次后可签发</small>';
      }
      return '<tr>' +
        '<td>' + esc(bid) + '</td>' +
        '<td><span class="verdict" data-v="' + esc(b.verdict) + '">' + esc(b.verdict || '') + '</span><br><small>' + esc(b.reason || '') + '</small></td>' +
        '<td class="num">' + esc(b.common_wh != null ? b.common_wh : b.common_mwh) + '</td>' +
        '<td class="num">' + esc(b.allocated != null ? b.allocated : b.allocated_common_mwh) + '</td>' +
        '<td class="num' + (shortfall ? ' shortfall' : '') + '">' + esc(shortfall) + '</td>' +
        '<td>' + ((b.capped_rooms || []).map(esc).join('、') || '—') + '</td>' +
        '<td>' + resultCell + '</td>' +
        '<td>' + action + '</td>' +
      '</tr>';
    }).join('');
    Array.prototype.forEach.call(document.querySelectorAll('[data-issue]'), function (btn) {
      btn.addEventListener('click', function () { issueBuilding(btn.getAttribute('data-issue'), btn); });
    });
    var summary = $('issuance-summary');
    if (summary) summary.textContent = '已签发 ' + done + ' 栋 · 阻断 ' + blocked + ' 栋 · 共 ' + buildings.length + ' 栋；重试不重复出账';
  }
  async function refreshRun(runId) {
    var run = await request('/api/runs/' + runId);
    state.run = run;
    render(run);
    $('run-status').textContent = run.status + ' · rev ' + run.revision;
    $('revision').textContent = 'rev ' + run.revision;
    return run;
  }
  async function issueBuilding(buildingId, btn) {
    if (!state.run) return;
    try {
      if (btn) btn.disabled = true;
      setNotice('');
      await request('/api/runs/' + state.run.run_id + '/issue', {
        method: 'POST', body: JSON.stringify({building_id: buildingId})
      });
      await refreshRun(state.run.run_id);
    } catch (error) {
      setNotice(error.message);
      if (btn) btn.disabled = false;
    }
  }
  async function issueAll() {
    if (!state.run) return;
    try {
      setNotice('');
      $('issue-all').disabled = true;
      await request('/api/runs/' + state.run.run_id + '/issue', {method: 'POST', body: JSON.stringify({})});
      await refreshRun(state.run.run_id);
    } catch (error) { setNotice(error.message); }
  }
  function render(data) {
    state.payload = data;
    $('chart-label').textContent = Object.values(state.resultColumns)[0];
    $('m-input').textContent = data.counts.input;
    $('m-accepted').textContent = data.counts.accepted;
    $('m-isolated').textContent = data.counts.isolated + data.counts.duplicates;
    $('m-rejected').textContent = data.summary.REJECT;
    renderRows(data);
    renderIssues(data);
    renderLedger(data);
    renderBuildings(data);
    window.renderChart($('chart'), data.chart && data.chart.length ? (state.kind || 'bars') : 'bars', data.chart || []);
  }
  function stageButtons(stages) {
    $('stage-nav').innerHTML = stages.map(function (stage, index) {
      return '<button type="button" data-stage="' + stage.id + '" aria-pressed="' + (index === 0 ? 'true' : 'false') + '">' + esc(stage.name) + '</button>';
    }).join('');
    Array.from(document.querySelectorAll('[data-stage]')).forEach(function (button) {
      button.addEventListener('click', function () {
        document.querySelectorAll('[data-stage]').forEach(function (other) { other.setAttribute('aria-pressed', String(other === button)); });
        loadStage(button.getAttribute('data-stage'));
      });
    });
  }
  async function loadStage(stage) {
    try {
      setNotice('');
      document.body.setAttribute('aria-busy', 'true');
      var extra = {};
      try { extra = parseLimits(); } catch (limitError) { setNotice(limitError.message); }
      var payload = await request('/api/stages/' + stage, {
        method: 'POST',
        body: JSON.stringify(Object.assign({profile: $('profile').value}, extra.limits ? {contract_limits: extra.limits, month: extra.period} : {}))
      });
      render(payload);
    } catch (error) { setNotice(error.message); }
    finally { document.body.removeAttribute('aria-busy'); }
  }
  async function runBatch() {
    try {
      setNotice('');
      var entered = parseLimits();
      $('run').disabled = true;
      if ($('apply-limits')) $('apply-limits').disabled = true;
      var requestBody = {profile: $('profile').value};
      if (entered.limits) requestBody.contract_limits = entered.limits;
      if (entered.period) requestBody.month = entered.period;
      var run = await request('/api/runs', {method: 'POST', body: JSON.stringify(requestBody)});
      state.run = run;
      state.approved = run.status === 'APPROVED';
      render(run);
      $('run-status').textContent = run.status + ' · rev ' + run.revision;
      $('revision').textContent = 'rev ' + run.revision;
      $('sign').disabled = run.summary.REJECT > 0 || state.approved;
      $('hold').disabled = state.approved;
      $('download').hidden = !state.approved;
      if (state.approved) $('download').href = '/api/runs/' + run.run_id + '/evidence';
    } catch (error) { setNotice(error.message); }
    finally { $('run').disabled = false; if ($('apply-limits')) $('apply-limits').disabled = false; }
  }
  async function review(decision) {
    if (!state.run) return;
    try {
      var run = await request('/api/runs/' + state.run.run_id + '/review', {
        method: 'POST',
        body: JSON.stringify({decision: decision, comment: $('comment').value, expected_revision: state.run.revision})
      });
      state.run = run;
      state.approved = run.status === 'APPROVED';
      $('run-status').textContent = run.status + ' · rev ' + run.revision;
      $('revision').textContent = 'rev ' + run.revision;
      $('sign').disabled = true;
      $('hold').disabled = true;
      $('download').hidden = !state.approved;
      if (state.approved) $('download').href = '/api/runs/' + run.run_id + '/evidence';
    } catch (error) { setNotice(error.message); }
  }
  async function boot() {
    try {
      var catalog = await request('/api/catalog');
      state.kind = catalog.chart;
      state.resultColumns = catalog.result_columns;
      state.inputColumns = catalog.columns;
      stageButtons(catalog.stages.slice(0, 5));
      document.querySelector('.rail-note').textContent = catalog.code + ' · ' + catalog.stages[6].name;
      await loadStage('intake');
    } catch (error) { setNotice(error.message); }
    $('run').addEventListener('click', runBatch);
    if ($('apply-limits')) $('apply-limits').addEventListener('click', runBatch);
    if ($('issue-all')) $('issue-all').addEventListener('click', issueAll);
    $('sign').addEventListener('click', function () { review('APPROVED'); });
    $('hold').addEventListener('click', function () { review('HELD'); });
    $('profile').addEventListener('change', function () {
      state.run = null; state.approved = false;
      $('sign').disabled = true; $('hold').disabled = true; $('download').hidden = true;
      $('run-status').textContent = '未执行批次'; $('revision').textContent = 'rev 0';
      loadStage('intake');
    });
  }
  document.addEventListener('DOMContentLoaded', boot);
})();