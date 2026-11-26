'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../backend/desktop/plugin.js'), 'utf8');

function build({ supportsSettingsPage = true, supportsModelMenu = true, backend = {} } = {}) {
  const state = [];
  let next = 0;
  let effects = [];
  const calls = [];
  let settingsPage;
  const contributions = [];
  const fakeSdk = { SETTINGS_PLUGINS_AREA: 'settings.plugins', ...(supportsModelMenu ? { MODEL_MENU_ROW_AREA: 'modelMenu.row' } : {}) };
  const mockHooks = {
    useState(initial) {
      const i = next++;
      if (!(i in state)) state[i] = initial;
      return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }];
    },
    useEffect(callback) { effects.push(callback); },
  };
  const element = (type, props = {}, key) => ({ type, props, key });
  let js = source.replace(/^import .+$/gm, '');
  js = js.replace('export default {', 'globalThis.__plugin = {');
  const sandbox = {
    ...mockHooks, jsx: element, jsxs: element, sdk: fakeSdk,
  };
  vm.runInNewContext(js, sandbox, { filename: 'desktop/plugin.js', timeout: 2500 });
  const plugin = sandbox.__plugin;
  const ctx = {
    rest: (endpoint, options) => {
      calls.push({ endpoint, options });
      if (!(endpoint in backend)) return Promise.reject(Object.assign(new Error('secret-in-remote-error'), { status: 404 }));
      const value = backend[endpoint];
      return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
    },
    registerSettingsPage: supportsSettingsPage ? value => { settingsPage = value; } : undefined,
    register(value) { contributions.push(value); if (value.area === 'settings.plugins') settingsPage = value; },
  };
  plugin.register(ctx);

  function expand(node) {
    if (!node || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map(expand);
    if (typeof node.type === 'function') return expand(node.type(node.props));
    return { ...node, props: { ...node.props, children: expand(node.props?.children) } };
  }
  function render() { next = 0; effects = []; return expand(settingsPage.render()); }
  function flatten(node, out = []) {
    if (!node || typeof node !== 'object') return out;
    if (Array.isArray(node)) { node.forEach(n => flatten(n, out)); return out; }
    out.push(node);
    flatten(node.props?.children, out);
    return out;
  }
  return { plugin, ctx, calls, contributions, page: settingsPage, render, effects: () => effects,
           flatten, state };
}

const status = {
  base_url: 'https://router.example/api/v1', api_key_configured: true,
  models: { chat: 'chat/fast', image: '', video: '', tts: '', stt: '' },
  preferences: { tts_voice: 'pt-BR', search_provider: '', fetch_provider: '' },
  native_chat_provider_active: false,
};
function tick() { return new Promise(resolve => setImmediate(resolve)); }

test('correct plugin identity, opt-in, and SDK-native settings registration', () => {
  const c = build();
  assert.equal(c.plugin.id, 'omniroute-media');
  assert.equal(c.plugin.defaultEnabled, false);
  assert.equal(c.page.title, 'OmniRoute');
  assert.equal(c.page.id, 'settings');
});

test('older host fallback uses SDK settings area', () => {
  const c = build({ supportsSettingsPage: false });
  assert.equal(c.page.area, 'settings.plugins');
  assert.equal(c.page.title, 'OmniRoute');
});

test('initial GET fetches profile-scoped backend without reaching OmniRoute from Desktop', async () => {
  const c = build({ backend: {'/status': status } });
  c.render();
  for (const effect of c.effects()) effect();
  await tick();
  assert.equal(c.calls.length, 1);
  assert.equal(c.calls[0].endpoint, '/status');
  const tree = c.render();
  assert.ok(JSON.stringify(tree).includes('chat/fast'));
  assert.ok(JSON.stringify(tree).includes('Credencial configurada'));
});

test('reload status uses GET, not POST', async () => {
  const c = build({ backend: {'/status': status } });
  c.render(); c.effects()[0](); await tick();
  const nodes = c.flatten(c.render());
  const button = nodes.find(n => n.type === 'button' && n.props?.children === 'Atualizar estado');
  assert.ok(button);
  button.props.onClick(); await tick();
  assert.equal(c.calls.at(-1).endpoint, '/status');
  assert.equal(c.calls.at(-1).options, undefined);
});

test('explicit activate-chat uses POST only when user clicks', async () => {
  const c = build({ backend: {'/status': status, '/activate-chat': {...status, native_chat_provider_active: true} } });
  c.render(); c.effects()[0](); await tick();
  assert.equal(c.calls.some(x => x.endpoint === '/activate-chat'), false);
  const btn = c.flatten(c.render()).find(n => n.type === 'button' && n.props?.children === 'Ativar OmniRoute para chat');
  assert.ok(btn);
  assert.equal(btn.props.disabled, false);
  btn.props.onClick(); await tick();
  assert.equal(c.calls.at(-1).endpoint, '/activate-chat');
  assert.equal(c.calls.at(-1).options.method, 'POST');
});

test('backend errors do not display remote error contents', async () => {
  const c = build();
  c.render(); c.effects()[0](); await tick();
  const tree = c.render();
  assert.ok(JSON.stringify(tree).includes('API OmniRoute não disponível'));
  assert.equal(JSON.stringify(tree).includes('secret-in-remote-error'), false);
});

test('no direct network, credential persistence or privileged renderer APIs', () => {
  assert.ok(source.includes("from '@hermes/plugin-sdk'"));
  for (const unsafe of ['localStorage', 'sessionStorage', 'ctx.storage', 'window.', 'fetch(', 'eval(', 'new Function(', 'http://n8n', 'innerHTML', 'document.']) {
    assert.equal(source.includes(unsafe), false, 'unexpected: ' + unsafe);
  }
});


test('native model-menu badge identifies OmniRoute routing prefix only', () => {
  const c = build();
  const entry = c.contributions.find(x => x.area === 'modelMenu.row');
  assert.ok(entry);
  const decorate = entry.data.decorate;
  for (const [model, expected] of [
    ['nvidia/nvidia/nemotron', 'nvidia'],
    ['openrouter/nvidia/nemotron', 'openrouter'],
    ['groq/groq/compound', 'groq'],
    ['cf/example/model', 'cf'],
    ['auto/fast', 'auto'],
    ['Combo-1', 'Sem prefixo'],
  ]) {
    assert.equal(decorate({provider:'omniroute', model, label:'Friendly'}).badge, expected);
  }
  assert.equal(decorate({provider:'openrouter', model:'nvidia/nemotron'}), null);
  assert.equal(decorate({provider:'omniroute', model:''}), null);
  assert.equal(c.calls.length, 0, 'decorating must not contact a backend');
});

test('older desktop without the official model-menu hook still registers settings', () => {
  const c = build({supportsModelMenu:false});
  assert.equal(c.page.id, 'settings');
  assert.equal(c.contributions.some(x => x.area === 'modelMenu.row'), false);
});

test('settings show routing labels but keep the exact model id on selection', async () => {
  const c = build({backend: {
    '/status':status,
    '/models?kind=chat': {models:[
      {id:'openrouter/nvidia/nemotron', label:'Nemotron', route_label:'openrouter/nvidia/nemotron'},
      {id:'Combo-1', label:'Combo 1', route_label:'combo/Combo-1'},
      {id:'groq/legacy', label:'Legacy'},
    ]},
    '/model':status,
  }});
  c.render(); c.effects()[0](); await tick();
  const discover = c.flatten(c.render()).find(n => n.type === 'button' && n.props?.children === 'Buscar modelos');
  discover.props.onClick(); await tick();
  const nodes = c.flatten(c.render());
  const opts = nodes.filter(n => n.type === 'option');
  assert.ok(opts.some(n => n.props.value === 'Combo-1' && n.props.children === 'combo/Combo-1'));
  assert.ok(opts.some(n => n.props.value === 'openrouter/nvidia/nemotron' && n.props.children === 'openrouter/nvidia/nemotron'));
  assert.ok(opts.some(n => n.props.value === 'groq/legacy' && n.props.children === 'groq/legacy'));
  const select = nodes.find(n => n.type === 'select' && n.props['aria-label'] === 'Modelos disponíveis: LLM / Chat');
  assert.ok(select, 'chat model selector');
  select.props.onChange({target:{value:'Combo-1'}});
  const save = c.flatten(c.render()).find(n => n.type === 'button' && n.props?.children === 'Salvar');
  save.props.onClick(); await tick();
  assert.equal(c.calls.at(-1).options.body.model, 'Combo-1');
});

test('discovery multi-select sends explicit filters and does not activate chat', async () => {
  const c = build({ backend: {'/status': status, '/discover-models': {models:[{id:'p/llm',label:'Example',kind:'chat'}],warnings:[]}} });
  c.render(); c.effects()[0](); await tick();
  let nodes = c.flatten(c.render());
  function toggle(label, checked) {
    const node = c.flatten(c.render()).find(n => n.type==='label' && Array.isArray(n.props.children) && n.props.children.includes(label));
    assert.ok(node, label);
    node.props.children.find(n=>n?.type==='input').props.onChange({target:{checked}});
  }
  toggle('Todos os tipos', false);
  assert.equal(c.flatten(c.render()).find(n=>n.type==='button'&&n.props.children==='Consultar catálogo').props.disabled,true);
  toggle('LLM / Chat', true);
  toggle('Embeddings', true);
  toggle('Tool calling', true);
  toggle('Visão', true);
  nodes = c.flatten(c.render());
  const mode = nodes.find(n=>n.type==='select'&&n.props.value==='and');
  mode.props.onChange({target:{value:'or'}});
  c.flatten(c.render()).find(n=>n.type==='button'&&n.props.children==='Consultar catálogo').props.onClick();
  await tick();
  const call = c.calls.at(-1);
  assert.equal(call.endpoint,'/discover-models');
  assert.equal(JSON.stringify(call.options.body.kinds),JSON.stringify(['chat','embedding']));
  assert.equal(JSON.stringify(call.options.body.capabilities),JSON.stringify(['tool_calling','vision']));
  assert.equal(call.options.body.match,'or');
  assert.equal(c.calls.some(x=>x.endpoint==='/activate-chat'),false);
  assert.ok(JSON.stringify(c.render()).includes('p/llm'));
});

test('Dashboard multi-select uses authenticated plugin REST and preserves routing IDs', async () => {
  const dashboard = fs.readFileSync(path.resolve(__dirname, '../backend/dashboard/dist/index.js'), 'utf8');
  const state = []; let next = 0, effects = [], panel;
  const calls = [];
  const h = (type, props, ...children) => ({type, props:{...(props||{}), children}});
  const components = Object.fromEntries(['Card','CardHeader','CardTitle','CardContent','Input','Button'].map(x=>[x,x]));
  const SDK = {React:{createElement:h,useState(initial){const i=next++;if(!(i in state))state[i]=initial;return [state[i],v=>{state[i]=typeof v==='function'?v(state[i]):v;}];},useEffect(fn){effects.push(fn);}},components,
    fetchJSON(url,options){calls.push({url,options});return Promise.resolve(url.endsWith('/status')?status:{models:[{id:'provider/org/model',route_label:'provider/org/model',label:'Example',kind:'chat'}],warnings:[]});}};
  vm.runInNewContext(dashboard,{window:{__HERMES_PLUGIN_SDK__:SDK,__HERMES_PLUGINS__:{register(id,fn){assert.equal(id,'omniroute-media');panel=fn;}}}}, {timeout:2500});
  function render(){next=0;effects=[];return panel();}
  function flatten(n,out=[]){if(!n||typeof n!=='object')return out;if(Array.isArray(n)){n.forEach(x=>flatten(x,out));return out;}out.push(n);flatten(n.props?.children,out);return out;}
  render(); effects[0](); await tick();
  function toggle(label, checked){const n=flatten(render()).find(n=>n.type==='label'&&n.props.children.includes(label));assert.ok(n,label);n.props.children.find(x=>x?.type==='input').props.onChange({target:{checked}});}
  toggle('Todos os tipos',false);
  toggle('LLM / Chat',true);toggle('Imagem',true);toggle('Tool calling',true);
  const query=flatten(render()).find(n=>n.type==='Button'&&n.props.children.includes('Consultar catálogo'));
  query.props.onClick();await tick();
  const call=calls.at(-1);assert.ok(call.url.endsWith('/discover-models'));assert.equal(call.options.method,'POST');
  const body=JSON.parse(call.options.body);assert.deepEqual(body.kinds,['chat','image']);assert.deepEqual(body.capabilities,['tool_calling']);
  assert.ok(JSON.stringify(render()).includes('provider/org/model'));
  assert.equal(calls.some(x=>x.url.endsWith('/activate-chat')),false);
});


test('Desktop footer identifies its own version independently of remote backend', async () => {
  const c=build({backend:{'/status':{...status,plugin_version:'0.4.0-beta.2'}}});
  c.render();c.effects()[0]();await tick();
  const footer=c.flatten(c.render()).find(n=>n.type==='footer');
  assert.ok(footer);
  const content=JSON.stringify(footer);
  assert.ok(content.includes('Interface Desktop v0.4.0-beta.3'));
  assert.ok(content.includes('Backend conectado: v0.4.0-beta.2'));
  assert.ok(content.includes('Versões diferentes'));
});

test('Dashboard and Desktop version markers match the package manifest', () => {
  const root=path.resolve(__dirname,'..');
  const manifest=fs.readFileSync(path.join(root,'backend/plugin.yaml'),'utf8');
  const version=manifest.match(/^version:\s*"([^"]+)"/m)[1];
  const dashboard=fs.readFileSync(path.join(root,'backend/dashboard/dist/index.js'),'utf8');
  const api=fs.readFileSync(path.join(root,'backend/dashboard/plugin_api.py'),'utf8');
  const dashManifest=JSON.parse(fs.readFileSync(path.join(root,'backend/dashboard/manifest.json'),'utf8'));
  assert.equal(dashManifest.version,version);
  assert.ok(source.includes("UI_VERSION = '"+version+"'"));
  assert.ok(dashboard.includes("UI_VERSION = '"+version+"'"));
  assert.ok(api.includes("PLUGIN_VERSION = '"+version+"'"));
});
