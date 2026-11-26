"""Offline integration-contract tests using Hermes ABC doubles, no network."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def _load_backend():
    agent = types.ModuleType('agent'); agent.__path__ = []
    modules = {'agent': agent}
    def provider_mod(name, base, methods):
        mod = types.ModuleType('agent.' + name)
        setattr(mod, base, type(base, (), {}))
        for key, fn in methods.items(): setattr(mod, key, fn)
        modules[mod.__name__] = mod
    provider_mod('image_gen_provider', 'ImageGenProvider', {
        'success_response': lambda **k: dict(success=True, **k),
        'error_response': lambda **k: dict(success=False, **k),
        'save_b64_image': lambda *a, **kw: '/tmp/mock.png',
        'save_url_image': lambda *a, **kw: '/tmp/mock.png'})
    provider_mod('video_gen_provider', 'VideoGenProvider', {
        'success_response': lambda **k: dict(success=True, **k),
        'error_response': lambda **k: dict(success=False, **k),
        'save_b64_video': lambda *a, **kw: '/tmp/mock.mp4'})
    provider_mod('web_search_provider', 'WebSearchProvider', {})
    provider_mod('tts_provider', 'TTSProvider', {})
    provider_mod('transcription_provider', 'TranscriptionProvider', {})
    # Explicit fake scoped getters (the production path must not leak os.environ).
    scope = types.ModuleType('agent.secret_scope')
    scope.get_secret_str = lambda name, default='': os.environ.get(name, default)
    modules[scope.__name__] = scope
    sys.modules.update(modules)
    spec = importlib.util.spec_from_file_location('omniroute_test_backend', ROOT / 'backend' / '__init__.py',
              submodule_search_locations=[str(ROOT / 'backend')])
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = plugin
    spec.loader.exec_module(plugin)
    return plugin


B = _load_backend()
CORE = sys.modules[B.__name__ + '.core']


class RegistrationTests(unittest.TestCase):
    def test_registers_five_backend_interfaces(self):
        class Context:
            def __init__(self): self.calls = []
            def __getattr__(self, name):
                def add(x): self.calls.append((name, x.name))
                return add
        ctx = Context(); B.register(ctx)
        self.assertEqual(ctx.calls, [
            ('register_image_gen_provider','omniroute'),
            ('register_video_gen_provider','omniroute'),
            ('register_web_search_provider','omniroute'),
            ('register_tts_provider','omniroute'),
            ('register_transcription_provider','omniroute')])

    def test_model_provider_registration(self):
        captured = []
        pro = types.ModuleType('providers')
        base = types.ModuleType('providers.base')
        @dataclass
        class Profile:
            name: str
            aliases: tuple = ()
            display_name: str = ''
            description: str = ''
            auth_type: str = ''
            api_mode: str = ''
            base_url: str = ''
            env_vars: tuple = ()
            fallback_models: tuple = ()
            supports_model_listing: bool = True
            supports_health_check: bool = True
            supports_vision: bool = False
        pro.register_provider = captured.append
        base.ProviderProfile = Profile
        with patch.dict(sys.modules, {'providers':pro,'providers.base':base}):
            spec = importlib.util.spec_from_file_location('omniroute_model_test', ROOT / 'model-provider' / '__init__.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertEqual([p.name for p in captured], ['omniroute'])
        self.assertEqual(captured[0].base_url, '')
        self.assertEqual(captured[0].env_vars, ('OMNIROUTE_API_KEY',))
        self.assertEqual(captured[0].fallback_models, ())

    def test_manifest_kinds_are_correct(self):
        a = (ROOT / 'backend/plugin.yaml').read_text()
        b = (ROOT / 'model-provider/plugin.yaml').read_text()
        self.assertIn('kind: backend', a)
        self.assertIn('kind: model-provider', b)
        self.assertIn('provides_web_providers:', a)
        self.assertNotIn('omniroute.josevictor.me/api/v1', a + b)


class CoreTests(unittest.TestCase):
    @patch.dict(os.environ, {'OMNIROUTE_API_KEY':'hidden','OMNIROUTE_BASE_URL':'http://127.0.0.1:8080/v1'})
    def test_endpoint_and_configuration(self):
        self.assertTrue(CORE.configured())
        self.assertEqual(CORE.api_base(), 'http://127.0.0.1:8080/v1')

    @patch.dict(os.environ, {'OMNIROUTE_API_KEY':'hidden','OMNIROUTE_BASE_URL':'http://test:secret@x/v1'})
    def test_disallows_basic_credentials_in_url(self):
        with self.assertRaises(CORE.OmniError): CORE.api_base()

    @patch.dict(os.environ, {'OMNIROUTE_API_KEY':'hidden','OMNIROUTE_BASE_URL':'https://router.example/v1'})
    def test_no_redirect_with_bearer_token(self):
        self.assertIsNone(CORE._NoRedirect().redirect_request(None,None,302,'redirect',{},'https://evil.invalid/'))

    def test_media_format_selector(self):
        from omniroute_test_backend.providers.image import _size
        rows = [{'id':'m', 'supported_sizes':['1024x768','768x1024','1024x1024']}]
        self.assertEqual(_size(rows,'m','portrait'),'768x1024')
        self.assertIsNone(_size([{'id':'m','supported_sizes':['16:9','9:16']}],'m','portrait'))
        self.assertIsNone(_size([], 'unknown','landscape'))

    def test_image_with_edit_route(self):
        with patch.object(sys.modules[B.__name__+'.providers.image'], 'call_json', return_value={'data':[{'url':'https://cdn.test/image.png'}]}) as req, \
             patch.object(sys.modules[B.__name__+'.providers.image'], 'model_entries', return_value=[]):
            import base64
            url = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
            result = B.OmniImage().generate('refine', model='test/model', image_url=url)
        self.assertTrue(result['success'])
        self.assertEqual(req.call_args.args[1], '/images/edits')
        self.assertEqual(result['modality'], 'image')
        body = req.call_args.kwargs['payload']
        self.assertEqual(len(body['images']), 1)
        self.assertIn('image_url', body['images'][0])
        self.assertNotIn('reference_images', body)

    def test_image_without_model_is_explicit_error(self):
        with patch.dict(os.environ, {'OMNIROUTE_IMAGE_MODEL':''}):
            result = B.OmniImage().generate('test')
        self.assertFalse(result['success'])
        self.assertIn('OMNIROUTE_IMAGE_MODEL', result['error'])

    def test_video_text_and_image_to_video(self):
        with patch.object(sys.modules[B.__name__+'.providers.video'], 'call_json', return_value={'data':[{'url':'https://cdn.test/clip.mp4'}]}) as req:
            result = B.OmniVideo().generate('a tree', model='video/x', image_url='https://source.test/i.jpg')
        self.assertTrue(result['success'])
        self.assertEqual(result['modality'], 'image')
        self.assertEqual(req.call_args.args[1], '/videos/generations')

    def test_search_envelope(self):
        with patch.object(sys.modules[B.__name__+'.providers.web'], 'call_json', return_value={
            'results':[{'title':'A', 'url':'https://a.test','snippet':'x'*700}]}):
            out = B.OmniWeb().search('example')
        self.assertTrue(out['success'])
        self.assertLessEqual(len(out['data']['web'][0]['description']), 500)

    def test_extract_partial_failure(self):
        from omniroute_test_backend.providers import web
        with patch.object(web, 'call_json', side_effect=[{'url':'https://a.test', 'content':'hello'}, CORE.OmniError('HTTP 503')]):
            out = B.OmniWeb().extract(['https://a.test','https://b.test'])
        self.assertEqual(len(out),2)
        self.assertEqual(out[0]['content'],'hello')
        self.assertIn('error',out[1])

    def test_tts_uses_configured_model_and_path(self):
        from omniroute_test_backend.providers import audio
        with tempfile.TemporaryDirectory() as tmp, patch.object(audio, 'call', return_value=(b'abc','audio/mpeg')) as client:
            out = B.OmniTTS().synthesize('hello', str(Path(tmp)/'voice'), model='tts/demo')
            self.assertTrue(Path(out).is_file())
            self.assertEqual(Path(out).suffix,'.mp3')
            self.assertEqual(client.call_args.args[1], '/audio/speech')

    def test_stt_multipart(self):
        from omniroute_test_backend.providers import audio
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp)/'voice.wav'; sample.write_bytes(b'RIFFMOCK')
            with patch.object(audio,'call',return_value=(b'{"text":"transcribed"}','application/json')) as client:
                out = B.OmniSTT().transcribe(str(sample),model='stt/demo')
        self.assertTrue(out['success'])
        self.assertIn('multipart/form-data',client.call_args.kwargs['content_type'])
        self.assertIn(b'RIFFMOCK',client.call_args.kwargs['data'])

    def test_no_secret_in_response(self):
        with patch.dict(os.environ, {'OMNIROUTE_API_KEY':'supersecret','OMNIROUTE_BASE_URL':'https://test.invalid/v1'}):
            with patch.object(CORE._OPENER, 'open', side_effect=__import__('urllib').error.HTTPError('x',401,'secret',None,None)):
                with self.assertRaisesRegex(CORE.OmniError,'OmniRoute HTTP 401') as err:
                    CORE.call_json('GET','/models')
            self.assertNotIn('supersecret', str(err.exception))


class DocsTests(unittest.TestCase):
    def test_dashboard_manifest(self):
        d=json.loads((ROOT/'backend/dashboard/manifest.json').read_text())
        self.assertEqual(d['name'],'omniroute-media')
        self.assertTrue((ROOT/'backend/dashboard'/d['entry']).is_file())
        self.assertTrue((ROOT/'backend/dashboard'/d['api']).is_file())


class ExtendedSafetyTests(unittest.TestCase):
    def test_explicit_model_precedence(self):
        with patch.dict(os.environ, {'OMNIROUTE_IMAGE_MODEL':'configured/image'}):
            self.assertEqual(CORE.model_id('explicit/model', 'OMNIROUTE_IMAGE_MODEL', 'image'), 'explicit/model')

    def test_discovery_from_mocked_api(self):
        with patch.object(CORE, '_fetch_catalog', return_value=[{'id':'demo/a','type':'chat'}, {'id':'demo/b','type':'chat'}]) as req:
            fresh = CORE.Catalog()
            with patch.dict(os.environ, {'OMNIROUTE_API_KEY':'key','OMNIROUTE_BASE_URL':'https://router.test/v1'}):
                one = fresh.get('/models'); two = fresh.get('/models')
        self.assertEqual([x['id'] for x in one], ['demo/a','demo/b'])
        self.assertEqual(one,two)
        self.assertEqual(req.call_count,1)

    def test_production_code_does_not_read_raw_environment_secrets(self):
        for f in (ROOT/'backend/core.py', ROOT/'model-provider/__init__.py'):
            self.assertNotIn('os.environ', f.read_text())

    def test_image_output_format_signature(self):
        from omniroute_test_backend.providers.image import _extension
        import base64
        self.assertEqual(_extension(base64.b64encode(b'\xff\xd8\xffdemo').decode()),'jpg')
        self.assertEqual(_extension(base64.b64encode(b'\x89PNG\r\n').decode()),'png')

    def test_dashboard_uses_hermes_native_config_when_active(self):
        env = {'OMNIROUTE_BASE_URL':'https://example.invalid/v1','OMNIROUTE_API_KEY':'secret'}
        config = {'model':{'provider':'omniroute'}}
        writes = []
        hermes_cli = types.ModuleType('hermes_cli'); hermes_cli.__path__=[]
        cfg = types.ModuleType('hermes_cli.config')
        cfg.get_env_value=lambda k: env.get(k, '')
        cfg.save_env_value=lambda k,v: env.__setitem__(k,v)
        cfg.save_env_value_secure=lambda k,v: env.__setitem__(k,v)
        cfg.load_config=lambda: config
        cfg.set_config_value=lambda k,v: writes.append((k,v))
        with patch.dict(sys.modules,{'hermes_cli':hermes_cli,'hermes_cli.config':cfg}), \
             patch.object(sys.modules['agent.secret_scope'], 'get_secret_str', lambda k, default='': env.get(k,default)):
            spec=importlib.util.spec_from_file_location('omni_dash_test',ROOT/'backend/dashboard/plugin_api.py')
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            state=m.save_model(m.ModelSelection(kind='chat',model='local/model'))
            self.assertTrue(state['api_key_configured'])
            self.assertNotIn('api_key',state)
            self.assertEqual(writes,[('model.default','local/model')])
            self.assertTrue(m._matches_kind({'id':'t/one','type':'audio','subtype':'speech'},'tts'))
            self.assertFalse(m._matches_kind({'id':'t/one','type':'audio','subtype':'speech'},'stt'))
            self.assertTrue(m._matches_kind({'id':'s/one','type':'audio','subtype':'transcription'},'stt'))
            self.assertFalse(m._matches_kind({'id':'s/one','type':'audio','subtype':'transcription'},'tts'))
            self.assertFalse(m._matches_kind({'id':'s/one','type':'audio','subtype':'speech'},'chat'))
            m.save_connection(m.Connection(base_url='http://127.0.0.1:8000/v1'))
            self.assertIn(('model.base_url','http://127.0.0.1:8000/v1'),writes)
            # Real dashboard listing code, with a deterministic local HTTP double.
            # The same unified catalog is filtered differently for each modality.
            from io import BytesIO
            payload={'data':[{'id':'demo/chat','type':'chat'},
                             {'id':'demo/speech','type':'audio','subtype':'speech'},
                             {'id':'demo/transcription','type':'audio','subtype':'transcription'},
                             {'id':'demo/video','type':'video'}]}
            called=[]
            class FakeOpener:
                def open(self,req,timeout=None):
                    called.append(req.full_url)
                    return BytesIO(json.dumps(payload).encode())
            with patch.object(m.request,'build_opener',return_value=FakeOpener()):
                self.assertEqual([x['id'] for x in m.models('chat')['models']], ['demo/chat'])
                self.assertEqual([x['id'] for x in m.models('tts')['models']], ['demo/speech'])
                self.assertEqual([x['id'] for x in m.models('stt')['models']], ['demo/transcription'])
            self.assertTrue(called[0].endswith('/models?prefix=alias&limit=200'))
            self.assertTrue(called[1].endswith('/models?prefix=alias&limit=200'))
            large = [{'id': f'model/{i}', 'type': 'chat'} for i in range(1205)]
            large += [{'id':'model/reason', 'type':'chat','subtype':'reasoning'},
                      {'id':'combo/default', 'type':'combo'},
                      {'id':'model/0', 'type':'chat'},
                      {'id':'media/tts', 'type':'audio','subtype':'speech'}]
            with patch.object(m, '_fetch_catalog', return_value=large):
                response = m.models('chat')
                listed = response['models']
            self.assertEqual(len(listed), 1207)
            stats = response['diagnostics']
            self.assertEqual(stats['received'], 1209)
            self.assertEqual(stats['classified']['chat'], 1208)
            self.assertEqual(stats['classified']['tts'], 1)
            self.assertEqual(stats['combos'], 1)
            self.assertEqual(stats['duplicates_removed'], 1)
            self.assertEqual(stats['delivered'], 1207)
            self.assertEqual(stats['source'], 'api')
            self.assertEqual(listed[-1]['id'], 'combo/default')
            from fastapi import HTTPException
            with patch.object(m, '_fetch_catalog', side_effect=m.CatalogError('bad cursor')):
                with self.assertRaises(HTTPException) as failure:
                    m.models('chat')
                self.assertEqual(failure.exception.status_code, 502)
                self.assertEqual(failure.exception.detail, 'bad cursor')
            config['model']['provider']='different'
            writes.clear()
            m.save_model(m.ModelSelection(kind='chat',model='other/model'))
            self.assertEqual(writes,[])

    def test_dashboard_rejects_endpoint_with_embedded_password(self):
        env = {}
        hermes_cli=types.ModuleType('hermes_cli'); hermes_cli.__path__=[]
        cfg=types.ModuleType('hermes_cli.config')
        cfg.get_env_value=lambda k: env.get(k,'')
        cfg.save_env_value=lambda k,v: env.__setitem__(k,v)
        cfg.save_env_value_secure=lambda k,v: env.__setitem__(k,v)
        cfg.load_config=lambda: {'model':{}}
        cfg.set_config_value=lambda *a: None
        with patch.dict(sys.modules,{'hermes_cli':hermes_cli,'hermes_cli.config':cfg}), \
             patch.object(sys.modules['agent.secret_scope'], 'get_secret_str', lambda k, default='': env.get(k,default)):
            spec=importlib.util.spec_from_file_location('omni_dash_test2',ROOT/'backend/dashboard/plugin_api.py')
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):
                m.save_connection(m.Connection(base_url='https://me:secret@router.test/v1'))
            with self.assertRaises(HTTPException):
                m.save_connection(m.Connection(base_url='https://router.example/v1',api_key='bad\nkey'))
            self.assertEqual(env,{})



class OmniRoute351RegressionTests(unittest.TestCase):
    def test_image_registry_null_modalities_are_allowed(self):
        with patch.object(CORE.catalog, 'get', return_value=[
            {'id': 'image/a', 'type': 'image', 'input_modalities': None},
            {'id': 'image/b', 'type': 'image'},
            {'id': 'image/c', 'type': 'image', 'input_modalities': ['image']},
        ]) as getter:
            models = CORE.model_entries('image')
        self.assertEqual([x['id'] for x in models], ['image/a','image/b'])
        self.assertEqual(getter.call_args.args, ('/images/generations',))

    def test_video_uses_official_specialty_catalog(self):
        with patch.object(CORE.catalog, 'get', return_value=[
            {'id':'video/a','type':'video'}, {'id':'video/b','type':'video'}
        ]) as getter:
            self.assertEqual(len(CORE.model_entries('video')),2)
        self.assertEqual(getter.call_args.args, ('/videos/generations',))

    def test_video_preserves_optional_parameters(self):
        from omniroute_test_backend.providers import video
        with patch.object(video,'call_json',return_value={'data':[{'url':'https://cdn.test/movie.mp4'}]}) as req:
            result=B.OmniVideo().generate('forest',model='runway/gen-3',
                                         negative_prompt='fog',audio=True,seed=33)
        self.assertTrue(result['success'])
        self.assertEqual(req.call_args.kwargs['payload']['negative_prompt'],'fog')
        self.assertIs(req.call_args.kwargs['payload']['audio'],True)
        self.assertEqual(req.call_args.kwargs['payload']['seed'],33)

    def test_image_edits_include_all_data_url_references(self):
        import base64
        image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
        from omniroute_test_backend.providers import image as im
        with patch.object(im,'model_entries',return_value=[]),patch.object(im,'call_json',return_value={
                'data':[{'url':'https://cdn.test/edited.png'}]}) as req:
            result=B.OmniImage().generate('change',model='codex/gpt-image-2',
                                          image_url=image,reference_image_urls=[image])
        self.assertTrue(result['success'])
        payload=req.call_args.kwargs['payload']
        self.assertEqual(len(payload['images']),2)
        self.assertNotIn('reference_images',payload)
        self.assertNotIn('image',payload)
        self.assertEqual(payload['model'],'codex/gpt-image-2')

    def test_more_than_eight_refs_rejected(self):
        from omniroute_test_backend.providers import image as im
        with patch.object(im,'call_json') as req:
            output=B.OmniImage().generate('change',model='openai/gpt-image-2',
                reference_image_urls=['x']*9)
        self.assertFalse(output['success'])
        req.assert_not_called()

    def test_http_public_is_rejected(self):
        with self.assertRaises(CORE.OmniError):
            CORE.validated_base('http://example.com/v1')
        with self.assertRaises(CORE.OmniError):
            CORE.validated_base('http://8.8.8.8/v1')
        self.assertEqual(CORE.validated_base('http://192.168.1.25:8080/v1'),
                         'http://192.168.1.25:8080/v1')
        self.assertEqual(CORE.validated_base('http://omniroute.home.arpa:22129/v1'),
                         'http://omniroute.home.arpa:22129/v1')
        self.assertEqual(CORE.validated_base('https://example.com/v1'),
                         'https://example.com/v1')

    def test_bad_base_url_operations(self):
        for url in ['http://localhost:99999/v1','https://example.com/v1/models',
                    'https://example.com/v1?key=secret','http://name:password@localhost/v1']:
            with self.subTest(url=url),self.assertRaises(CORE.OmniError):
                CORE.validated_base(url)

    def test_video_catalog_fallback_to_models(self):
        def data(path, **kwargs):
            if path=='/videos/generations': return []
            return [{'id':'demo/v1','type':'video'}, {'id':'demo/chat','type':'chat'}]
        with patch.object(CORE.catalog, 'get', side_effect=data):
            rows=CORE.model_entries('video')
        self.assertEqual([r['id'] for r in rows], ['demo/v1'])

    def test_web_invalid_result_limit_clean_error(self):
        result=B.OmniWeb().search('test',limit='invalid')
        self.assertFalse(result['success'])
        self.assertIn('limit',result['error'])

    def test_media_catalog_isolated_by_key_and_endpoint(self):
        from unittest.mock import patch as mo
        with mo.object(CORE, '_fetch_catalog',side_effect=[
              [{'id':'profile-a'}], [{'id':'profile-b'}]]) as req:
            c=CORE.Catalog()
            with patch.dict(os.environ,{'OMNIROUTE_API_KEY':'key-a','OMNIROUTE_BASE_URL':'https://a.example/v1'}):
                a=c.get('/models')
            with patch.dict(os.environ,{'OMNIROUTE_API_KEY':'key-b','OMNIROUTE_BASE_URL':'https://b.example/v1'}):
                b=c.get('/models')
        self.assertEqual(a[0]['id'],'profile-a')
        self.assertEqual(b[0]['id'],'profile-b')
        self.assertEqual(req.call_count,2)

    def test_video_provider_model_url_default(self):
        # Uses the exact public ProviderProfile API and scoped endpoint resolution.
        pro=types.ModuleType('providers');base=types.ModuleType('providers.base')
        @dataclass
        class Profile:
            name: str
            aliases: tuple = ()
            display_name: str = ''
            description: str = ''
            auth_type: str = ''
            api_mode: str = ''
            base_url: str = ''
            env_vars: tuple = ()
            fallback_models: tuple = ()
            supports_model_listing: bool = True
            supports_health_check: bool = True
            supports_vision: bool = False
        captured=[]; pro.register_provider=captured.append; base.ProviderProfile=Profile
        with patch.dict(sys.modules,{'providers':pro,'providers.base':base}):
            spec=importlib.util.spec_from_file_location('omni_profile_probe',ROOT/'model-provider/__init__.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.dict(os.environ,{'OMNIROUTE_BASE_URL':'https://router.example/v1'}):
            self.assertEqual(module.omniroute.build_client_kwargs_extras(),
                             {'base_url':'https://router.example/v1'})
        with patch.dict(os.environ,{'OMNIROUTE_BASE_URL':'http://public.example/v1'}):
            self.assertEqual(module.omniroute.build_client_kwargs_extras(),{})


    def test_audio_model_roles_from_metadata(self):
        with patch.object(CORE.catalog,'get',return_value=[
            {'id':'tts/one', 'type':'speech'},
            {'id':'stt/one', 'type':'transcription'},
            {'id':'combo/chat','type':'chat'}]):
            self.assertEqual([r['id'] for r in CORE.model_entries('tts')],['tts/one'])
            self.assertEqual([r['id'] for r in CORE.model_entries('stt')],['stt/one'])

    def test_redirect_proxy_bypass_configured(self):
        # The request opener is bound to an explicit no-proxy handler.
        import urllib.request
        handlers=[h for h in CORE._OPENER.handlers if isinstance(h,urllib.request.ProxyHandler)]
        self.assertFalse(handlers, 'Configured no-proxy opener must not load environment proxies')

class OmniRoute353RegressionTests(unittest.TestCase):
    """Contracts confirmed from cheaper-inference/OmniRoute tag v3.8.53."""

    def test_audio_subtype_speech_transcription_are_distinct(self):
        rows = [
            {'id': 't/speech', 'type': 'audio', 'subtype': 'speech'},
            {'id': 's/transcribe', 'type': 'audio', 'subtype': 'transcription'},
            {'id': 'unknown/audio', 'type': 'audio'},
            {'id': 'image/stuff', 'type': 'image', 'output_modalities': ['image']},
        ]
        with patch.object(CORE.catalog, 'get', return_value=rows):
            self.assertEqual([x['id'] for x in CORE.model_entries('tts')], ['t/speech'])
            self.assertEqual([x['id'] for x in CORE.model_entries('stt')], ['s/transcribe'])

    def test_chat_catalog_uses_native_kind_and_alias_filter(self):
        rows = [
            {'id': 'model/chat', 'type': 'chat'},
            {'id': 'model/media', 'type': 'audio', 'subtype': 'speech'},
            {'id': 'model/vision', 'type': 'image'},
            {'id': 'model/legacy'},
            {'id': 'model/embed', 'type': 'embedding'},
            {'id': 'model/combo', 'type': 'combo'},
        ]
        with patch.object(CORE.catalog, 'get', return_value=rows) as get:
            selected = CORE.model_entries('chat')
        self.assertEqual([x['id'] for x in selected], ['model/chat', 'model/legacy', 'model/combo'])
        self.assertEqual(get.call_args.args, ('/models',))

    def test_model_provider_filters_typed_media_and_uses_native_query(self):
        from io import BytesIO
        mod = types.ModuleType('providers'); base = types.ModuleType('providers.base')
        class Profile:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        captured=[];mod.register_provider=captured.append;base.ProviderProfile=Profile
        with patch.dict(sys.modules, {'providers':mod, 'providers.base':base}):
            spec=importlib.util.spec_from_file_location('omni353_provider',ROOT/'model-provider/__init__.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        payload={'data':[{'id':'a/chat','type':'chat'}, {'id':'a/video','type':'video'},
                         {'id':'a/tts','type':'audio','subtype':'speech'},
                         {'id':'a/stt','type':'audio','subtype':'transcription'},
                         {'id':'a/embed','type':'embedding'}, {'id':'a/legacy'},
                         {'id':'a/chat','type':'chat'}, {'id':'a/reason','type':'chat','subtype':'reasoning'}, {'id':'a/combo','type':'combo'}]}
        opened=[]
        class FakeOpener:
            def open(self, req, timeout=8):
                opened.append((req.full_url,req.get_header('Authorization')))
                return BytesIO(json.dumps(payload).encode())
        with patch.object(module.request,'build_opener',return_value=FakeOpener()):
            ids=module.omniroute.fetch_models(api_key='secret',base_url='https://router.example/v1')
        self.assertEqual(ids, ['a/chat','a/legacy','a/reason','a/combo'])
        self.assertEqual(opened[0][0], 'https://router.example/v1/models?prefix=alias&limit=200')
        self.assertEqual(opened[0][1], 'Bearer secret')
        self.assertTrue(callable(module.omniroute.picker_catalog))
        self.assertEqual(module.omniroute.base_url_env_var, 'OMNIROUTE_BASE_URL')
        with patch.object(module.omniroute, 'fetch_models', return_value=['hook/model']) as probe:
            self.assertEqual(module.omniroute.picker_catalog(True), ['hook/model'])
            probe.assert_called_once_with()
        with patch.object(module, '_env', side_effect=lambda name: 'https://router.example/v1' if name.endswith('BASE_URL') else 'scoped-secret'), \
             patch.object(module.request, 'build_opener') as transport:
            self.assertIsNone(module.omniroute.fetch_models(api_key='', base_url='https://router.example/v1'))
            self.assertIsNone(module.omniroute.fetch_models(base_url='https://other.example/v1'))
            transport.assert_not_called()

    def test_image_without_advertised_size_does_not_set_size(self):
        from omniroute_test_backend.providers import image as im
        for model in ('zm/inclusionai/ming-image-0.1-design', 'custom/unknown'):
            with self.subTest(model=model),patch.object(im,'model_entries',return_value=[]),\
                 patch.object(im,'call_json',return_value={'data':[{'url':'https://test.invalid/x.png'}]}) as call:
                self.assertTrue(B.OmniImage().generate('sunset',model=model)['success'])
                self.assertNotIn('size',call.call_args.kwargs['payload'])

    def test_image_uses_advertised_pixel_size_only(self):
        from omniroute_test_backend.providers import image as im
        rows=[{'id':'my/image','supported_sizes':['16:9','1536x1024','1024x1536']}]
        with patch.object(im,'model_entries',return_value=rows),\
             patch.object(im,'call_json',return_value={'data':[{'url':'https://example.org/img'}]}) as call:
            B.OmniImage().generate('sunset',model='my/image',aspect_ratio='portrait')
        self.assertEqual(call.call_args.kwargs['payload']['size'],'1024x1536')

    def test_unknown_image_model_multi_reference_is_rejected(self):
        from omniroute_test_backend.providers import image as im
        import base64
        image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
        with patch.object(im,'call_json') as call:
            r=B.OmniImage().generate('update',model='openai/gpt-image-2',
                                      image_url=image,reference_image_urls=[image])
        self.assertFalse(r['success'])
        self.assertIn('up to 1',r['error'])
        call.assert_not_called()

    def test_image_capabilities_follow_configured_model(self):
        with patch.dict(os.environ, {'OMNIROUTE_IMAGE_MODEL':'openai/gpt-image-2'}):
            self.assertEqual(B.OmniImage().capabilities()['max_reference_images'],0)
        with patch.dict(os.environ, {'OMNIROUTE_IMAGE_MODEL':'codex/gpt-image-2'}):
            self.assertEqual(B.OmniImage().capabilities()['max_reference_images'],16)

    def test_xai_image_to_video_uses_image_not_image_url(self):
        from omniroute_test_backend.providers import video
        with patch.object(video,'call_json',return_value={'data':[{'url':'https://cdn.test/clip.mp4'}]}) as client:
            result=B.OmniVideo().generate('clouds',model='xai/grok-imagine-video',image_url='https://cdn.test/ref.png')
        self.assertTrue(result['success'])
        payload=client.call_args.kwargs['payload']
        self.assertEqual(payload['image'],'https://cdn.test/ref.png')
        self.assertNotIn('image_url',payload)

    def test_other_video_upstream_preserves_image_url(self):
        from omniroute_test_backend.providers import video
        with patch.object(video,'call_json',return_value={'data':[{'url':'https://cdn.test/clip.mp4'}]}) as client:
            result=B.OmniVideo().generate('clouds',model='runway/gen-3',image_url='https://cdn.test/ref.png')
        self.assertTrue(result['success'])
        self.assertEqual(client.call_args.kwargs['payload']['image_url'],'https://cdn.test/ref.png')

    def test_video_duration_beyond_ten_forwarded_if_model_has_no_limit(self):
        from omniroute_test_backend.providers import video
        with patch.object(video,'model_entries',return_value=[]),\
             patch.object(video,'call_json',return_value={'data':[{'url':'https://cdn.test/clip.mp4'}]}) as client:
            result=B.OmniVideo().generate('clouds',model='some/long',duration=90)
        self.assertTrue(result['success'])
        self.assertEqual(client.call_args.kwargs['payload']['duration'],90)

    def test_video_advertised_model_capabilities_and_duration(self):
        from omniroute_test_backend.providers import video
        row={'id':'studio/long','type':'video','media_capabilities':{
            'min_duration':2,'max_duration':120, 'aspect_ratios':['9:16'],
            'resolutions':['1080p'], 'supports_audio':True, 'supports_seed':True}}
        with patch.dict(os.environ, {'OMNIROUTE_VIDEO_MODEL':'studio/long'}),\
             patch.object(video,'model_entries',return_value=[row]),\
             patch.object(video,'call_json',return_value={'data':[{'url':'https://cdn.test/clip.mp4'}]}) as client:
            c=B.OmniVideo().capabilities()
            self.assertEqual(c['max_duration'],120)
            self.assertEqual(c['min_duration'],2)
            self.assertTrue(c['supports_seed'])
            self.assertEqual(c['aspect_ratios'],['9:16'])
            good=B.OmniVideo().generate('clouds',model='studio/long',duration=90,aspect_ratio='9:16',resolution='1080p')
            bad=B.OmniVideo().generate('clouds',model='studio/long',duration=125)
        self.assertTrue(good['success'])
        self.assertFalse(bad['success'])
        self.assertEqual(client.call_count,1)
        self.assertEqual(client.call_args.kwargs['payload']['resolution'],'1080p')

    def test_video_picker_exposes_per_model_duration_to_hermes(self):
        from omniroute_test_backend.providers import video
        row={'id':'studio/long','type':'video','media_capabilities':{
            'minDuration':2,'maxDuration':120,'modalities':['image','text']}}
        with patch.object(video,'model_entries',return_value=[row]), \
             patch.object(CORE,'model_entries',return_value=[row]):
            result=B.OmniVideo().list_models()
        self.assertEqual(result[0]['id'],'studio/long')
        self.assertEqual(result[0]['min_duration'],2)
        self.assertEqual(result[0]['max_duration'],120)
        self.assertEqual(result[0]['modalities'],['image','text'])

    def test_video_unknown_limits_are_not_advertised_as_ten_seconds(self):
        from omniroute_test_backend.providers import video
        with patch.dict(os.environ, {'OMNIROUTE_VIDEO_MODEL':'some/long'}),\
             patch.object(video,'model_entries',return_value=[]):
            caps=B.OmniVideo().capabilities()
        self.assertNotIn('max_duration',caps)
        self.assertNotIn('aspect_ratios',caps)
        self.assertNotIn('resolutions',caps)

    def test_explicit_image_size_remains_available(self):
        from omniroute_test_backend.providers import image as im
        with patch.object(im,'model_entries',return_value=[]),\
             patch.object(im,'call_json',return_value={'data':[{'url':'https://cdn.test/output.png'}]}) as call:
            out=B.OmniImage().generate('sunset',model='some/image',size='2048x1024')
        self.assertTrue(out['success'])
        self.assertEqual(call.call_args.kwargs['payload']['size'],'2048x1024')

    def test_video_multiple_images_not_silently_ignored(self):
        from omniroute_test_backend.providers import video
        with patch.object(video,'call_json') as client:
            r=B.OmniVideo().generate('clouds',model='xai/video',reference_image_urls=['a','b'])
        self.assertFalse(r['success'])
        client.assert_not_called()

    def test_http_omniroute_code_is_sanitized(self):
        from io import BytesIO
        from urllib.error import HTTPError
        body=json.dumps({'error':{'code':'MODEL_ENDPOINT_MISMATCH','message':'Bearer SENSITIVE'}}).encode()
        err=HTTPError('https://test.invalid/v1',400,'failed',{},BytesIO(body))
        with patch.dict(os.environ,{'OMNIROUTE_BASE_URL':'https://test.invalid/v1',
                                    'OMNIROUTE_API_KEY':'SENSITIVE'}),\
             patch.object(CORE._OPENER,'open',side_effect=err):
            with self.assertRaises(CORE.OmniError) as caught:
                CORE.call_json('POST','/images/generations',payload={'model':'x'})
        self.assertIn('MODEL_ENDPOINT_MISMATCH',str(caught.exception))
        self.assertNotIn('SENSITIVE',str(caught.exception))

    def test_api_path_only_allows_audited_discovery_query(self):
        with self.assertRaises(CORE.OmniError):
            CORE.call('GET','/models?api_key=bad')
        with self.assertRaises(CORE.OmniError):
            CORE.call('GET','/models?kind=chat&prefix=alias#fragment')


class CompleteCatalogTests(unittest.TestCase):
    def test_canonical_catalog_source_and_generated_copy(self):
        import ast
        self.assertEqual((ROOT/'backend/catalog_discovery.py').read_bytes(),
                         (ROOT/'model-provider/catalog_discovery.py').read_bytes())
        for path in ('backend/core.py', 'backend/dashboard/plugin_api.py', 'model-provider/__init__.py'):
            nodes = ast.parse((ROOT/path).read_text()).body
            self.assertFalse(any(isinstance(n, ast.FunctionDef) and n.name in ('_is_chat', '_fetch_catalog', '_fetch_pages') for n in nodes))

    def test_paginated_catalog_over_1000_and_encoded_cursor(self):
        from io import BytesIO
        from urllib.parse import urlsplit, parse_qs
        rows = [{'id': f'p/model {i}+&', 'type':'chat'} for i in range(1205)]
        class Opener:
            def open(self, req, timeout):
                query = parse_qs(urlsplit(req.full_url).query)
                assert query['prefix'] == ['alias']
                assert req.get_header('Authorization') == 'Bearer private-key'
                start = 0 if 'after' not in query else next(i+1 for i,r in enumerate(rows) if r['id'] == query['after'][0])
                page = rows[start:start+int(query['limit'][0])]
                return BytesIO(json.dumps({'data':page,'has_more':start+len(page)<len(rows),'last_id':page[-1]['id']}).encode())
        stats = {}
        actual = CORE._fetch_catalog('https://router.example/v1','private-key',Opener(), diagnostics=stats)
        self.assertEqual(actual, rows)
        self.assertEqual((stats['received'], stats['pages'], stats['requests']), (1205, 7, 7))
        self.assertEqual(stats['source'], 'api')
        self.assertNotIn('private-key', json.dumps(stats))

    def test_repeat_cursor_and_invalid_envelope_fail_closed(self):
        from io import BytesIO
        class Opener:
            def open(self, req, timeout):
                return BytesIO(b'{"data":[{"id":"same"}],"has_more":true,"last_id":"same"}')
        stats = {}
        with self.assertRaisesRegex(CORE.CatalogError, 'cursor'):
            CORE._fetch_catalog('https://router.example/v1','secret',Opener(), diagnostics=stats)
        self.assertEqual(stats['status'], 'error')
        self.assertEqual(stats['pages'], 2)
        self.assertNotIn('secret', json.dumps(stats))
        class Bad:
            def open(self, req, timeout):
                return BytesIO(b'{"data":null}')
        with self.assertRaisesRegex(CORE.CatalogError, 'envelope'):
            CORE._fetch_catalog('https://router.example/v1','secret',Bad())

    def test_large_page_retries_smaller_and_specialty_subtypes_stay_out(self):
        from io import BytesIO
        from urllib.parse import urlsplit, parse_qs
        limits = []
        class Opener:
            def open(self, req, timeout):
                limit = int(parse_qs(urlsplit(req.full_url).query)['limit'][0])
                limits.append(limit)
                if limit == 200:
                    return BytesIO(b'x' * (4*1024*1024+1))
                return BytesIO(b'{"data":[{"id":"ok"}],"has_more":false}')
        self.assertEqual(CORE._fetch_catalog('https://router.example/v1','secret',Opener()), [{'id':'ok'}])
        self.assertEqual(limits,[200,100])
        for row in ({'id':'r','type':'chat','subtype':'reasoning'},
                    {'id':'c','type':'combo'}, {'id':'legacy'}):
            self.assertTrue(CORE.is_chat_model(row))
        for row in ({'id':'tts','type':'chat','subtype':'speech'},
                    {'id':'emb','type':'embedding'}, {'id':'bad','subtype':'transcription'}):
            self.assertFalse(CORE.is_chat_model(row))


    def test_cache_diagnostics_and_no_credential_in_logs(self):
        with patch.dict(os.environ, {'OMNIROUTE_BASE_URL':'https://private.example/v1',
                                     'OMNIROUTE_API_KEY':'private-key'}):
            with patch.object(CORE, '_fetch_catalog', return_value=[{'id':'demo/chat'}]) as fetch:
                local = CORE.Catalog()
                first, second = {}, {}
                self.assertEqual(local.get('/models', diagnostics=first), local.get('/models', diagnostics=second))
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(first['source'], 'api')
                self.assertEqual(second['source'], 'cache')
                self.assertEqual(second['requests'], 0)
                self.assertNotIn('private-key', json.dumps(second))
            with patch.object(CORE.catalog, 'get', return_value=[{'id':'demo/chat'}]):
                with self.assertLogs(CORE.__name__, level='INFO') as logs:
                    CORE.model_entries('chat')
                self.assertIn('"delivered": 1', logs.output[0])
                self.assertNotIn('private-key', logs.output[0])


if __name__=='__main__':unittest.main()
