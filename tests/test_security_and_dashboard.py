"""Hardening regressions beyond the Hermes API doubles in test_suite.py."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from test_suite import B, CORE, ROOT
from omniroute_test_backend.providers import audio


class MultipartSafety(unittest.TestCase):
    def test_model_crlf_injection_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'mic.wav'; file.write_bytes(b'RIFFWAVE')
            with patch.object(audio, 'call') as send:
                result = B.OmniSTT().transcribe(str(file), model='good\r\nX-Forged: 1')
            self.assertFalse(result['success'])
            send.assert_not_called()

    def test_language_crlf_injection_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'mic.wav'; file.write_bytes(b'RIFFWAVE')
            with patch.object(audio, 'call') as send:
                result = B.OmniSTT().transcribe(str(file), model='model/id', language='en\r\nX: 1')
            self.assertFalse(result['success'])
            send.assert_not_called()

    def test_filename_control_characters_are_escaped(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'hello\nContent-Type:evil.wav'
            file.write_bytes(b'RIFFWAVE')
            data, ctype = audio._multipart_upload(file, 'model/id', None)
            self.assertIn(b'filename="hello_Content-Type:evil.wav"', data)
            self.assertNotIn(b'filename="hello\n', data)
            self.assertIn(b'Content-Disposition: form-data; name="file"', data)
            self.assertIn('multipart/form-data; boundary=', ctype)

    def test_empty_model_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'mic.wav'; file.write_bytes(b'audio')
            with self.assertRaises(CORE.OmniError):
                audio._multipart_upload(file, ' ', None)

    def test_multipart_valid_utf8_values(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'microfone.wav'; file.write_bytes(b'RIFFWAVE')
            data, _ = audio._multipart_upload(file, 'provedor/modelo', 'pt-BR')
            self.assertIn(b'provedor/modelo', data)
            self.assertIn(b'pt-BR', data)
            self.assertIn(b'RIFFWAVE', data)


class SpeechFormats(unittest.TestCase):
    def test_mpeg_response_to_wav_request_saved_as_mp3(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(audio,'call',return_value=(b'ID3\x04test','audio/mpeg')):
                actual = B.OmniTTS().synthesize('ola', str(Path(directory)/'target.wav'),
                                                model='tts/model',format='wav')
            self.assertEqual(Path(actual).suffix,'.mp3')
            # The output directory is removed when the temporary context exits.
            self.assertTrue(actual.endswith('.mp3'))

    def test_wav_magic_overrides_incorrect_content_type(self):
        self.assertEqual(audio._audio_extension(b'RIFF\x00\x00\x00\x00WAVE', 'audio/mpeg', 'mp3'),'wav')

    def test_json_is_not_saved_as_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(audio,'call',return_value=(b'{"error":"bad"}','application/json')):
                with self.assertRaises(CORE.OmniError):
                    B.OmniTTS().synthesize('ola',str(Path(directory)/'target.wav'),model='tts/model')

    def test_unconfigured_voice_catalog_not_fabricated(self):
        with patch.dict('os.environ',{'OMNIROUTE_TTS_VOICE':''}):
            self.assertEqual(B.OmniTTS().list_voices(),[])
            self.assertIsNone(B.OmniTTS().default_voice())

    def test_voice_only_sent_when_configured(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('os.environ',{'OMNIROUTE_TTS_VOICE':''}), \
             patch.object(audio,'call',return_value=(b'ID3voice','audio/mpeg')) as send:
            B.OmniTTS().synthesize('ola',str(Path(directory)/'target.mp3'),model='tts/model')
            self.assertNotIn('voice',send.call_args.kwargs['payload'])


class MarketplaceConfiguration(unittest.TestCase):
    def test_manifests_allow_web_configuration_without_install_prompt(self):
        import yaml
        for name in ('backend','model-provider'):
            with self.subTest(name=name):
                manifest = yaml.safe_load((ROOT/name/'plugin.yaml').read_text())
                self.assertEqual(manifest.get('requires_env',[]),[])
                optional = manifest.get('optional_env',[])
                key = next(x for x in optional if x['name']=='OMNIROUTE_API_KEY')
                self.assertTrue(key.get('secret'))
                self.assertEqual(manifest['requires_hermes'],'>=0.23.2')

    def test_catalog_templates_match_declared_env_capabilities(self):
        import yaml
        for f in (ROOT/'catalog').glob('*.template'):
            data=yaml.safe_load(f.read_text())
            self.assertEqual(data['capabilities']['requires_env'],[])

    def test_hermes_validator_ref_is_fixed_in_ci(self):
        contents=(ROOT/'.github/workflows/tests.yml').read_text()
        self.assertEqual(contents.count('hermes-ref: v0.23.2'),2)

    def test_hermes_ui_has_activation_and_preferences(self):
        js=(ROOT/'backend/dashboard/dist/index.js').read_text()
        for endpoint in ('/activate-chat', '/preference', '/models', '/connection'):
            self.assertIn(endpoint,js)

    def test_api_reads_secrets_from_scope(self):
        code=(ROOT/'backend/dashboard/plugin_api.py').read_text()
        self.assertIn('from agent.secret_scope import get_secret_str',code)
        self.assertIn("_secret('OMNIROUTE_API_KEY')",code)
        self.assertNotIn("_value('OMNIROUTE_API_KEY')",code)

    def test_no_bytecode_or_binaries_in_delivery_tree(self):
        # Python creates __pycache__ during tests. The marketplace rule applies
        # to files shipped in the Git commit, not runtime-generated bytecode.
        forbidden = {'.pyc', '.pyo', '.so', '.dll', '.exe', '.wasm', '.dylib'}
        result = subprocess.run(
            ['git', 'ls-files', '--cached', '-z'],
            cwd=ROOT, capture_output=True, check=False,
        )
        if result.returncode == 0:
            files = [
                ROOT / item.decode('utf-8', errors='surrogateescape')
                for item in result.stdout.split(b'\\0') if item
            ]
        else:
            # Extracted source archives have no .git directory. Ignore only
            # interpreter/test caches that are not part of the distribution.
            files = [
                p for p in ROOT.rglob('*') if p.is_file()
                and not {'__pycache__', '.pytest_cache', '.git', '.venv'}.intersection(p.parts)
            ]
        disallowed = [p.relative_to(ROOT).as_posix() for p in files if p.suffix.lower() in forbidden]
        self.assertFalse(disallowed, f'Forbidden versioned executables: {disallowed}')


if __name__ == '__main__':
    unittest.main()


class DashboardApiSimulation(unittest.TestCase):
    """API contract exercise with a profile-scoped Hermes config/secret double."""

    def test_connection_activation_and_profile_isolation(self):
        import importlib.util
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        profiles = {
            'alpha': {'env': {}, 'config': {'model': {'provider': 'other'}}},
            'beta': {'env': {}, 'config': {'model': {'provider': 'other'}}},
        }
        current = {'name': 'alpha'}
        def state(): return profiles[current['name']]
        def get_env(name): return state()['env'].get(name, '')
        def save_env(name, value): state()['env'][name] = value
        def set_config(key, value): state()['config']['model'][key.split('.')[-1]] = value

        cfg_module = types.ModuleType('hermes_cli.config')
        cfg_module.get_env_value = get_env
        cfg_module.save_env_value = save_env
        cfg_module.save_env_value_secure = save_env
        cfg_module.load_config = lambda: state()['config']
        cfg_module.set_config_value = set_config
        cli_module = types.ModuleType('hermes_cli');cli_module.__path__=[]
        scope = sys.modules['agent.secret_scope']
        with patch.dict(sys.modules, {'hermes_cli': cli_module, 'hermes_cli.config': cfg_module}), \
             patch.object(scope, 'get_secret_str', lambda k, default='': get_env(k) or default):
            spec = importlib.util.spec_from_file_location('omni_dashboard_profile_test',
                                   ROOT/'backend/dashboard/plugin_api.py')
            app_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(app_mod)
            app = FastAPI()
            app.include_router(app_mod.router, prefix='/api/plugins/omniroute-media')
            with TestClient(app) as client:
                root='/api/plugins/omniroute-media'
                response=client.get(root+'/status')
                self.assertEqual(response.status_code,200)
                self.assertFalse(response.json()['api_key_configured'])
                response=client.post(root+'/connection', json={
                    'base_url':'https://router.example/v1','api_key':'secret-alpha'})
                self.assertEqual(response.status_code,200)
                self.assertTrue(response.json()['api_key_configured'])
                self.assertNotIn('secret-alpha', json.dumps(response.json()))
                response=client.post(root+'/model', json={'kind':'chat','model':'llm/alpha'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(state()['config']['model']['provider'],'other')
                response=client.post(root+'/activate-chat', json={})
                self.assertEqual(response.status_code,200)
                self.assertEqual(state()['config']['model']['provider'],'omniroute')
                self.assertEqual(state()['config']['model']['default'],'llm/alpha')
                response=client.post(root+'/preference',json={'kind':'tts_voice','value':'MyVoice'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['preferences']['tts_voice'],'MyVoice')
                current['name']='beta'
                response=client.get(root+'/status')
                self.assertFalse(response.json()['api_key_configured'])
                self.assertEqual(response.json()['base_url'],'')
                self.assertEqual(response.json()['models']['chat'],'')
                self.assertNotIn('secret-alpha',json.dumps(response.json()))
                self.assertEqual(client.post(root+'/activate-chat',json={}).status_code,409)


class ModelCapabilityTruthfulness(unittest.TestCase):
    def test_unconfigured_image_advertises_only_text(self):
        with patch.dict('os.environ',{'OMNIROUTE_IMAGE_MODEL':''}):
            c=B.OmniImage().capabilities()
            self.assertEqual(c['modalities'],['text'])
            self.assertEqual(c['max_reference_images'],0)

    def test_codex_edit_capability_when_chosen(self):
        with patch.dict('os.environ',{'OMNIROUTE_IMAGE_MODEL':'codex/gpt-image-2'}):
            c=B.OmniImage().capabilities()
            self.assertIn('image',c['modalities'])
            self.assertEqual(c['max_reference_images'],16)

    def test_unknown_video_does_not_advertise_image_input(self):
        from omniroute_test_backend.providers import video
        with patch.object(video,'model_entries',return_value=[]), \
             patch.dict('os.environ',{'OMNIROUTE_VIDEO_MODEL':'unknown/video'}):
            self.assertEqual(B.OmniVideo().capabilities()['modalities'],['text'])

    def test_xai_video_supports_image_input(self):
        from omniroute_test_backend.providers import video
        rows=[{'id':'xai/grok-imagine-video','type':'video','input_modalities':['text']}]
        with patch.object(video,'model_entries',return_value=rows), \
             patch.dict('os.environ',{'OMNIROUTE_VIDEO_MODEL':'xai/grok-imagine-video'}):
            self.assertIn('image',B.OmniVideo().capabilities()['modalities'])


class VideoReferenceSecurity(unittest.TestCase):
    def test_model_generated_reference_must_be_public_https(self):
        from omniroute_test_backend.providers import video
        for url in ('file:///etc/passwd', 'http://127.0.0.1/media.png',
                    'https://127.0.0.1/image.png', 'https://user:pass@public.example/image.png',
                    'https://omniroute.home.arpa/img.png'):
            with self.subTest(url=url), patch.object(video,'call_json') as req:
                out=B.OmniVideo().generate('animate',model='xai/grok-imagine-video',image_url=url)
                self.assertFalse(out['success'])
                req.assert_not_called()

    def test_public_https_reference_allowed(self):
        from omniroute_test_backend.providers import video
        self.assertEqual(video._validated_reference_url('https://media.example.com/img.png?sig=abc'),
                         'https://media.example.com/img.png?sig=abc')
