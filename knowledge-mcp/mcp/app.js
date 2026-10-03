const $ = id => document.getElementById(id);
let current = null, policy = null, selectedFolders = [''], availableFolders = [''], loadedSyncRevision = null, wizardStep = 0, authRequired = false;
let messageTimer = null, refreshError = null;
const setupLabels = ['Dashboard access', 'Service health', 'Document folders', 'Indexing policy', 'Dry-run test', 'Initial indexing'];

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
  const done = Math.max(0, Math.min(6, status.config.setup_step || 0));
  $('setup-progress-bar').value = done;
  $('wizard-progress').textContent = done === 6 ? 'Setup complete' : status.config.onboarding_complete ? status.index_running ? 'Initial indexing in progress · 5 of 6 steps complete' : 'Waiting for initial indexing · 5 of 6 steps complete' : `Step ${wizardStep + 1} of 6 · ${setupLabels[wizardStep]}`;
  for (const item of $('setup-steps').children) {
    const index = Number(item.dataset.progressStep);
    item.classList.toggle('complete', index < done);
    item.classList.toggle('current', index === wizardStep);
    item.classList.toggle('failed', index === 5 && done === 5 && status.config.onboarding_complete && !status.index_running && status.last_result && !status.last_result.dry_run && status.last_result.exit_code !== 0);
    if (index === wizardStep) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  }
  if (done === 5 && status.config.onboarding_complete && !status.index_running && status.last_result && !status.last_result.dry_run && status.last_result.exit_code !== 0) $('wizard-progress').textContent = 'Initial indexing failed · review the log and retry';
}
function showStep(step) {
  wizardStep = Math.max(0, Math.min(5, step));
  document.querySelectorAll('.step').forEach(el => el.classList.toggle('active', Number(el.dataset.step) === wizardStep));
  if (current) renderSetupProgress(current);
  const list = $('setup-steps'), item = list.children[wizardStep];
  if (item) list.scrollTo({left: item.offsetLeft - list.offsetLeft - (list.clientWidth - item.clientWidth) / 2, behavior: 'smooth'});
}
function backStep() { showStep(wizardStep - 1); }
async function nextStep() {
  try {
    const step = Math.min(5, wizardStep + 1);
    const result = await api('/api/onboarding/progress', {step});
    current.config.setup_step = result.setup_step;
    showStep(step);
  } catch (e) { message(e.message, true); }
}
function sourceModeChanged() {
  const mode = document.activeElement?.id?.endsWith('source-mode') ? document.activeElement.value : current.config.source_mode;
  $('setup-source-mode').value = mode; $('dashboard-source-mode').value = mode;
  document.querySelectorAll('[data-host-help]').forEach(el => el.classList.toggle('hidden', mode !== 'host_agent'));
  const root = mode === 'host_agent' ? current.config.host_root : current.config.source_mode === 'container' ? current.config.source_root : '';
  $('setup-source-root').value = root; $('dashboard-source-root').value = root;
}
async function pairAgent() {
  try {
    const result = await api('/api/agent/pair', {});
    $('setup-agent-key').textContent = 'Pairing key (shown once): ' + result.token;
    $('dashboard-agent-key').textContent = 'Pairing key (shown once): ' + result.token;
    message('Host agent key generated. Install or re-pair the agent on the Docker host.');
  } catch (e) { message(e.message, true); }
}
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

function drawFolders() {
  document.querySelectorAll('[data-folder-list]').forEach(list => {
    list.replaceChildren();
    for (const value of [...new Set([...availableFolders, ...selectedFolders])]) {
      const label = document.createElement('label'), box = document.createElement('input');
      box.type = 'checkbox'; box.checked = selectedFolders.includes(value);
      box.onchange = () => {
        selectedFolders = box.checked ? (value === '' ? [''] : [...selectedFolders.filter(x => x !== ''), value]) : selectedFolders.filter(x => x !== value);
        drawFolders();
      };
      label.append(box, document.createTextNode(value || '(entire document root)')); list.append(label);
    }
  });
}
function folderWidget(id) {
  const node = $(id); node.replaceChildren();
  const hint = document.createElement('p'); hint.className = 'hint'; hint.textContent = `Subfolders under ${current.config.source_mode === 'host_agent' ? current.config.host_root : current.source_root}`;
  const list = document.createElement('div'); list.className = 'folders'; list.dataset.folderList = 'true';
  const add = document.createElement('div'); add.className = 'row';
  const input = document.createElement('input'); input.type = 'text'; input.placeholder = 'Optional subfolder path'; input.setAttribute('aria-label', 'Add subfolder'); input.style.flex = '1';
  const button = document.createElement('button'); button.className = 'secondary'; button.textContent = 'Add subfolder';
  button.onclick = () => {
    let value = input.value.trim(); if (!value) return;
    const root = current.config.source_mode === 'host_agent' ? current.config.host_root : current.source_root;
    if (value.startsWith(root + '/')) value = value.slice(root.length + 1);
    if (value.startsWith('/')) { message('Set this absolute path as the document root above, then save it.', true); return; }
    selectedFolders = [...selectedFolders.filter(x => x !== ''), value]; drawFolders(); input.value = '';
  };
  add.append(input, button); node.append(hint, list, add); drawFolders();
}
async function loadFolders() {
  const result = await api('/api/folders'); availableFolders = result.folders;
  folderWidget('wizard-folders'); folderWidget('dashboard-folders');
}
async function saveFolders(advance = false, fromWizard = false) {
  try {
    const mode = $(fromWizard ? 'setup-source-mode' : 'dashboard-source-mode').value;
    const sourceRoot = $(fromWizard ? 'setup-source-root' : 'dashboard-source-root').value.trim();
    const oldRoot = current.config.source_mode === 'host_agent' ? current.config.host_root : current.source_root;
    const folders = mode === current.config.source_mode && sourceRoot === oldRoot ? selectedFolders : [''];
    const interval = fromWizard ? 0 : Number($('interval').value);
    const result = await api('/api/config', {...(mode === 'host_agent' ? {host_root: sourceRoot} : {source_root: sourceRoot}), source_mode: mode, folders, interval_hours: interval});
    selectedFolders = [...result.folders]; current.config = result; current.source_root = result.source_root;
    $('setup-source-root').value = mode === 'host_agent' ? result.host_root : result.source_root;
    $('dashboard-source-root').value = $('setup-source-root').value;
    await loadFolders(); message(mode === 'host_agent' ? 'Host folder saved. Waiting for the agent to sync it.' : 'Document source saved.'); if (advance) await nextStep(); await refresh();
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
  try { await api('/api/policy', {policy: formPolicy(advance ? 'wizard-policy' : 'dashboard-policy')}); await loadPolicy(); message('Policy saved.'); if (advance) await nextStep(); }
  catch (e) { message(e.message, true); }
}
async function saveYaml() { try { await api('/api/policy', {content: $('policy-yaml').value}); await loadPolicy(); message('YAML saved.'); } catch (e) { message(e.message, true); } }
async function service(name, action) { try { await api('/api/service', {name, action}); message(`${name}: ${action} requested.`); await refresh(); } catch (e) { message(e.message, true); } }
async function waitForFreshHostSync() {
  const before = await api('/api/status');
  if (before.config.source_mode !== 'host_agent') return;
  const request = await api('/api/agent/refresh', {});
  message('Syncing the host folder before indexing…');
  const deadline = Date.now() + 15 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 2000));
    const status = await api('/api/status');
    if (status.agent_error) throw Error('Host sync failed: ' + status.agent_error);
    if (status.config.source_mode !== 'host_agent' || status.config.sync_revision !== before.config.sync_revision) throw Error('Document source changed during sync');
    if (status.source_ready && status.agent_sync_request_completed >= request.sync_request) return;
  }
  throw Error('Host sync did not finish. Check the agent status and log.');
}
async function runIndex(dry_run) {
  try { await waitForFreshHostSync(); await api('/api/index', {dry_run}); message(dry_run ? 'Dry run started.' : 'Indexing started.'); if (dry_run) $('dry-result').textContent = 'Test running…'; await refresh(); }
  catch (e) { message(e.message, true); }
}
async function startInitialIndex() {
  try {
    await waitForFreshHostSync();
    await api('/api/index', {dry_run: false}); await api('/api/onboarding', {});
    $('wizard').classList.add('hidden'); $('dashboard').classList.remove('hidden');
    message('Indexing started. Follow the log, then start MCP.'); await refresh();
  } catch (e) { message(e.message, true); }
}
async function refresh() {
  try {
    const s = await api('/api/status'); current = s;
    renderSetupProgress(s);
    $('health').replaceChildren(badge('App', s.app_ready), badge('Qdrant', s.qdrant_ready), badge('MCP', s.mcp_running), badge('Documents', s.source_ready), ...(s.config.source_mode === 'host_agent' ? [badge('Host agent', s.agent_connected)] : []));
    $('wizard-health').replaceChildren(badge('App', s.app_ready), badge('Qdrant', s.qdrant_ready));
    $('source-root').textContent = 'Document root: ' + (s.config.source_mode === 'host_agent' ? s.config.host_root : s.source_root);
    const syncState = !s.agent_connected ? 'Host agent disconnected' : s.agent_error ? 'Host sync failed: ' + s.agent_error : s.agent_syncing ? 'Syncing documents…' : s.agent_synced ? 'Host documents synchronized' : 'Waiting for host sync';
    const syncDetail = s.agent_last_sync_at ? ` · Last sync: ${new Date(s.agent_last_sync_at * 1000).toLocaleString('en-GB')}` : '';
    $('agent-status').textContent = s.config.source_mode === 'host_agent' ? syncState + syncDetail : '';
    $('setup-agent-status').textContent = s.config.source_mode === 'host_agent' ? syncState + syncDetail : '';
    if (s.config.source_mode === 'host_agent' && s.agent_synced && loadedSyncRevision !== s.config.sync_revision) { loadedSyncRevision = s.config.sync_revision; loadFolders().catch(e => message(e.message, true)); }
    $('index-state').textContent = s.index_running ? 'Indexing in progress…' : s.last_result ? `${s.last_result.dry_run ? 'Dry run' : 'Indexing'} finished with exit code ${s.last_result.exit_code} · ${new Date(s.last_result.finished_at * 1000).toLocaleString('en-GB')}` : 'No run recorded.';
    const readyForMcp = !s.index_running && s.last_result && !s.last_result.dry_run && s.last_result.exit_code === 0 && s.qdrant_ready;
    $('start-after-index').disabled = !readyForMcp || s.mcp_running;
    $('mcp-guidance').textContent = s.index_running ? 'Wait for indexing to finish before starting MCP.' : readyForMcp && !s.mcp_running ? 'Indexing is complete. You can start MCP.' : s.mcp_running ? 'MCP is running.' : '';
    $('log').textContent = s.log || 'No run yet.'; $('setup-log').textContent = s.log || 'No run yet.';
    $('dry').disabled = s.index_running; $('run').disabled = s.index_running || !s.qdrant_ready || !s.source_ready;
    document.querySelectorAll('[data-qdrant]').forEach(x => x.disabled = !s.qdrant_managed); $('wizard-qdrant').disabled = !s.qdrant_managed;
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
    current = await api('/api/status'); selectedFolders = [...current.config.folders];
    $('login-enabled').checked = auth.required || current.config.setup_step === 0;
    $('setup-source-mode').value = current.config.source_mode; $('dashboard-source-mode').value = current.config.source_mode;
    sourceModeChanged();
    $('interval').value = current.config.interval_hours;
    await Promise.all([loadFolders(), loadPolicy()]);
    showStep(Math.min(5, current.config.setup_step || 0)); await refresh(); setInterval(refresh, 3000);
  } catch (e) { message(e.message, true); }
}
start();
