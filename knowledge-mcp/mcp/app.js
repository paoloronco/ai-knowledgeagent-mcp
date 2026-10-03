const $ = id => document.getElementById(id);
let current = null, policy = null, selectedFolders = [''], availableFolders = [''];

async function api(path, data) {
  const options = data === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Control-Token': token}, body: JSON.stringify(data)
  };
  const response = await fetch(path, options), body = await response.json();
  if (!response.ok) throw Error(body.error || 'Request failed');
  return body;
}
function message(value, error = false) { $('message').textContent = value; $('message').style.color = error ? '#a32121' : '#176438'; }
function badge(name, good) {
  const el = document.createElement('span'); el.className = 'badge' + (good ? ' ok' : '');
  el.textContent = name + ': ' + (good ? 'ready' : 'unavailable'); return el;
}
function showStep(step) {
  sessionStorage.setItem('knowledge-onboarding-step', String(step));
  document.querySelectorAll('.step').forEach(el => el.classList.toggle('active', Number(el.dataset.step) === step));
  $('wizard-progress').textContent = `Step ${step + 1} of 6`;
}
function nextStep() { showStep(Math.min(5, Number(sessionStorage.getItem('knowledge-onboarding-step') || 0) + 1)); }

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
      await api('/api/security', {enabled: true, password: $('setup-password').value});
      sessionStorage.setItem('knowledge-onboarding-step', '1'); location.reload(); return;
    }
    nextStep();
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
  const hint = document.createElement('p'); hint.className = 'hint'; hint.textContent = `Subfolders under ${current.source_root}`;
  const list = document.createElement('div'); list.className = 'folders'; list.dataset.folderList = 'true';
  const add = document.createElement('div'); add.className = 'row';
  const input = document.createElement('input'); input.type = 'text'; input.placeholder = 'Optional subfolder path'; input.setAttribute('aria-label', 'Add subfolder'); input.style.flex = '1';
  const button = document.createElement('button'); button.className = 'secondary'; button.textContent = 'Add subfolder';
  button.onclick = () => {
    let value = input.value.trim(); if (!value) return;
    if (value.startsWith(current.source_root + '/')) value = value.slice(current.source_root.length + 1);
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
    const sourceRoot = $(fromWizard ? 'setup-source-root' : 'dashboard-source-root').value.trim().replace(/\/+$/, '') || '/';
    const folders = sourceRoot === current.source_root ? selectedFolders : [''];
    const interval = fromWizard ? 0 : Number($('interval').value);
    const result = await api('/api/config', {source_root: sourceRoot, folders, interval_hours: interval});
    selectedFolders = [...result.folders]; current.source_root = result.source_root;
    $('setup-source-root').value = result.source_root; $('dashboard-source-root').value = result.source_root;
    await loadFolders(); message('Document source saved.'); if (advance) nextStep(); await refresh();
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
  try { await api('/api/policy', {policy: formPolicy(advance ? 'wizard-policy' : 'dashboard-policy')}); await loadPolicy(); message('Policy saved.'); if (advance) nextStep(); }
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
    sessionStorage.removeItem('knowledge-onboarding-step'); $('wizard').classList.add('hidden'); $('dashboard').classList.remove('hidden');
    message('Indexing started. Follow the log, then start MCP.'); await refresh();
  } catch (e) { message(e.message, true); }
}
async function refresh() {
  try {
    const s = await api('/api/status'); current = s;
    $('health').replaceChildren(badge('App', s.app_ready), badge('Qdrant', s.qdrant_ready), badge('MCP', s.mcp_running), badge('Documents', s.source_ready));
    $('wizard-health').replaceChildren(badge('App', s.app_ready), badge('Qdrant', s.qdrant_ready));
    $('source-root').textContent = 'Document root: ' + s.source_root;
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
      $('dry-next').disabled = s.last_result.exit_code !== 0;
    }
    $('wizard').classList.toggle('hidden', s.config.onboarding_complete); $('dashboard').classList.toggle('hidden', !s.config.onboarding_complete);
  } catch (e) { message(e.message, true); }
}
async function start() {
  try {
    const auth = await api('/api/auth'); if (!auth.authenticated) { $('login-view').classList.remove('hidden'); return; }
    $('app-view').classList.remove('hidden'); $('logout').classList.toggle('hidden', !auth.required);
    $('auth-state').textContent = auth.required ? 'Login enabled' : 'Login disabled';
    current = await api('/api/status'); selectedFolders = [...current.config.folders];
    $('setup-source-root').value = current.source_root; $('dashboard-source-root').value = current.source_root;
    $('interval').value = current.config.interval_hours;
    await Promise.all([loadFolders(), loadPolicy()]);
    showStep(Number(sessionStorage.getItem('knowledge-onboarding-step') || 0)); await refresh(); setInterval(refresh, 3000);
  } catch (e) { message(e.message, true); }
}
start();
