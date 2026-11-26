(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  var React = SDK.React;
  var h = React.createElement;
  var C = SDK.components;
  var kinds = [
    ['chat','LLM / Chat'], ['image','Images'], ['video','Video'],
    ['tts','Text-to-speech'], ['stt','Speech-to-text']
  ];

const DISCOVERY_TYPES = [['chat','LLM / Chat'],['embedding','Embeddings'],['image','Imagem'],['audio','Áudio'],['video','Vídeo'],['rerank','Reranking'],['moderation','Moderação'],['music','Música']]
const DISCOVERY_CAPABILITIES = [['tool_calling','Tool calling'],['reasoning','Raciocínio'],['thinking','Thinking'],['vision','Visão'],['structured_output','Saída estruturada'],['attachment','Anexos'],['temperature','Temperatura']]
const initialDiscovery = () => ({kinds: DISCOVERY_TYPES.map(x=>x[0]), capabilities: [], match:'and', configured_only:true, free_only:false, include_combos:true, min_context:0, q:''})

  var base = '/api/plugins/omniroute-media';
  function Field(label, input) {
    return h('label', {key:label, className:'block mb-3'},
      h('span', {className:'block text-sm mb-1'}, label), input);
  }
  function Panel() {
    var [filters,setFilters]=React.useState(initialDiscovery());
    var [discovery,setDiscovery]=React.useState(null);
    var [page,setPage]=React.useState(0);
    var [readToken,setReadToken]=React.useState('');
    var [clearReadToken,setClearReadToken]=React.useState(false);
    var status = React.useState(null), state = status[0], setState = status[1];
    var url = React.useState(''), currentUrl = url[0], setUrl = url[1];
    var secret = React.useState(''), key = secret[0], setKey = secret[1];
    var list = React.useState({}), catalogs = list[0], setCatalogs = list[1];
    var values = React.useState({}), selections = values[0], setSelections = values[1];
    var prefs = React.useState({}), preferences = prefs[0], setPreferences = prefs[1];
    var message = React.useState(''), feedback = message[0], setFeedback = message[1];
    var busy = React.useState(false), loading = busy[0], setLoading = busy[1];
    function refresh() {
      SDK.fetchJSON(base + '/status').then(function (s) {
        setState(s); setUrl(s.base_url || ''); setSelections(s.models || {}); setPreferences(s.preferences || {});
      }).catch(function(e){setFeedback('Operação OmniRoute falhou. Confira a conexão e as permissões.');});
    }
    React.useEffect(refresh, []);
    function send(path, data, ok) {
      setLoading(true); setFeedback('');
      SDK.fetchJSON(base + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)})
        .then(function(s){setState(s); setKey(''); setReadToken('');setClearReadToken(false); setDiscovery(null); setPage(0); setFeedback(ok + ' (a Hermes reload may be needed).');})
        .catch(function(e){setFeedback('Operação OmniRoute falhou. Confira a conexão e as permissões.');})
        .finally(function(){setKey('');setReadToken('');setClearReadToken(false);setLoading(false);});
    }
    function showModels(kind) {
      SDK.fetchJSON(base + '/models?kind=' + encodeURIComponent(kind))
        .then(function(body){
          setCatalogs(function(prev){return Object.assign({},prev,{[kind]:body.models || []});});
          var d = body.diagnostics, c = d && d.classified;
          if (d && c) setFeedback('Catalog ' + kind + ': ' + d.received + ' received; chat ' + c.chat +
            ', image ' + c.image + ', video ' + c.video + ', TTS ' + c.tts + ', STT ' + c.stt +
            ', combos ' + d.combos + ', other ' + d.other + '; duplicates removed ' + d.duplicates_removed +
            '; delivered ' + d.delivered + '; ' + d.pages + ' pages / ' + d.requests + ' requests; ' +
            d.duration_ms + ' ms; source ' + d.source + '.');
        })
        .catch(function(e){setFeedback('Operação OmniRoute falhou. Confira a conexão e as permissões.');});
    }
    function updateFilter(name,value){setFilters(old=>({...old,[name]:value}));setDiscovery(null);setPage(0);}
    function toggleFilter(name,value,checked){updateFilter(name,checked?[...new Set([...filters[name],value])]:filters[name].filter(x=>x!==value));}
    function check(label,checked,change){return h('label',{key:label,className:'flex gap-2 items-center text-sm'},h('input',{type:'checkbox',checked,disabled:loading,onChange:e=>change(e.target.checked)}),label);}
    function discoverAll(){
      if(loading||!filters.kinds.length)return;
      setLoading(true);setDiscovery(null);setPage(0);setFeedback('');
      SDK.fetchJSON(base+'/discover-models',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(filters)})
        .then(r=>{if(!r||!Array.isArray(r.models))throw Error('Invalid catalog');setDiscovery(r);})
        .catch(()=>setFeedback('Não foi possível consultar o catálogo. Confira a conexão e o token de leitura.'))
        .finally(()=>setLoading(false));
    }
    return h('div', {className:'space-y-4 max-w-3xl'},
      h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, null, 'OmniRoute connection')),
        h(C.CardContent, null,
          h('p', {className:'text-sm mb-3'}, 'Private endpoint; credentials are saved by Hermes and never returned to this page.'),
          Field('API base URL (/v1 or /api/v1)', h(C.Input, {value:currentUrl, onChange:function(e){setUrl(e.target.value)}, placeholder:'https://your-router.example/v1'})),
          Field('Replace API key (leave empty to keep existing)', h(C.Input, {type:'password', autoComplete:'new-password', value:key, onChange:function(e){setKey(e.target.value);}, placeholder:'Key configured: ' + (state && state.api_key_configured ? 'yes':'no')})),
          Field('Token de leitura (opcional)',h(C.Input,{type:'password',value:readToken,disabled:clearReadToken,autoComplete:'new-password',onChange:e=>setReadToken(e.target.value),placeholder:state?.read_token_configured?'Configurado':'Não configurado'})),
          check('Remover token de leitura',clearReadToken,v=>{setReadToken('');setClearReadToken(v);}),
          h(C.Button, {disabled:loading, onClick:function(){send('/connection',{base_url:currentUrl, api_key:key,read_token:readToken,clear_read_token:clearReadToken}, 'Connection saved');}}, 'Save connection'),
          h('p', {className:'text-xs mt-2'}, 'All settings are managed by Hermes for the selected profile. The chat provider changes only when you activate it explicitly.')
        )
      ),
      h(C.Card, null,
        h(C.CardHeader,null,h(C.CardTitle,null,'Catálogo geral — Model Discovery')),
        h(C.CardContent,null,
          Field('Pesquisa',h(C.Input,{value:filters.q,maxLength:200,disabled:loading,onChange:e=>updateFilter('q',e.target.value)})),
          ...[['configured_only','Somente configurados'],['free_only','Somente catalogados como gratuitos'],['include_combos','Incluir Combos e Auto-Combos']].map(([k,l])=>check(l,filters[k],v=>updateFilter(k,v))),
          h('h3',null,'Tipos de modelo'),
          check('Todos os tipos',filters.kinds.length===DISCOVERY_TYPES.length,v=>updateFilter('kinds',v?DISCOVERY_TYPES.map(x=>x[0]):[])),
          h('div',{className:'grid grid-cols-2 gap-1'},DISCOVERY_TYPES.map(([k,l])=>check(l,filters.kinds.includes(k),v=>toggleFilter('kinds',k,v)))),
          h('h3',null,'Capacidades'),
          check('Qualquer capacidade (sem restrição)',filters.capabilities.length===0,v=>updateFilter('capabilities',v?[]:['tool_calling'])),
          check('Selecionar todas as capacidades',filters.capabilities.length===DISCOVERY_CAPABILITIES.length,v=>updateFilter('capabilities',v?DISCOVERY_CAPABILITIES.map(x=>x[0]):[])),
          h('div',{className:'grid grid-cols-2 gap-1'},DISCOVERY_CAPABILITIES.map(([k,l])=>check(l,filters.capabilities.includes(k),v=>toggleFilter('capabilities',k,v)))),
          Field('Correspondência',h('select',{value:filters.match,disabled:loading,onChange:e=>updateFilter('match',e.target.value)},h('option',{value:'and'},'Todas (AND)'),h('option',{value:'or'},'Pelo menos uma (OR)'))),
          Field('Contexto mínimo',h('select',{value:filters.min_context,disabled:loading,onChange:e=>updateFilter('min_context',Number(e.target.value))},[0,32768,65536,131072,262144,524288,1048576].map(n=>h('option',{key:n,value:n},n?n+' tokens':'Sem restrição')))),
          h(C.Button,{disabled:loading||!filters.kinds.length,onClick:discoverAll},'Consultar catálogo'),
          h(C.Button,{disabled:loading,onClick:()=>{setFilters(initialDiscovery());setDiscovery(null);setPage(0);}},'Restaurar filtros'),
          !filters.kinds.length&&h('p',null,'Nenhum tipo selecionado.'),
          discovery&&h('div',null,h('p',null,discovery.models.length+' modelo(s) encontrados'),
            (discovery.warnings||[]).map((w,i)=>h('p',{key:i,className:'text-xs'},String(w))),
            discovery.free_summary&&h('p',{className:'text-xs'},'Catálogo global: '+String(discovery.free_summary.modelCount??'—')+' ofertas; não é saldo da conta.'),
            discovery.models.slice(page*50,page*50+50).map(m=>h('div',{key:m.id,className:'border-b py-2'},h('div',null,m.label),h('div',{className:'text-xs break-all'},(m.route_label||m.id)+' · '+m.kind+(m.free_type?' · '+m.free_type:'')+(m.provider_state?' · '+m.provider_state:'')),m.provider_usage&&h('div',{className:'text-xs'},'Provedor: '+String(m.provider_usage.successes??'—')+'/'+String(m.provider_usage.requests??'—')+' sucessos · '+String(m.provider_usage.avgLatencyMs??'—')+' ms · '+String(m.provider_usage.windowHours??'—')+' h'),['chat','image','video'].includes(m.kind)&&h(C.Button,{disabled:loading,onClick:()=>setSelections(old=>({...old,[m.kind]:m.id}))},'Usar no campo '+m.kind+' (salvar abaixo)'))),
            h(C.Button,{disabled:page===0||loading,onClick:()=>setPage(p=>p-1)},'Anterior'),
            h(C.Button,{disabled:(page+1)*50>=discovery.models.length||loading,onClick:()=>setPage(p=>p+1)},'Próxima'))
        )
      ),
      h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, null, 'Model selection')),
        h(C.CardContent, null, kinds.map(function(info){var kind=info[0]; return h('section', {key:kind, className:'mb-4'},
          h('label', {className:'block text-sm mb-1'}, info[1]),
          h('div', {className:'flex gap-2 mb-2'},
            h(C.Input, {value:selections[kind] || '', onChange:function(e){var v=e.target.value;setSelections(function(s){return Object.assign({},s,{[kind]:v});});}, placeholder:'model ID'}),
            h(C.Button, {disabled:loading || !selections[kind], onClick:function(){send('/model',{kind:kind,model:selections[kind]},'Model saved');}}, 'Save'),
            h(C.Button, {disabled:loading, onClick:function(){showModels(kind)}}, 'Discover')
          ),
          catalogs[kind] && h('select',{className:'w-full p-2 rounded border',value:'',onChange:function(e){var v=e.target.value;setSelections(function(s){return Object.assign({},s,{[kind]:v});});}},
            h('option', {value:''}, 'Select a discovered model (' + catalogs[kind].length + ')'),
            catalogs[kind].map(function(m){return h('option', {value:m.id,key:m.id}, m.route_label || m.id);})
          )
        );}) )
      ),
      h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, null, 'Additional options')),
        h(C.CardContent, null,
          [['tts_voice','TTS voice (provider-specific)'],
           ['search_provider','Search provider override (optional)'],
           ['fetch_provider','Web extract provider override (optional)']]
          .map(function(pair){var name=pair[0]; return h('div',{key:name,className:'mb-3'},
            Field(pair[1],h(C.Input,{value:preferences[name] || '',
              onChange:function(e){var v=e.target.value;setPreferences(function(old){return Object.assign({},old,{[name]:v});});},
              placeholder:'Leave empty for OmniRoute default'})),
            h(C.Button,{disabled:loading,onClick:function(){send('/preference',{kind:name,value:preferences[name] || ''},'Preference saved');}},'Save preference')
          );})
        )
      ),
      h(C.Card, null,
        h(C.CardHeader, null,h(C.CardTitle,null,'Hermes chat integration')),
        h(C.CardContent,null,
          h('p',{className:'text-sm mb-3'},state && state.native_chat_provider_active ?
            'OmniRoute is the active Hermes chat provider.' :
            'OmniRoute is not currently the Hermes chat provider. Save a chat model above first.'),
          h(C.Button,{disabled:loading || !(state && state.api_key_configured && selections.chat),
            onClick:function(){send('/activate-chat',{},'OmniRoute activated for Hermes chat');}},
            'Activate OmniRoute as Hermes chat provider')
        )
      ),
      feedback && h('p', {role:'status', className:'text-sm'}, feedback)
    );
  }
  window.__HERMES_PLUGINS__.register('omniroute-media', Panel);
})();
