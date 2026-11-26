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
        self.assertEqual(params['kind'],['chat'])
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
        with patch.object(api,'_value',return_value='https://router.example/v1'), patch.object(api,'_secret',return_value='synthetic'), patch.object(api,'_discovery_get',side_effect=[{'data':rows},HTTPException(502)]):
            with self.assertRaises(HTTPException):
                api.discover_models(api.DiscoveryFilters(free_only=True))
