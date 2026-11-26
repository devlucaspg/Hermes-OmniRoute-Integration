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
  var base = '/api/plugins/omniroute-media';
  function Field(label, input) {
    return h('label', {key:label, className:'block mb-3'},
      h('span', {className:'block text-sm mb-1'}, label), input);
  }
  function Panel() {
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
      }).catch(function(e){setFeedback(String(e.message || e));});
    }
    React.useEffect(refresh, []);
    function send(path, data, ok) {
      setLoading(true); setFeedback('');
      SDK.fetchJSON(base + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)})
        .then(function(s){setState(s); setKey(''); setFeedback(ok + ' (a Hermes reload may be needed).');})
        .catch(function(e){setFeedback(String(e.message || e));})
        .finally(function(){setLoading(false);});
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
        .catch(function(e){setFeedback(String(e.message || e));});
    }
    return h('div', {className:'space-y-4 max-w-3xl'},
      h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, null, 'OmniRoute connection')),
        h(C.CardContent, null,
          h('p', {className:'text-sm mb-3'}, 'Private endpoint; credentials are saved by Hermes and never returned to this page.'),
          Field('API base URL (/v1 or /api/v1)', h(C.Input, {value:currentUrl, onChange:function(e){setUrl(e.target.value)}, placeholder:'https://your-router.example/v1'})),
          Field('Replace API key (leave empty to keep existing)', h(C.Input, {type:'password', autoComplete:'new-password', value:key, onChange:function(e){setKey(e.target.value);}, placeholder:'Key configured: ' + (state && state.api_key_configured ? 'yes':'no')})),
          h(C.Button, {disabled:loading, onClick:function(){send('/connection',{base_url:currentUrl, api_key:key}, 'Connection saved');}}, 'Save connection'),
          h('p', {className:'text-xs mt-2'}, 'All settings are managed by Hermes for the selected profile. The chat provider changes only when you activate it explicitly.')
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
            catalogs[kind].map(function(m){return h('option', {value:m.id,key:m.id}, m.label);})
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
