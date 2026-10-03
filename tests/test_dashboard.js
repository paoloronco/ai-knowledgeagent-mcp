const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const ui = path.join(__dirname, '../knowledge-mcp/mcp');
const script = fs.readFileSync(path.join(ui, 'app.js'), 'utf8').replace(/start\(\);\s*$/, '');
const html = fs.readFileSync(path.join(ui, 'webui.html'), 'utf8');

function dashboard(config, connected = false) {
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(([, id]) => [id, {
    value: '', textContent: '', children: [], open: false,
    classList: {
      classes: new Set(),
      toggle(name, force) { if (force ?? !this.classes.has(name)) this.classes.add(name); else this.classes.delete(name); },
      remove(name) { this.classes.delete(name); }, add(name) { this.classes.add(name); },
      contains(name) { return this.classes.has(name); }
    }, replaceChildren() {}, scrollTo() {}, removeAttribute(name) { if (name === 'value') this.value = undefined; }
  }]));
  const calls = [];
  const status = {config: {sync_request: 0, ...config}, source_root: config.source_root, agent_connected: connected, agent_paired: connected, agent_managed: true,
    source_ready: connected || config.source_mode === 'container', agent_file_count: 2, agent_sync_request_completed: 1};
  const context = vm.createContext({
    document: {getElementById: id => elements[id] || null, querySelectorAll: () => [],
      createElement: () => ({className: '', textContent: ''}), activeElement: null},
    token: 'test-control-token', Date, clearTimeout() {},
    setTimeout(callback, delay) { if (delay === 2000) callback(); },
    async fetch(route, options) {
      const body = options?.body ? JSON.parse(options.body) : null;
      calls.push({route, body});
      let result;
      if (route === '/api/config') {
        status.config = {...status.config, source_selection: body.source_selection, host_root: body.document_root, source_mode: 'host_agent'};
        status.source_root = status.config.source_root;
        result = status.config;
      } else if (route === '/api/status') result = status;
      else if (route === '/api/agent/refresh') result = {sync_request: 1};
      else if (route === '/api/onboarding/progress') result = {setup_step: body.step};
      else throw Error('Unexpected request: ' + route);
      return {ok: true, json: async () => result};
    }
  });
  vm.runInContext(script, context);
  context.initial = status;
  vm.runInContext('current = initial; wizardStep = 2; fillSourceInputs();', context);
  return {elements, calls, context, status};
}

const legacy = {source_selection: 'auto', source_mode: 'container', source_root: '/data/documents', host_root: '', setup_step: 2};

test('saving an arbitrary root uses automatic selection despite a legacy container source', async () => {
  const {elements, calls, context} = dashboard(legacy);
  elements['setup-source-root'].value = '/mnt/documents';
  await vm.runInContext('saveSource(false, true)', context);
  assert.deepEqual(calls.find(x => x.route === '/api/config').body, {
    document_root: '/mnt/documents', source_selection: 'auto', folders: [''], interval_hours: 0
  });
  assert.equal(elements['dashboard-source-root'].value, '/mnt/documents');
  assert.match(elements['setup-source-status'].textContent, /\/mnt\/documents.*Automatic host agent/i);
  assert.doesNotMatch(html, /host_agent\.py install|Generate pairing key|Download the host service/);
});

test('Next keeps setup on the folder step and explains a missing host service immediately', async () => {
  const {elements, calls, context} = dashboard(legacy);
  elements['setup-source-root'].value = '/home/user/My documents';
  await vm.runInContext('saveSource(true, true)', context);
  assert.equal(calls.some(x => x.route === '/api/onboarding/progress'), false);
  assert.equal(calls.some(x => x.route === '/api/agent/refresh'), false);
  assert.match(elements.message.textContent, /host-agent Docker service/);
});

test('Next verifies the selected host folder before advancing to indexing policy', async () => {
  const {elements, calls, context, status} = dashboard(legacy, true);
  status.source_ready = false;
  status.agent_sync_request_completed = -1;
  let polls = 0;
  context.setTimeout = (resolve, delay) => {
    if (delay === 2000) {
      polls += 1;
      status.source_ready = true;
      status.agent_sync_request_completed = 0;
      resolve();
    }
  };
  elements['setup-source-root'].value = '/mnt/documents';
  await vm.runInContext('saveSource(true, true)', context);
  const sync = calls.findIndex(x => x.route === '/api/agent/refresh');
  const advance = calls.findIndex(x => x.route === '/api/onboarding/progress');
  assert.equal(sync, -1);
  assert.equal(polls, 1);
  assert.ok(advance >= 0);
  assert.equal(calls[advance].body.step, 3);
  assert.match(elements['setup-source-status'].textContent, /Folder ready.*2 eligible documents/);
});

test('section 3 shows scan and transfer progress from the host agent', async () => {
  const {elements, context, status} = dashboard({...legacy, source_mode: 'host_agent', host_root: '/mnt/documents'}, true);
  status.source_ready = false;
  status.agent_progress = {phase: 'scanning', checked: 12, completed: 0, total: 0};
  await vm.runInContext('refresh()', context);
  assert.match(elements['setup-source-status'].textContent, /Scanning host folder: 12 files checked/);
  assert.equal(elements['setup-sync-progress'].classList.contains('hidden'), false);
  status.agent_progress = {phase: 'transferring', checked: 20, completed: 2, total: 4};
  await vm.runInContext('refresh()', context);
  assert.match(elements['setup-source-status'].textContent, /2 of 4/);
  assert.equal(elements['setup-sync-progress'].value, 50);
  status.source_ready = true;
  status.agent_progress = null;
  await vm.runInContext('refresh()', context);
  assert.equal(elements['setup-sync-progress'].classList.contains('hidden'), true);
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
