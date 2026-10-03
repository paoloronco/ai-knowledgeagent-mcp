const $ = id => document.getElementById(id);
let current = null, policy = null, wizardStep = 0, authRequired = false;
let messageTimer = null, refreshError = null;
const setupLabels = ['Dashboard access', 'Service health', 'Document folders', 'Indexing policy', 'Eligible documents', 'Dry-run test', 'Initial indexing'];

async function api(path, data) {
  const options = data === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Control-Token': token}, body: JSON.stringify(data)
  };
  const response = await fetch(path, options), body = await response.json();
  if (!response.ok) throw Error(body.error || 'Request failed');
  return body;
}
function message(value, error = false) {
  clearTimeout(messageTimer);
  const notice = $('message');
  notice.textContent = value;
  notice.classList.toggle('error', error);
  notice.classList.toggle('visible', Boolean(value));
  messageTimer = setTimeout(() => {
    notice.classList.remove('visible');
    notice.textContent = '';
  }, error ? 7000 : 4000);
}
function badge(name, good) {
  const el = document.createElement('span'); el.className = 'badge' + (good ? ' ok' : '');
  el.textContent = name + ': ' + (good ? 'ready' : 'unavailable'); return el;
}
function renderSetupProgress(status) {
  const done = Math.max(0, Math.min(7, status.config.setup_step || 0));
  $('setup-progress-bar').value = done;
  $('wizard-progress').textContent = done === 7 ? 'Setup complete' : status.config.onboarding_complete ? status.index_running ? 'Initial indexing in progress · 6 of 7 steps complete' : 'Waiting for initial indexing · 6 of 7 steps complete' : `Step ${wizardStep + 1} of 7 · ${setupLabels[wizardStep]}`;
  for (const item of $('setup-steps').children) {
    const index = Number(item.dataset.progressStep);
    item.classList.toggle('complete', index < done);
    item.classList.toggle('current', index === wizardStep);
    item.classList.toggle('failed', index === 6 && done === 6 && status.config.onboarding_complete && !status.index_running && status.last_result && !status.last_result.dry_run && status.last_result.exit_code !== 0);
    if (index === wizardStep) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  }
  if (done === 6 && status.config.onboarding_complete && !status.index_running && status.last_result && !status.last_result.dry_run && status.last_result.exit_code !== 0) $('wizard-progress').textContent = 'Initial indexing failed · review the log and retry';
}
function showStep(step) {
  wizardStep = Math.max(0, Math.min(6, step));
  document.querySelectorAll('.step').forEach(el => el.classList.toggle('active', Number(el.dataset.step) === wizardStep));
  if (current) renderSetupProgress(current);
  const list = $('setup-steps'), item = list.children[wizardStep];
  if (item) list.scrollTo({left: item.offsetLeft - list.offsetLeft - (list.clientWidth - item.clientWidth) / 2, behavior: 'smooth'});
}
function backStep() { showStep(wizardStep - 1); }
async function nextStep() {
  try {
    const step = Math.min(6, wizardStep + 1);
    const result = await api('/api/onboarding/progress', {step});
    current.config.setup_step = result.setup_step;
    showStep(step);
  } catch (e) { message(e.message, true); }
}
function sourceModeChanged() {
  const mode = document.activeElement?.id?.endsWith('source-mode') ? document.activeElement.value : current.config.source_selection;
  $('setup-source-mode').value = mode; $('dashboard-source-mode').value = mode;
}
function fillSourceInputs() {
  const root = current.config.source_mode === 'host_agent' ? current.config.host_root : current.config.source_root;
  $('setup-source-root').value = root; $('dashboard-source-root').value = root;
  $('setup-source-mode').value = current.config.source_selection; $('dashboard-source-mode').value = current.config.source_selection;
  sourceModeChanged();
}
function renderSourceStatus(s) {
  let text;
  if (s.config.source_mode === 'host_agent') {
    const root = s.config.host_root;
    if (!root) text = 'Enter the absolute path of a folder on the Docker host.';
    else text = 'Folder selected: ' + root + '. Set the indexing policy before scanning.';
  } else {
    text = (s.source_ready ? 'Folder selected: ' : 'Folder unavailable: ') + s.config.source_root;
  }
  $('setup-source-status').textContent = text; $('dashboard-source-status').textContent = text;
}
function renderScanStatus(s) {
  const progress = $('setup-sync-progress');
  const phase = s.agent_progress?.phase;
  let text;
  if (s.scan_error) text = 'Scan failed: ' + s.scan_error;
  else if (s.scan_complete) text = `Scan complete: ${s.scan_checked} files checked, ${s.scan_eligible_count} eligible documents.` + (s.scan_eligible_count ? '' : ' Review the folder and indexing policy, then scan again.');
  else if (s.config.source_mode === 'host_agent' && !s.agent_connected) text = s.agent_managed ? 'Waiting for the host agent. Check its Docker service.' : 'Host folder access is not configured.';
  else if (phase === 'scanning' || s.scan_running && s.config.source_mode !== 'host_agent') text = `Scanning ${s.config.source_mode === 'host_agent' ? 'host folder' : 'document folder'}: ${s.scan_checked} files checked, ${s.scan_eligible_count} eligible…`;
  else if (phase === 'planning') text = 'Comparing eligible documents with the synchronized copy…';
  else if (phase === 'transferring') text = `Transferring changed documents: ${s.agent_progress.completed} of ${s.agent_progress.total}…`;
  else if (phase === 'finalizing') text = 'Finalizing host folder sync…';
  else text = s.config.source_mode === 'host_agent' ? 'Waiting for the host agent to scan the selected folder…' : 'Start the document scan.';
  $('setup-scan-status').textContent = text;
  const showProgress = !s.scan_complete && (s.scan_running || s.config.source_mode === 'host_agent' && s.config.host_root && !s.scan_error);
  progress.classList.toggle('hidden', !showProgress);
  if (showProgress && s.agent_progress?.phase === 'transferring' && s.agent_progress.total > 0) progress.value = 100 * s.agent_progress.completed / s.agent_progress.total;
  else progress.removeAttribute('value');
  const list = $('setup-eligible-list'); list.replaceChildren();
  for (const name of s.scan_eligible_preview || []) { const item = document.createElement('li'); item.textContent = name; list.append(item); }
  if (s.scan_eligible_count > (s.scan_eligible_preview || []).length) { const item = document.createElement('li'); item.textContent = `…and ${s.scan_eligible_count - s.scan_eligible_preview.length} more`; list.append(item); }
  $('scan-next').disabled = !s.scan_ready;
  $('scan-again').disabled = s.scan_running;
}
async function startScan() { try { await api('/api/scan', {}); await refresh(); } catch (e) { message(e.message, true); } }
async function syncNow() {
  try { await api('/api/agent/refresh', {}); message('Host sync requested. The agent will scan the folder shortly.'); }
  catch (e) { message(e.message, true); }
}

async function login() {
  try {
    const response = await fetch('/api/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: $('login-password').value})});
    const body = await response.json(); if (!response.ok) throw Error(body.error || 'Sign-in failed'); location.reload();
  } catch (e) { message(e.message, true); }
}
async function logout() { try { await api('/api/logout', {}); location.reload(); } catch (e) { message(e.message, true); } }
async function setupSecurity() {
  try {
    if ($('login-enabled').checked) {
      const password = $('setup-password').value;
      if (!authRequired || password) {
        await api('/api/security', {enabled: true, password});
        location.reload(); return;
      }
    } else if (authRequired) {
      await api('/api/security', {enabled: false});
      location.reload(); return;
    }
    await nextStep();
  } catch (e) { message(e.message, true); }
}
async function setPassword() { try { await api('/api/security', {enabled: true, password: $('new-password').value}); location.reload(); } catch (e) { message(e.message, true); } }
async function disablePassword() { try { await api('/api/security', {enabled: false}); location.reload(); } catch (e) { message(e.message, true); } }

async function saveSource(advance = false, fromWizard = false) {
  try {
    const selection = $(fromWizard ? 'setup-source-mode' : 'dashboard-source-mode').value;
    const sourceRoot = $(fromWizard ? 'setup-source-root' : 'dashboard-source-root').value.trim();
    const interval = fromWizard ? 0 : Number($('interval').value);
    const result = await api('/api/config', {document_root: sourceRoot, source_selection: selection, folders: [''], interval_hours: interval});
    current.config = result; current.source_root = result.source_root;
    fillSourceInputs(); await refresh();
    if (advance) await nextStep();
    else message('Document root saved.');
  } catch (e) { message(e.message, true); }
}

const extensions = ['.pdf', '.docx', '.pptx', '.md', '.txt', '.html', '.htm'];
function policyWidget(id) {
  const node = $(id); node.replaceChildren();
  const title = document.createElement('h3'); title.textContent = 'Included extensions'; node.append(title);
  const checks = document.createElement('div'); checks.className = 'extensions';
  for (const ext of extensions) {
    const label = document.createElement('label'), box = document.createElement('input');
    box.type = 'checkbox'; box.dataset.extension = ext; box.checked = policy.include_extensions.includes(ext);
    label.append(box, document.createTextNode(' ' + ext)); checks.append(label);
  }
  node.append(checks);
  for (const [key, caption] of [
    ['exclude_directories', 'Excluded directories (one per line)'], ['exclude_top_level', 'Excluded top-level entries'],
    ['exclude_files', 'Excluded files (name or relative path)'], ['exclude_extensions', 'Excluded extensions']
  ]) {
    const label = document.createElement('label'); label.textContent = caption;
    const input = document.createElement('textarea'); input.dataset.policyKey = key; input.value = (policy[key] || []).join('\n'); node.append(label, input);
  }
  const label = document.createElement('label'); label.textContent = 'Maximum file size (MB)';
  const size = document.createElement('input'); size.type = 'number'; size.min = '1'; size.dataset.policySize = 'true'; size.value = policy.max_file_size_mb; node.append(label, size);
}
async function loadPolicy() {
  const result = await api('/api/policy'); policy = result.policy; $('policy-yaml').value = result.content;
  policyWidget('wizard-policy'); policyWidget('dashboard-policy');
}
function formPolicy(id) {
  const node = $(id), values = {...policy};
  values.include_extensions = [...node.querySelectorAll('[data-extension]:checked')].map(x => x.dataset.extension);
  for (const input of node.querySelectorAll('[data-policy-key]')) values[input.dataset.policyKey] = input.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  values.max_file_size_mb = Number(node.querySelector('[data-policy-size]').value); return values;
}
async function savePolicy(advance) {
  try { await api('/api/policy', {policy: formPolicy(advance ? 'wizard-policy' : 'dashboard-policy')}); await loadPolicy(); message('Policy saved.'); if (advance) { await nextStep(); if (current.config.source_mode === 'container') await startScan(); } }
  catch (e) { message(e.message, true); }
}
async function saveYaml() { try { await api('/api/policy', {content: $('policy-yaml').value}); await loadPolicy(); message('YAML saved.'); } catch (e) { message(e.message, true); } }
async function service(name, action) { try { await api('/api/service', {name, action}); message(`${name}: ${action} requested.`); await refresh(); } catch (e) { message(e.message, true); } }
async function runIndex(dry_run) {
  try { await api('/api/index', {dry_run}); message(dry_run ? 'Dry run started.' : 'Indexing started.'); if (dry_run) $('dry-result').textContent = 'Test running…'; await refresh(); }
  catch (e) { message(e.message, true); }
}
async function startInitialIndex() {
  try {
    await api('/api/index', {dry_run: false}); await api('/api/onboarding', {});
    $('wizard').classList.add('hidden'); $('dashboard').classList.remove('hidden');
    message('Indexing started. Follow the log, then start MCP.'); await refresh();
  } catch (e) { message(e.message, true); }
}
async function refresh() {
  try {
    const s = await api('/api/status'); current = s;
    renderSetupProgress(s);
    renderSourceStatus(s);
    renderScanStatus(s);
    $('health').replaceChildren(badge('App', s.app_ready), badge('Qdrant', s.qdrant_ready), badge('MCP', s.mcp_running), badge('Documents', s.source_ready), ...(s.config.source_mode === 'host_agent' ? [badge('Host agent', s.agent_connected)] : []));
    $('wizard-health').replaceChildren(badge('App', s.app_ready), badge('Qdrant', s.qdrant_ready), ...(s.agent_managed ? [badge('Host agent', s.agent_connected)] : []));
    $('source-root').textContent = 'Document root: ' + (s.config.source_mode === 'host_agent' ? s.config.host_root : s.source_root);
    const syncState = s.agent_error ? 'Host sync failed: ' + s.agent_error : !s.agent_connected ? s.agent_managed ? 'Automatic host agent unavailable' : 'Host folder access is not configured' : s.agent_syncing ? 'Syncing documents…' : s.agent_synced ? 'Host documents synchronized' : 'Waiting for host sync';
    const syncDetail = s.agent_last_sync_at ? ` · Last sync: ${new Date(s.agent_last_sync_at * 1000).toLocaleString('en-GB')}` : '';
    $('agent-status').textContent = s.config.source_mode === 'host_agent' ? syncState + syncDetail : '';
    $('index-state').textContent = s.index_running ? 'Indexing in progress…' : s.last_result ? `${s.last_result.dry_run ? 'Dry run' : 'Indexing'} finished with exit code ${s.last_result.exit_code} · ${new Date(s.last_result.finished_at * 1000).toLocaleString('en-GB')}` : 'No run recorded.';
    const readyForMcp = !s.index_running && s.last_result && !s.last_result.dry_run && s.last_result.exit_code === 0 && s.qdrant_ready;
    $('start-after-index').disabled = !readyForMcp || s.mcp_running;
    $('mcp-guidance').textContent = s.index_running ? 'Wait for indexing to finish before starting MCP.' : readyForMcp && !s.mcp_running ? 'Indexing is complete. You can start MCP.' : s.mcp_running ? 'MCP is running.' : '';
    $('log').textContent = s.log || 'No run yet.'; $('setup-log').textContent = s.log || 'No run yet.';
    $('dry').disabled = s.index_running; $('run').disabled = s.index_running || !s.qdrant_ready || !s.source_ready;
    document.querySelectorAll('[data-qdrant]').forEach(x => x.disabled = !s.qdrant_managed);
    $('wizard-qdrant').classList.toggle('hidden', s.qdrant_ready || !s.qdrant_managed);
    $('wizard-qdrant').disabled = !s.qdrant_managed;
    $('next-run').textContent = s.next_run_at ? 'Next update: ' + new Date(s.next_run_at * 1000).toLocaleString('en-GB') : 'Scheduling is off';
    if (document.activeElement !== $('interval')) $('interval').value = s.config.interval_hours;
    if (s.last_result?.dry_run && !s.index_running) {
      $('dry-result').textContent = s.last_result.exit_code === 0 ? 'Test complete. Review the log.' : 'Test failed. Review the log.';
    }
    $('dry-next').disabled = !(s.last_result?.dry_run && !s.index_running && s.last_result.exit_code === 0);
    $('wizard').classList.toggle('hidden', s.config.onboarding_complete); $('dashboard').classList.toggle('hidden', !s.config.onboarding_complete);
    refreshError = null;
  } catch (e) {
    if (refreshError !== e.message) message(e.message, true);
    refreshError = e.message;
  }
}
async function start() {
  try {
    const auth = await api('/api/auth'); if (!auth.authenticated) { $('login-view').classList.remove('hidden'); return; }
    authRequired = auth.required;
    $('app-view').classList.remove('hidden'); $('logout').classList.toggle('hidden', !auth.required);
    $('auth-state').textContent = auth.required ? 'Login enabled' : 'Login disabled';
    current = await api('/api/status');
    $('login-enabled').checked = auth.required;
    fillSourceInputs();
    $('interval').value = current.config.interval_hours;
    await loadPolicy();
    showStep(Math.min(6, current.config.setup_step || 0)); await refresh(); if (wizardStep === 4 && current.config.source_mode === 'container' && !current.scan_complete && !current.scan_running) await startScan(); setInterval(refresh, 3000);
  } catch (e) { message(e.message, true); }
}
start();
