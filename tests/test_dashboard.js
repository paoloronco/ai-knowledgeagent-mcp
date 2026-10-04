const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const ui = path.join(__dirname, '../knowledge-mcp/mcp');
const script = fs.readFileSync(path.join(ui, 'app.js'), 'utf8').replace(/start\(\);\s*$/, '');
const html = fs.readFileSync(path.join(ui, 'webui.html'), 'utf8');

function dashboard(config, connected = false, pathname = '/dashboard/indexing') {
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(([, id]) => [id, {
    value: '', textContent: '', children: [], open: false, disabled: false,
    classList: {
      classes: new Set(),
      toggle(name, force) { if (force ?? !this.classes.has(name)) this.classes.add(name); else this.classes.delete(name); },
      remove(name) { this.classes.delete(name); }, add(name) { this.classes.add(name); },
      contains(name) { return this.classes.has(name); }
    }, replaceChildren(...items) { this.children = items; }, append(...items) { this.children.push(...items); }, scrollTo() {},
    removeAttribute(name) { if (name === 'value') this.value = undefined; }, setAttribute() {}, showModal() { this.open = true; }, close() { this.open = false; }
  }]));
  const calls = [];
  const makeClassList = () => ({classes: new Set(), toggle(name, force) { if (force) this.classes.add(name); else this.classes.delete(name); }, contains(name) { return this.classes.has(name); }});
  const panels = [...html.matchAll(/class="card dashboard-panel" data-page="([^"]+)"/g)].map(([, page]) => ({dataset: {page}, classList: makeClassList()}));
  const links = [...html.matchAll(/data-nav-page="([^"]+)"/g)].map(([, navPage]) => ({dataset: {navPage}, classList: makeClassList()}));
  const steps = [...html.matchAll(/class="step" data-step="([^"]+)"/g)].map(([, step]) => ({dataset: {step}, classList: makeClassList()}));
  const initialRoot = config.source_mode === 'host_agent' ? config.host_root : config.source_root;
  const status = {config: {sync_request: 0, ...config}, source_root: config.source_root, agent_connected: connected, agent_paired: connected, agent_managed: true,
    source_ready: connected || config.source_mode === 'container', agent_file_count: 2, agent_sync_request_completed: 1,
    scan_complete: false, scan_ready: false, scan_running: false, scan_checked: 0, scan_eligible_count: 0, scan_eligible_preview: [],
    document_paths: initialRoot ? [initialRoot] : []};
  const location = {pathname};
  const context = vm.createContext({
    document: {getElementById: id => elements[id] || null, querySelectorAll: selector => selector === '.dashboard-panel' ? panels : selector === '[data-nav-page]' ? links : selector === '.step' ? steps : [],
      createElement: () => ({className: '', textContent: '', children: [], append(...nodes) { this.children.push(...nodes); }, setAttribute() {}}), activeElement: null},
    token: 'test-control-token', Date, clearTimeout() {}, location, history: {pushState(_, __, url) { location.pathname = url; }, replaceState(_, __, url) { location.pathname = url; }},
    setTimeout(callback, delay) { if (delay === 2000) callback(); },
    async fetch(route, options) {
      const body = options?.body ? JSON.parse(options.body) : null;
      calls.push({route, body});
      let result;
      if (route === '/api/config') {
        const paths = body.document_paths;
        status.document_paths = paths || status.document_paths;
        status.config = {...status.config, source_selection: body.source_selection, host_root: paths?.[0] || status.config.host_root, source_mode: 'host_agent'};
        status.source_root = status.config.source_root;
        result = status.config;
      } else if (route === '/api/status') result = status;
      else if (route === '/api/folder/check') result = {reachable: true, mode: 'host_agent'};
      else if (route === '/api/scan/files') result = {files: ['notes/first.md', 'notes/second.md', 'notes/third.md']};
      else if (route === '/api/agent/refresh') result = {sync_request: 1};
      else if (route === '/api/scan') result = {requested: true};
      else if (route === '/api/onboarding/progress') result = {setup_step: body.step};
      else if (route === '/api/onboarding/skip-index') {
        status.config = {...status.config, onboarding_complete: true, setup_step: 7, initial_index_skipped: true};
        result = {complete: true, initial_index_skipped: true};
      }
      else if (route === '/api/index') result = {started: true};
      else throw Error('Unexpected request: ' + route);
      return {ok: true, json: async () => result};
    }
  });
  vm.runInContext(script, context);
  context.initial = status;
  vm.runInContext('current = initial; wizardStep = 2; fillSourceInputs();', context);
  return {elements, calls, context, status, panels, links, steps, location};
}

const legacy = {source_selection: 'auto', source_mode: 'host_agent', source_root: '/data/host-documents', host_root: '', setup_step: 2, folders: []};

test('adding a folder checks reachability and shows it in the list', async () => {
  const {elements, calls, context} = dashboard(legacy);
  elements['setup-source-root'].value = '/mnt/documents';
  await vm.runInContext('addFolder(true)', context);
  assert.deepEqual(calls.find(x => x.route === '/api/folder/check').body, {path: '/mnt/documents', source_selection: 'auto'});
  assert.deepEqual(calls.find(x => x.route === '/api/config').body, {
    document_paths: ['/mnt/documents'], source_selection: 'auto', interval_hours: 0
  });
  assert.equal(elements['setup-folder-list'].children[0].children[0].textContent, '/mnt/documents');
  assert.equal(elements['setup-source-root'].value, '');
  assert.doesNotMatch(html, /host_agent\.py install|Generate pairing key|Download the host service/);
});

test('folders can be removed, then Next advances to policy without scanning', async () => {
  const {elements, calls, context} = dashboard(legacy);
  elements['setup-source-root'].value = '/home/user/My documents';
  await vm.runInContext('addFolder(true)', context);
  elements['setup-source-root'].value = '/home/user/Other documents';
  await vm.runInContext('addFolder(true)', context);
  assert.equal(elements['setup-folder-list'].children.length, 2);
  await vm.runInContext("removeFolder('/home/user/My documents')", context);
  assert.equal(elements['setup-folder-list'].children.length, 1);
  await vm.runInContext('advanceFolders()', context);
  assert.equal(calls.find(x => x.route === '/api/onboarding/progress').body.step, 3);
  assert.equal(calls.some(x => x.route === '/api/scan'), false);
});

test('eligible documents step shows scan progress and enables Next only with matches', async () => {
  const {elements, context, status} = dashboard({...legacy, source_mode: 'host_agent', host_root: '/mnt/documents'}, true);
  status.source_ready = false;
  status.scan_running = true;
  status.scan_checked = 12;
  status.scan_eligible_count = 2;
  status.agent_progress = {phase: 'scanning', checked: 12, eligible: 2, completed: 0, total: 0};
  await vm.runInContext('refresh()', context);
  assert.match(elements['setup-scan-status'].textContent, /Scanning host folder: 12 files checked, 2 eligible/);
  assert.equal(elements['setup-eligible-list'].children.length, 0);
  assert.equal(elements['setup-sync-progress'].classList.contains('hidden'), false);
  status.agent_progress = {phase: 'transferring', checked: 20, completed: 2, total: 4};
  await vm.runInContext('refresh()', context);
  assert.match(elements['setup-scan-status'].textContent, /2 of 4/);
  assert.equal(elements['setup-sync-progress'].value, 50);
  status.scan_complete = true;
  status.scan_running = false;
  status.scan_eligible_count = 0;
  status.agent_progress = null;
  await vm.runInContext('refresh()', context);
  assert.equal(elements['setup-sync-progress'].classList.contains('hidden'), true);
  assert.equal(elements['scan-next'].disabled, true);
  status.scan_ready = true;
  status.scan_eligible_count = 2;
  status.scan_eligible_preview = ['notes/first.md', 'notes/second.md'];
  await vm.runInContext('refresh()', context);
  assert.equal(elements['scan-next'].disabled, false);
  assert.deepEqual(elements['setup-eligible-list'].children.map(x => x.textContent), ['notes/first.md', 'notes/second.md']);
  await vm.runInContext('openEligibleFiles()', context);
  assert.equal(elements['eligible-dialog'].open, true);
  assert.match(elements['eligible-all'].textContent, /notes\/third\.md/);
});

test('changing access preference preserves the document path being edited', () => {
  const {elements, context} = dashboard(legacy);
  elements['setup-source-root'].value = '/mnt/custom-documents';
  context.document.activeElement = {id: 'setup-source-mode', value: 'host_agent'};
  vm.runInContext('sourceModeChanged()', context);
  assert.equal(elements['setup-source-root'].value, '/mnt/custom-documents');
  assert.equal(elements['dashboard-source-mode'].value, 'host_agent');
});

test('Service health shows Start Qdrant only while managed Qdrant is unavailable', async () => {
  const {elements, context, status} = dashboard(legacy);
  status.qdrant_managed = true;
  status.qdrant_ready = true;
  await vm.runInContext('refresh()', context);
  assert.equal(elements['wizard-qdrant'].classList.contains('hidden'), true);
  status.qdrant_ready = false;
  await vm.runInContext('refresh()', context);
  assert.equal(elements['wizard-qdrant'].classList.contains('hidden'), false);
  status.qdrant_managed = false;
  await vm.runInContext('refresh()', context);
  assert.equal(elements['wizard-qdrant'].classList.contains('hidden'), true);
});

test('onboarding continues with dashboard login disabled', async () => {
  const {elements, calls, context} = dashboard({...legacy, setup_step: 0});
  elements['login-enabled'].checked = false;
  vm.runInContext('wizardStep = 0', context);
  await vm.runInContext('setupSecurity()', context);
  assert.equal(calls.some(x => x.route === '/api/security'), false);
  assert.equal(calls.find(x => x.route === '/api/onboarding/progress').body.step, 1);
  assert.doesNotMatch(html, /Enable login to select folders on the Docker host/);
});

test('password field is shown only when login is enabled', () => {
  const {elements, context} = dashboard({...legacy, setup_step: 0});
  elements['login-enabled'].checked = false;
  vm.runInContext('toggleSetupPassword()', context);
  assert.equal(elements['login-password-fields'].classList.contains('hidden'), true);
  elements['login-enabled'].checked = true;
  vm.runInContext('toggleSetupPassword()', context);
  assert.equal(elements['login-password-fields'].classList.contains('hidden'), false);
});

test('successful dry run enables Continue to indexing', async () => {
  const {elements, context, status, calls} = dashboard({...legacy, setup_step: 5}, true);
  vm.runInContext('wizardStep = 5', context);
  status.last_result = {dry_run: true, exit_code: 0, finished_at: 1};
  await vm.runInContext('refresh()', context);
  assert.equal(elements['dry-next'].disabled, false);
  assert.match(elements['dry-result'].textContent, /Dry run passed/);
  await vm.runInContext('nextStep()', context);
  assert.equal(calls.find(x => x.route === '/api/onboarding/progress').body.step, 6);
});

test('indexing progress is visible alone until initial indexing finishes', async () => {
  const {elements, context, status, panels, location} = dashboard({...legacy, onboarding_complete: true, setup_step: 6}, true);
  status.index_running = true;
  status.index_progress = {stage: 'indexing', completed: 25, total: 100};
  await vm.runInContext('refresh()', context);
  assert.equal(elements['setup-progress-card'].classList.contains('hidden'), true);
  assert.equal(elements['dashboard-nav'].classList.contains('hidden'), true);
  assert.match(elements['index-progress-label'].textContent, /25 of 100 \(25%\)/);
  assert.equal(panels.filter(x => x.classList.contains('active')).map(x => x.dataset.page).join(','), 'indexing');
  status.index_running = false;
  status.config.setup_step = 7;
  await vm.runInContext('refresh()', context);
  vm.runInContext("goDashboardPage('services', true)", context);
  assert.equal(location.pathname, '/dashboard/services');
  assert.equal(panels.filter(x => x.classList.contains('active')).map(x => x.dataset.page).join(','), 'services');
});

test('setup routes can be opened directly and navigation updates the URL', () => {
  const {context, location, steps} = dashboard({...legacy, setup_step: 3}, false, '/setup/health');
  vm.runInContext('syncRoute(current)', context);
  assert.equal(location.pathname, '/setup/health');
  assert.equal(steps.find(x => x.classList.contains('active')).dataset.step, '1');
  vm.runInContext('showStep(2)', context);
  assert.equal(location.pathname, '/setup/folders');
  vm.runInContext('backStep()', context);
  assert.equal(location.pathname, '/setup/health');
  location.pathname = '/setup/indexing';
  vm.runInContext('syncRoute(current)', context);
  assert.equal(location.pathname, '/setup/policy');
  assert.equal(steps.find(x => x.classList.contains('active')).dataset.step, '3');
});

test('skipping initial indexing opens the dashboard and keeps indexing available', async () => {
  const {elements, calls, context, status, panels, location} = dashboard({...legacy, setup_step: 6}, true, '/setup/indexing');
  await vm.runInContext('skipInitialIndex()', context);
  assert.equal(calls.some(x => x.route === '/api/onboarding/skip-index'), true);
  assert.equal(location.pathname, '/dashboard');
  assert.equal(status.config.initial_index_skipped, true);
  assert.equal(elements['dashboard-nav'].classList.contains('hidden'), false);
  assert.equal(panels.find(x => x.classList.contains('active')).dataset.page, 'overview');
  assert.match(elements['overview-state'].textContent, /postponed/);
  vm.runInContext("goDashboardPage('indexing', true)", context);
  assert.equal(location.pathname, '/dashboard/indexing');
  assert.equal(elements['run'].textContent, 'Start initial indexing');
  await vm.runInContext('runIndex(false)', context);
  assert.equal(calls.some(x => x.route === '/api/index' && x.body.dry_run === false), true);
});
