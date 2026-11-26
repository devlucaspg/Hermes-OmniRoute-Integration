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
        self.assertEqual(result['plugin_version'],'0.5.0-beta.2')


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

class EnrichedDiscovery(unittest.TestCase):
    def test_exact_provider_identity_and_paid_conflict(self):
        source=[{'id':'nvidia/org/model','owned_by':'nvidia','root':'org/model'},
                {'id':'nvidia/model','owned_by':'nvidia','root':'model'},
                {'id':'openrouter/org/model','owned_by':'openrouter','root':'org/model'},
                {'id':'alias','owned_by':'nvidia','root':'org/model'}]
        ext={('nvidia','org/model'):{'access':['free_preview'],'kind':'chat','source':'fixture','context_length':131072,'capabilities':['reasoning']},
             ('openrouter','org/model'):{'access':['paid'],'source':'fixture'}}
        baseline={('openrouter','org/model'):{'freeType':'recurring-daily'}}
        result=api._filtered_rows(source,api.DiscoveryFilters(free_only=True,capabilities=['reasoning'],min_context=65536),baseline,{},ext)
        self.assertEqual([r['id'] for r in result],['nvidia/org/model'])
        self.assertEqual(result[0]['access'],['free_preview'])
        self.assertEqual(api._filtered_rows(source,api.DiscoveryFilters(free_only=True),baseline,{},ext,retired={('nvidia','org/model')}),[])
    def test_nvidia_exact_schema(self):
        spec={'paths':{'/v1/chat/completions':{'post':{'requestBody':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Req'}}}}}}},
              'components':{'schemas':{'Req':{'properties':{'model':{'default':'moonshotai/kimi-k3.1-pro'}}}}}}
        self.assertEqual(api._enrich.nvidia_ids(spec),{'moonshotai/kimi-k3.1-pro'})
        spec['components']['schemas']['Req']['properties']['model']['enum']=['other/model']
        self.assertEqual(api._enrich.nvidia_ids(spec),set())
    def test_public_sources_do_not_send_keys_and_cache(self):
        import tempfile
        with tempfile.TemporaryDirectory() as home, patch.dict(api._enrich.ADAPTERS,{'nvidia':lambda:([{'model_id':'org/model','access':['free_preview'],'source':'fixture'}],0,0)}):
            first,state=api._enrich.collect(home,['nvidia'],{'nvidia'},3600)
            self.assertEqual(state['nvidia']['status'],'ok')
            with patch.dict(api._enrich.ADAPTERS,{'nvidia':lambda:(_ for _ in ()).throw(RuntimeError())}):
                second,state=api._enrich.collect(home,['nvidia'],{'nvidia'},3600)
                self.assertEqual(first,second)
    def test_quota_unknown_and_health_filter(self):
        self.assertEqual(api._enrich.quota_status('nvidia',['free_preview'],[]),'unknown')
        self.assertEqual(api._enrich.quota_status('ollama-local',['local'],[]),'not_applicable')
        self.assertEqual(api._filtered_rows(rows,api.DiscoveryFilters(exclude_cooling=True),{}, {},health={'p/org/a':'cooling'})[0]['id'],'p/org/b')
    def test_enriched_query_keeps_rows_for_local_filter(self):
        q=parse_qs(urlsplit(api._discovery_query(api.DiscoveryFilters(sources=['nvidia'],capabilities=['reasoning'],min_context=65536))).query)
        self.assertNotIn('capability',q)
        self.assertNotIn('min_context',q)
    def test_partial_source_preserves_picker(self):
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',side_effect=lambda n:'synthetic' if n=='OMNIROUTE_API_KEY' else ''), patch.object(api,'_fetch_catalog',return_value=rows), patch.object(api,'_picker_home',return_value='/unused'), patch.object(api._enrich,'collect',return_value=({}, {'nvidia':{'status':'unavailable'}})), patch.object(api,'_apply_picker') as apply:
            r=api.discover_models(api.DiscoveryFilters(sources=['nvidia'],apply_to_picker=True))
            self.assertFalse(r['picker_applied'])
            apply.assert_not_called()

    def test_nvidia_missing_spec_is_unresolved(self):
        with patch.object(api._enrich,'public_json',return_value={'openAPISpec':None}):
            self.assertEqual(api._enrich._nvidia_detail({'name':'audio-example'}),[])
    def test_xkiro_paid_and_premium_not_free_and_vision(self):
        sample={'data':[{'id':'cohere/a','access_tier':'free','modality':'chat','capabilities':{'vision':True,'tools':True}},
                        {'id':'org/premium','access_tier':'premium','modality':'chat'}]}
        with patch.object(api._enrich,'public_json',return_value=sample):
            entries,_,_=api._enrich.xkiro()
        self.assertEqual(entries[0]['access'],['free_quota'])
        self.assertEqual(entries[0]['input'],['text','image'])
        self.assertEqual(entries[1]['access'],['paid'])
    def test_llm7_nested_context(self):
        sample={'data':[{'id':'example','tier':'turbo','usage_based_only':False,'model_type':'chat','context_window':{'tokens':32000},'modalities':{'input':['text'],'output':['text']}}]}
        with patch.object(api._enrich,'public_json',return_value=sample):
            entries,_,_=api._enrich.llm7()
        self.assertEqual(entries[0]['context_length'],32000)
    def test_native_explicit_negative_vision(self):
        row={'id':'nvidia/org/m','owned_by':'nvidia','root':'org/m','capabilities':{'vision':False}}
        external={('nvidia','org/m'):{'source':'fixture','input':['text','image'],'capabilities':['vision']}}
        self.assertEqual(api._filtered_rows([row],api.DiscoveryFilters(input_modalities=['image']),{}, {},external),[])

    def test_gemini_exact_standard_pricing(self):
        def section(name,a,b):
            return '## '+name+'\n{% left-column %}\n[\x60'+name+'\x60](/docs/models/'+name+')\n{% /left-column %}\n{% tab title="Standard" %}\n{% table %}\n* Feature\n* Free Tier\n* Paid Tier\n---\n* Input price\n* '+a+'\n* $1\n---\n* Output price\n* '+b+'\n* $2\n{% /table %}\n{% /tab %}\n'
        data='# Gemini Developer API pricing\n'+section('gemini-example','Free of charge','Free of charge')+section('gemini-paid','Not available','Not available')+section('gemini-mixed','Free of charge','Not available')
        self.assertEqual({e['model_id']:e['access'] for e in api._enrich.parse_gemini(data)},{'gemini-example':['free_quota'],'gemini-paid':['paid'],'gemini-mixed':['unknown_pricing']})
    def test_groq_active_free_table_required(self):
        header='<table><tr><th><button class="bg-black dark:bg-white">Free Plan Limits</button><button class="other">Developer Plan Limits</button></th></tr><tr>'+''.join('<th>'+v+'</th>' for v in ('MODEL ID','RPM','RPD','TPM','TPD','ASH','ASD'))+'</tr></table>'
        rows='<table><tr>'+''.join('<td>'+v+'</td>' for v in ('org/example','30','1K','8K','200K','-','-'))+'</tr></table>'
        self.assertEqual(api._enrich.parse_groq(header+rows)[0]['access'],['free_quota'])
        with self.assertRaises(ValueError): api._enrich.parse_groq((header+rows).replace('bg-black dark:bg-white','other'))
    def test_cloudflare_explicit_paid_exceptions(self):
        data='# Pricing\n10,000 Neurons per day at no charge. Workers Paid.\nSome models require a paid billing method. This applies to \x60@cf/org/paid\x60. You can access these models.\n## LLM model pricing\n'+''.join('| @cf/org/'+v+' | $1 | 1000 neurons per M tokens |\n' for v in ('free','paid','a','b','c'))
        result={e['model_id']:e for e in api._enrich.parse_cloudflare(data)}
        self.assertEqual(result['@cf/org/free']['access'],['free_quota'])
        self.assertEqual(result['@cf/org/paid']['access'],['paid'])
        with self.assertRaises(ValueError): api._enrich.parse_cloudflare(data.replace('Some models require a paid billing method.','Changed.'))
    def test_mistral_policy_only_labs(self):
        index={('mistral',api._enrich.POLICY_ID):{'source':'fixture','policy':'mistral_labs','fetched_at':1}}
        self.assertEqual(api._enrich.route_metadata(index,('mistral','labs-example'))['access'],['free_preview'])
        self.assertEqual(api._enrich.route_metadata(index,('mistral','mistral-medium')), {})
    def test_sambanova_metered_prices_not_free(self):
        with patch.object(api._enrich,'public_json',return_value={'data':[{'id':'model','pricing':{'prompt':'0.01','completion':'0.02'}}]}):
            rows,_,_=api._enrich.sambanova()
        self.assertEqual(rows[0]['access'],['paid'])
    def test_exact_rootless_media(self):
        source=[{'id':'gemini/audio-example','owned_by':'gemini','root':None,'type':'audio'},
                {'id':'gemini/audio-example-alias','owned_by':'gemini','root':None,'type':'audio'}]
        meta={('gemini','audio-example'):{'source':'fixture','access':['free_quota']}}
        result=api._filtered_rows(source,api.DiscoveryFilters(kinds=['audio'],free_only=True),{}, {},meta)
        self.assertEqual([r['id'] for r in result],['gemini/audio-example'])
    def test_expired_reset_unknown(self):
        from datetime import datetime, timezone, timedelta
        now=datetime.now(timezone.utc)
        account={'provider':'xkiro','fetchedAt':now.isoformat(),'quotas':{'free_daily':{'remainingPercentage':0,'resetAt':(now-timedelta(seconds=1)).isoformat()}}}
        self.assertEqual(api._enrich.quota_status('xkiro',['free_quota'],[account]),'unknown')

class PinnedProviders(unittest.TestCase):
    def test_union_independent_of_search_and_no_duplicates(self):
        search=[rows[0]]
        configured=rows+[
            {'id':'web/model','owned_by':'web','root':'model'},
            {'id':'web/media','owned_by':'web','root':'media','type':'image'}]
        def fetch(base,key,opener,diagnostics,query_params):
            if query_params.get('q') == 'a':
                return search
            self.assertEqual(query_params,{'prefix':'canonical','configuredOnly':'true'})
            return configured
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',side_effect=lambda n:'synthetic' if n=='OMNIROUTE_API_KEY' else ''), patch.object(api,'_fetch_catalog',side_effect=fetch), patch.object(api,'_apply_picker',return_value={'picker_count':4}) as apply:
            r=api.discover_models(api.DiscoveryFilters(kinds=['chat'],providers=['p'],pinned_providers=['p','web','web','missing'],q='a',capabilities=['vision'],min_context=65536,configured_only=False,apply_to_picker=True))
        self.assertEqual(r['search_count'],1)
        self.assertEqual(r['pinned_count'],6)
        self.assertEqual(r['pinned_added_count'],5)
        self.assertEqual(r['count'],6)
        self.assertEqual(r['missing_pinned_providers'],['missing'])
        self.assertEqual(r['models'][0]['id'],'p/org/a')
        self.assertTrue(r['models'][0]['matched_search'])
        self.assertTrue(r['models'][0]['pinned'])
        web=next(m for m in r['models'] if m['id']=='web/model')
        self.assertEqual(web['access'],['unknown_pricing'])
        self.assertFalse(web['matched_search'])
        self.assertTrue(web['pinned'])
        self.assertTrue(any(m['kind']=='image' for m in r['models']))
        self.assertNotIn('auto/free',[m['id'] for m in r['models']])
        self.assertEqual(apply.call_args.args[1],r['models'])
    def test_pin_only_and_configured_provider_list(self):
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',side_effect=lambda n:'synthetic' if n=='OMNIROUTE_API_KEY' else ''), patch.object(api,'_fetch_catalog',return_value=rows) as fetch:
            self.assertEqual(api.configured_providers()['providers'],[{'id':'p','model_count':4}])
            result=api.discover_models(api.DiscoveryFilters(kinds=[],pinned_providers=['p']))
        self.assertEqual(result['search_count'],0)
        self.assertEqual(result['pinned_added_count'],4)
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(fetch.call_args.kwargs['query_params'],{'prefix':'canonical','configuredOnly':'true'})
    def test_pinned_paid_model_does_not_become_free(self):
        budget={'provider':'p','modelId':'org/a','freeType':'recurring-daily'}
        def get(url,key):
            if url.endswith('/free-models'): return {'models':[budget]}
            if '/free-provider-rankings?' in url: return {'rankings':[]}
            return {'perModel':[budget]}
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',return_value='synthetic'), patch.object(api,'_fetch_catalog',return_value=rows), patch.object(api,'_discovery_get',side_effect=get):
            result=api.discover_models(api.DiscoveryFilters(kinds=['chat'],free_only=True,pinned_providers=['p']))
        self.assertEqual(result['search_count'],1)
        self.assertEqual(result['pinned_added_count'],3)
        self.assertEqual(next(m for m in result['models'] if m['id']=='p/org/b')['access'],['unknown_pricing'])
    def test_combined_fetch_reuses_unfiltered_configured_catalog(self):
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',side_effect=lambda n:'synthetic' if n=='OMNIROUTE_API_KEY' else ''), patch.object(api,'_fetch_catalog',return_value=rows) as fetch:
            r=api.discover_models(api.DiscoveryFilters(pinned_providers=['p']))
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(r['pinned_added_count'],0)
        self.assertEqual(r['pinned_count'],4)
    def test_pinned_catalog_failure_never_applies_picker(self):
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',return_value='synthetic'), patch.object(api,'_fetch_catalog',side_effect=[rows,api.CatalogError('failed')]), patch.object(api,'_apply_picker') as apply:
            with self.assertRaises(HTTPException):
                api.discover_models(api.DiscoveryFilters(pinned_providers=['p'],q='test',apply_to_picker=True))
            apply.assert_not_called()
