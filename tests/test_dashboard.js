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
    classList: {toggle() {}, remove() {}, add() {}}, replaceChildren() {}, scrollTo() {}
  }]));
  const calls = [];
  const status = {config: {...config}, source_root: config.source_root, agent_connected: connected, agent_paired: connected,
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
  assert.match(elements['setup-source-status'].textContent, /\/mnt\/documents.*disconnected/i);
  assert.equal(elements['setup-host-connection'].open, true);
});

test('Next keeps setup on the folder step and explains a missing host service immediately', async () => {
  const {elements, calls, context} = dashboard(legacy);
  elements['setup-source-root'].value = '/home/user/My documents';
  await vm.runInContext('saveSource(true, true)', context);
  assert.equal(calls.some(x => x.route === '/api/onboarding/progress'), false);
  assert.equal(calls.some(x => x.route === '/api/agent/refresh'), false);
  assert.match(elements.message.textContent, /Connect the host service/);
});

test('Next verifies the selected host folder before advancing to indexing policy', async () => {
  const {elements, calls, context} = dashboard(legacy, true);
  elements['setup-source-root'].value = '/mnt/documents';
  await vm.runInContext('saveSource(true, true)', context);
  const sync = calls.findIndex(x => x.route === '/api/agent/refresh');
  const advance = calls.findIndex(x => x.route === '/api/onboarding/progress');
  assert.ok(sync >= 0 && advance > sync);
  assert.equal(calls[advance].body.step, 3);
  assert.match(elements['setup-source-status'].textContent, /Folder ready.*2 eligible documents/);
});

test('changing access preference preserves the document path being edited', () => {
  const {elements, context} = dashboard(legacy);
  elements['setup-source-root'].value = '/mnt/custom-documents';
  context.document.activeElement = {id: 'setup-source-mode', value: 'host_agent'};
  vm.runInContext('sourceModeChanged()', context);
  assert.equal(elements['setup-source-root'].value, '/mnt/custom-documents');
  assert.equal(elements['dashboard-source-mode'].value, 'host_agent');
});
