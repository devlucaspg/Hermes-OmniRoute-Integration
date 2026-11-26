"""Synthetic contract fixtures; no private catalog or usage telemetry."""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib import request, error  # preserve stdlib exception identity during module loading

from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parents[1]
def load_api():
    modules = {
        'agent': types.ModuleType('agent'),
        'agent.secret_scope': types.ModuleType('agent.secret_scope'),
        'hermes_cli': types.ModuleType('hermes_cli'),
        'hermes_cli.config': types.ModuleType('hermes_cli.config'),
    }
    modules['agent.secret_scope'].get_secret_str = lambda *a: ''
    for name in ('get_env_value','save_env_value','save_env_value_secure','load_config','set_config_value'):
        setattr(modules['hermes_cli.config'], name, lambda *a: {})
    spec = importlib.util.spec_from_file_location('discovery_test_api', ROOT/'backend/dashboard/plugin_api.py')
    mod = importlib.util.module_from_spec(spec)
    replacements = {**modules, 'discovery_test_api': mod}
    previous = {name: sys.modules.get(name) for name in replacements}
    try:
        sys.modules.update(replacements)
        spec.loader.exec_module(mod)
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    return mod

api = load_api()
rows = [
    {'id':'p/org/a','owned_by':'p','root':'org/a','capabilities':{'tool_calling':True,'vision':True},'context_length':65536},
    {'id':'p/org/b','owned_by':'p','root':'org/b','capabilities':{'tool_calling':True},'context_length':32768},
    {'id':'p/emb','owned_by':'p','root':'emb','type':'embedding'},
    {'id':'auto/free','owned_by':'combo','root':'auto/free','capabilities':{'tool_calling':True}},
    {'id':'p/org/a-high','owned_by':'p','root':'org/a-high','capabilities':{'tool_calling':True}},
]
free=api._free_index([{'provider':'p','modelId':'org/a','freeType':'recurring-daily'},
                     {'provider':'p','modelId':'org/b','freeType':'discontinued'}])

class Discovery(unittest.TestCase):
    def ids(self, **kwargs):
        return [r['id'] for r in api._filtered_rows(rows, api.DiscoveryFilters(**kwargs), free, {})]
    def test_all_types_and_no_caps(self):
        self.assertEqual(len(self.ids()),5)
        self.assertEqual(self.ids(kinds=[]),[])
    def test_type_union(self):
        self.assertEqual(self.ids(kinds=['embedding']),['p/emb'])
        self.assertEqual(len(self.ids(kinds=['chat','embedding'])),5)
    def test_and_or(self):
        self.assertEqual(self.ids(capabilities=['tool_calling','vision']),['p/org/a'])
        self.assertEqual(len(self.ids(capabilities=['tool_calling','vision'],match='or')),4)
    def test_native_query(self):
        params=parse_qs(urlsplit(api._discovery_query(api.DiscoveryFilters(kinds=['chat'],capabilities=['vision','tool_calling']))).query)
        self.assertNotIn('kind',params)  # retain explicit typed combos
        self.assertEqual(params['capability'],['vision,tool_calling'])
        self.assertEqual(params['prefix'],['canonical'])
        self.assertEqual(params['configuredOnly'],['true'])
        self.assertNotIn('kind',api._discovery_query(api.DiscoveryFilters(kinds=['chat','audio'])))
        self.assertNotIn('capability',api._discovery_query(api.DiscoveryFilters(capabilities=['vision','tool_calling'],match='or')))
    def test_free_strict(self):
        self.assertEqual(self.ids(free_only=True),['p/org/a'])
        self.assertNotIn('auto/free',self.ids(include_combos=False))
    def test_context_and_dedup(self):
        self.assertEqual(self.ids(min_context=65536),['p/org/a'])
        self.assertEqual(len(api._filtered_rows(rows+rows,api.DiscoveryFilters(),free,{})),5)
    def test_bad_filter(self):
        with self.assertRaises(HTTPException):
            api._discovery_query(api.DiscoveryFilters(kinds=['invalid']))
    def test_management_root(self):
        self.assertEqual(api._management_root('https://router.example/api/v1'),'https://router.example/api')
        self.assertEqual(api._management_root('https://router.example/v1'),'https://router.example/api')
    def test_no_type_selection_no_network(self):
        with patch.object(api,'_discovery_get') as get:
            self.assertEqual(api.discover_models(api.DiscoveryFilters(kinds=[]))['count'],0)
            get.assert_not_called()
    def test_free_catalog_failure_is_closed(self):
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',return_value='synthetic'), patch.object(api,'_fetch_catalog',return_value=rows), patch.object(api,'_discovery_get',side_effect=HTTPException(502)):
            with self.assertRaises(HTTPException):
                api.discover_models(api.DiscoveryFilters(free_only=True))

    def test_native_pagination_and_filters_over_1000(self):
        from io import BytesIO
        import json
        source = [{'id':f'p/model {i}+&', 'owned_by':'p', 'root':f'model {i}+&',
                   'capabilities':{'tool_calling':True}} for i in range(1705)]
        seen = []
        class Opener:
            def open(self, req, timeout):
                params = parse_qs(urlsplit(req.full_url).query)
                seen.append(params)
                assert params['prefix'] == ['canonical']
                assert params['configuredOnly'] == ['true']
                assert params['capability'] == ['tool_calling']
                start = 0 if 'after' not in params else next(i+1 for i,r in enumerate(source) if r['id']==params['after'][0])
                page = source[start:start+int(params['limit'][0])]
                return BytesIO(json.dumps({'data':page,'has_more':start+len(page)<len(source),'last_id':page[-1]['id']}).encode())
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',side_effect=lambda n:'synthetic' if n=='OMNIROUTE_API_KEY' else ''), patch.object(api.request,'build_opener',return_value=Opener()):
            result=api.discover_models(api.DiscoveryFilters(capabilities=['tool_calling']))
        self.assertEqual(result['count'],1705)
        self.assertEqual(result['diagnostics']['pages'],9)
        self.assertEqual(result['models'][-1]['id'],source[-1]['id'])
        self.assertEqual(seen[1]['after'],[source[199]['id']])
    def test_read_token_and_overlay_retirement(self):
        budget={'provider':'p','modelId':'org/a','freeType':'recurring-daily','monthlyTokens':5}
        def get(url, key):
            self.assertEqual(key,'read-token')
            if url.endswith('/free-models'): return {'models':[budget]}
            if '/free-provider-rankings?' in url: return {'rankings':[{'id':'p','reliability':{'state':'healthy','usage':{'requests':10,'successes':9,'avgLatencyMs':123,'windowHours':24}}}]}
            return {'catalogSource':'radar-overlay','modelCount':1,'perModel':[dict(budget,enabled=False)]}
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',side_effect=lambda n:'read-token' if n=='OMNIROUTE_READ_TOKEN' else 'inference-key'), patch.object(api,'_fetch_catalog',return_value=rows) as infer, patch.object(api,'_discovery_get',side_effect=get):
            result=api.discover_models(api.DiscoveryFilters(free_only=True))
            self.assertEqual(result['count'],0)
            self.assertEqual(infer.call_args.args[1],'inference-key')
            self.assertEqual(result['free_summary']['catalogSource'],'radar-overlay')
    def test_typed_combo_and_chat_subtypes(self):
        source=[{'id':'c','owned_by':'combo','type':'combo'},
                {'id':'r','owned_by':'p','type':'chat','subtype':'reasoning'},
                {'id':'s','owned_by':'p','type':'chat','subtype':'speech'}]
        self.assertEqual([r['id'] for r in api._filtered_rows(source,api.DiscoveryFilters(kinds=['chat']),{}, {})],['c','r'])
    def test_read_token_endpoint_change_requires_explicit_action(self):
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',return_value='synthetic'), patch.object(api,'save_env_value') as save:
            with self.assertRaises(HTTPException):
                api.save_connection(api.Connection(base_url='https://other.example/v1'))
            save.assert_not_called()

    def test_summary_enrichment_and_management_key_fallback(self):
        budget={'provider':'p','modelId':'org/a','freeType':'recurring-daily','monthlyTokens':100}
        calls=[]
        def get(url,key):
            calls.append((url,key))
            if url.endswith('/free-models'): return {'models':[budget]}
            if '/free-provider-rankings?' in url: return {'rankings':[{'id':'p','topModel':{'modelId':'org/b'},'reliability':{'state':'healthy','usage':{'requests':12,'successes':11,'avgLatencyMs':234,'windowHours':24}}}]}
            return {'catalogSource':'baseline','modelCount':1,'perModel':[dict(budget,hardStopGuaranteed=False,trainsOnPrompts=True)]}
        with patch.object(api,'_value',return_value='https://router.example/api/v1'), patch.object(api,'_secret',side_effect=lambda n:'key-with-manage' if n=='OMNIROUTE_API_KEY' else ''), patch.object(api,'_fetch_catalog',return_value=rows), patch.object(api,'_discovery_get',side_effect=get):
            result=api.discover_models(api.DiscoveryFilters(free_only=True))
        self.assertEqual([r['id'] for r in result['models']],['p/org/a'])
        self.assertEqual(result['models'][0]['provider_usage']['requests'],12)
        self.assertFalse(result['models'][0]['free_metadata']['hardStopGuaranteed'])
        self.assertTrue(result['models'][0]['free_metadata']['trainsOnPrompts'])
        self.assertEqual(len(calls),3)
        self.assertTrue(all(key=='key-with-manage' and url.startswith('https://router.example/api/') for url,key in calls))
    def test_no_management_request_by_default_without_read_token(self):
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',side_effect=lambda n:'inference-key' if n=='OMNIROUTE_API_KEY' else ''), patch.object(api,'_fetch_catalog',return_value=rows), patch.object(api,'_discovery_get') as get:
            result=api.discover_models(api.DiscoveryFilters())
        get.assert_not_called()
        self.assertEqual(result['count'],5)
    def test_management_token_never_sent_over_http(self):
        with patch.object(api,'_value',return_value='http://127.0.0.1/v1'), patch.object(api,'_secret',return_value='synthetic'), patch.object(api,'_fetch_catalog',return_value=rows), patch.object(api,'_discovery_get') as get:
            with self.assertRaises(HTTPException):
                api.discover_models(api.DiscoveryFilters(free_only=True))
            get.assert_not_called()
    def test_audio_is_not_chat_and_unknown_owner_is_preserved(self):
        source=[{'id':'malformed','type':'chat','subtype':'speech','owned_by':'p'},
                {'id':'tts','type':'audio','subtype':'speech','owned_by':'p'},
                {'id':'legacy'}, {'id':'combo-a','type':'combo'}]
        self.assertEqual([r['id'] for r in api._filtered_rows(source,api.DiscoveryFilters(kinds=['chat']),{}, {})],['legacy','combo-a'])
        self.assertEqual([r['id'] for r in api._filtered_rows(source,api.DiscoveryFilters(kinds=['audio']),{}, {})],['tts'])
    def test_clear_token_is_explicit_and_returns_only_boolean(self):
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',return_value='synthetic-secret'), patch.object(api,'save_env_value_secure') as save, patch.object(api,'status',return_value={'read_token_configured':True}):
            result=api.save_connection(api.Connection(clear_read_token=True))
            save.assert_called_once_with('OMNIROUTE_READ_TOKEN','')
            self.assertEqual(result,{'read_token_configured':False})

    def test_status_reports_installed_backend_version(self):
        with patch.object(api,'_value',return_value=''), patch.object(api,'_secret',return_value=''), patch.object(api,'_native_model_is_omniroute',return_value=False):
            result=api.status()
        self.assertEqual(result['plugin_version'],'0.4.0-beta.5')


    def test_picker_selection_profile_endpoint_and_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            m=api._catalog_module
            self.assertIsNone(m.read_picker_selection(a,'https://router.example/v1'))
            m.write_picker_selection(a,'https://router.example/v1',{'kinds':['chat']},['p/org/a','p/org/a'])
            self.assertEqual(m.read_picker_selection(a,'https://router.example/v1')['ids'],['p/org/a'])
            self.assertIsNone(m.read_picker_selection(b,'https://router.example/v1'))
            self.assertIsNone(m.read_picker_selection(a,'https://other.example/v1'))
            m.write_picker_selection(a,'https://router.example/v1',{'kinds':['image']},[])
            self.assertEqual(m.read_picker_selection(a,'https://router.example/v1')['ids'],[])
            m.clear_picker_selection(a)
            self.assertIsNone(m.read_picker_selection(a,'https://router.example/v1'))

    def test_successful_discovery_applies_only_chat_ids(self):
        import tempfile
        with tempfile.TemporaryDirectory() as home, patch.object(api,'_picker_home',return_value=home), patch.object(api,'_invalidate_picker') as invalidate, patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',side_effect=lambda n:'synthetic' if n=='OMNIROUTE_API_KEY' else ''), patch.object(api,'_fetch_catalog',return_value=rows):
            result=api.discover_models(api.DiscoveryFilters(kinds=['chat','embedding'],capabilities=['tool_calling'],include_combos=False,apply_to_picker=True))
            saved=api._catalog_module.read_picker_selection(home,'https://router.example/v1')
            self.assertEqual(saved['ids'],[r['id'] for r in result['models'] if r['kind']=='chat'])
            self.assertEqual(saved['ids'],['p/org/a','p/org/b','p/org/a-high'])
            self.assertEqual(result['picker_count'],3)
            self.assertNotIn('apply_to_picker',saved['filters'])
            invalidate.assert_called_once_with()
            with patch.object(api,'_fetch_catalog',side_effect=api.CatalogError('synthetic failure')):
                with self.assertRaises(HTTPException):
                    api.discover_models(api.DiscoveryFilters(apply_to_picker=True))
            self.assertEqual(api._catalog_module.read_picker_selection(home,'https://router.example/v1'),saved)
            api.discover_models(api.DiscoveryFilters(kinds=['embedding'],apply_to_picker=True))
            self.assertEqual(api._catalog_module.read_picker_selection(home,'https://router.example/v1')['ids'],[])
