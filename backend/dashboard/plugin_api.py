"""Hermes Dashboard extension: no secrets ever returned to the browser.

Uses the host's profile-scoped env persistence API. All handlers are sync to
keep blocking network access out of the gateway asyncio event loop.
"""
from __future__ import annotations

import json
import logging
from urllib import request, error, parse
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from agent.secret_scope import get_secret_str
from hermes_cli.config import get_env_value, save_env_value, save_env_value_secure, load_config, set_config_value

# The dashboard may live outside the backend Python import package. Keep
# endpoint validation self-contained but identical to backend/core.py.
import ipaddress

router = APIRouter()

KINDS = {
    'chat': 'OMNIROUTE_CHAT_MODEL',
    'image': 'OMNIROUTE_IMAGE_MODEL',
    'video': 'OMNIROUTE_VIDEO_MODEL',
    'tts': 'OMNIROUTE_TTS_MODEL',
    'stt': 'OMNIROUTE_STT_MODEL',
}

PREFERENCES = {'tts_voice': 'OMNIROUTE_TTS_VOICE',
               'search_provider': 'OMNIROUTE_SEARCH_PROVIDER',
               'fetch_provider': 'OMNIROUTE_FETCH_PROVIDER'}


def _value(name: str) -> str:
    return str(get_env_value(name) or '').strip()


def _secret(name: str) -> str:
    """Credentials MUST come from the active Hermes profile secret scope."""
    return str(get_secret_str(name) or '').strip()


def _native_model_is_omniroute() -> bool:
    cfg = load_config()
    model = cfg.get('model') if isinstance(cfg, dict) else None
    return isinstance(model, dict) and model.get('provider') == 'omniroute'



def _valid_url(url: str) -> str:
    url = url.strip().rstrip('/')
    try:
        parsed = parse.urlsplit(url)
    except ValueError:
        raise HTTPException(status_code=422, detail='Malformed API URL') from None
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or not parsed.path.rstrip('/').endswith(('/v1','/api/v1'))
            or any(c in url for c in '\r\n\t')):
        raise HTTPException(status_code=422, detail='Use an API root ending in /v1 or /api/v1, without credentials or query')
    try:
        _ = parsed.port
    except ValueError:
        raise HTTPException(status_code=422, detail='Invalid API URL port') from None
    if parsed.scheme == 'http':
        host = parsed.hostname.lower().rstrip('.')
        try:
            addr = ipaddress.ip_address(host)
            local = addr.is_private or addr.is_loopback or addr.is_link_local
        except ValueError:
            local = host in {'localhost', 'host.docker.internal'} or host.endswith(('.home.arpa','.local','.internal'))
        if not local:
            raise HTTPException(status_code=422, detail='Use HTTPS for public OmniRoute endpoints')
    return url


class Connection(BaseModel):
    base_url: str = Field(default='', max_length=1024)
    api_key: str = Field(default='', max_length=8192)


class ModelSelection(BaseModel):
    kind: str
    model: str = Field(min_length=1, max_length=256)


@router.get('/status')
def status():
    return {
        'base_url': _value('OMNIROUTE_BASE_URL'),
        'api_key_configured': bool(_secret('OMNIROUTE_API_KEY')),
        'models': {kind: _value(env) for kind, env in KINDS.items()},
        'preferences': {name: _value(env) for name, env in PREFERENCES.items()},
        'native_chat_provider_active': _native_model_is_omniroute(),
        'reload_may_be_needed': True,
    }


@router.post('/connection')
def save_connection(body: Connection):
    if not body.base_url and not body.api_key:
        raise HTTPException(status_code=422, detail='Supply a base URL or a new API key')
    # Validate the entire request BEFORE writing any configuration keys.
    checked = _valid_url(body.base_url) if body.base_url else None
    if body.api_key and any(ord(c) < 32 or ord(c) == 127 for c in body.api_key):
        raise HTTPException(status_code=422, detail='API key cannot contain control characters')
    if checked:
        save_env_value('OMNIROUTE_BASE_URL', checked)
        if _native_model_is_omniroute():
            set_config_value('model.base_url', checked)
    if body.api_key:
        save_env_value_secure('OMNIROUTE_API_KEY', body.api_key)
    result = status()
    # The current request may have an immutable secret snapshot loaded before
    # the save. Report the new key as configured without exposing its value.
    if body.api_key:
        result['api_key_configured'] = True
    return result


@router.post('/model')
def save_model(body: ModelSelection):
    env = KINDS.get(body.kind)
    if not env:
        raise HTTPException(status_code=422, detail='Invalid model category')
    if any(ord(c) < 32 or ord(c) == 127 for c in body.model):
        raise HTTPException(status_code=422, detail='Invalid model ID')
    save_env_value(env, body.model)
    if body.kind == 'chat' and _native_model_is_omniroute():
        set_config_value('model.default', body.model)
    return status()


class PreferenceSelection(BaseModel):
    kind: str
    value: str = Field(default='', max_length=160)


@router.post('/preference')
def save_preference(body: PreferenceSelection):
    env = PREFERENCES.get(body.kind)
    if not env:
        raise HTTPException(status_code=422, detail='Unknown preference')
    if any(ord(c) < 32 or ord(c) == 127 for c in body.value):
        raise HTTPException(status_code=422, detail='Invalid preference value')
    save_env_value(env, body.value.strip())
    return status()


@router.post('/activate-chat')
def activate_chat():
    """Explicit user action: switch Hermes chat to the configured OmniRoute."""
    url = _value('OMNIROUTE_BASE_URL')
    if not url or not _secret('OMNIROUTE_API_KEY'):
        raise HTTPException(status_code=409, detail='Set OmniRoute URL and API key first')
    url = _valid_url(url)
    selected = _value('OMNIROUTE_CHAT_MODEL')
    if not selected:
        raise HTTPException(status_code=409, detail='Select and save an OmniRoute chat model first')
    # Validate all first, then persist the native Hermes config with its own
    # supported config writer. This route never auto-activates other providers.
    set_config_value('model.base_url', url)
    set_config_value('model.default', selected)
    set_config_value('model.provider', 'omniroute')
    return status()


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


# The Hermes loader may import this entrypoint without a package context.
# Load the sibling catalog module by absolute file path; do not change sys.path.
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

_catalog_spec = spec_from_file_location(__name__ + '_catalog_discovery',
                                        Path(__file__).resolve().parents[1] / 'catalog_discovery.py')
_catalog_module = module_from_spec(_catalog_spec)
_catalog_spec.loader.exec_module(_catalog_module)
CatalogError = _catalog_module.CatalogError
_fetch_catalog = _catalog_module._fetch_catalog
_is_chat = _catalog_module._is_chat
select_rows = _catalog_module.select_rows
catalog_diagnostics = _catalog_module.catalog_diagnostics
new_diagnostics = _catalog_module.new_diagnostics
log_diagnostics = _catalog_module.log_diagnostics

def _matches_kind(row, kind):
    return _catalog_module._matches_kind(row, kind)


@router.get('/models')
def models(kind: str = 'chat'):
    if kind not in KINDS: raise HTTPException(status_code=422, detail='Invalid model category')
    base = _value('OMNIROUTE_BASE_URL')
    key = _secret('OMNIROUTE_API_KEY')
    if not base or not key: raise HTTPException(status_code=409, detail='Configure OmniRoute first')
    path = ('/images/generations' if kind == 'image' else
            '/videos/generations' if kind == 'video' else '/models')
    root = _valid_url(base)
    opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
    stats = new_diagnostics()
    try:
        rows = _fetch_catalog(root, key, opener, path=path, diagnostics=stats)
    except CatalogError as exc:
        stats.update(status='error', error=str(exc))
        details = catalog_diagnostics([], kind, path, stats=stats)
        log_diagnostics(logging.getLogger(__name__), details)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    selected = select_rows(rows, kind, path)
    # Keep the exact inference ID; the route label is display-only. The
    # first segment of a namespaced ID is the OmniRoute routing alias, not
    # necessarily the upstream manufacturer's name.
    result = []
    for row in selected:
        model_id = row['id']
        owner = row.get('owned_by') if isinstance(row.get('owned_by'), str) else ''
        source_root = row.get('root') if isinstance(row.get('root'), str) else ''
        if not owner and row.get('type') == 'combo':
            owner = 'combo'
        route_label = model_id if '/' in model_id or not owner else owner + '/' + model_id
        result.append({'id': model_id, 'label': str(row.get('name') or model_id),
                       'route_label': route_label, 'owned_by': owner, 'root': source_root})
    details = catalog_diagnostics(rows, kind, path, stats=stats, delivered=len(result))
    log_diagnostics(logging.getLogger(__name__), details)
    return {'models': result, 'kind': kind, 'diagnostics': details}
