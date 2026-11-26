"""Hermes Dashboard extension: no secrets ever returned to the browser.

Uses the host's profile-scoped env persistence API. All handlers are sync to
keep blocking network access out of the gateway asyncio event loop.
"""
from __future__ import annotations

import json
import http.client
import time
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


# Kept identical in the independently installable provider, backend and dashboard.
# The dashboard is loaded directly by Hermes, outside the backend package.
class CatalogError(RuntimeError):
    pass


def _is_chat(row):
    if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'].strip():
        return False
    category = str(row.get('type') or '').strip().lower()
    subtype = str(row.get('subtype') or '').strip().lower()
    non_chat = {'audio', 'speech', 'tts', 'transcription', 'stt', 'audio-speech',
                'audio-transcriptions', 'embedding', 'embeddings', 'image', 'images',
                'video', 'music', 'rerank', 'moderation'}
    # Explicit chat subtypes (e.g. reasoning) are valid. Untyped legacy entries
    # remain compatible, but an untyped entry with an unknown subtype is ambiguous.
    return (category in {'chat', 'text', 'language', 'llm', 'combo', ''}
            and subtype not in non_chat and (bool(category) or not subtype))


def _fetch_catalog(root, key, opener, timeout=20.0, path='/models'):
    """Retrieve every authorized page, never report a partial catalog as success."""
    if not key or any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise CatalogError('Invalid OmniRoute API key')
    if path not in {'/models', '/images/generations', '/videos/generations'}:
        raise CatalogError('Invalid catalog endpoint')
    page_size = 200
    max_bytes = 4 * 1024 * 1024
    cursor = None
    seen = set()
    rows = []
    total_bytes = 0
    deadline = time.monotonic() + 180
    for _ in range(1000):
        # Only internally constructed query parameters; never follow a server URL.
        # kind=chat matches only literal chat (or untyped) and can omit combos.
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CatalogError('OmniRoute catalog discovery exceeded its time budget')
            query = [('prefix', 'alias'), ('limit', str(page_size))]
            if cursor is not None:
                query.append(('after', cursor))
            url = root + path
            if path == '/models':
                url += '?' + parse.urlencode(query)
            try:
                req = request.Request(url, headers={
                    'Authorization': 'Bearer ' + key, 'Accept': 'application/json',
                    'User-Agent': 'hermes-omniroute-community/0.4.0-beta.2',
                })
                with opener.open(req, timeout=min(timeout, remaining)) as response:
                    raw = response.read(max_bytes + 1)
            except error.HTTPError as exc:
                raise CatalogError(f'OmniRoute catalog HTTP {exc.code}') from None
            except (error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException) as exc:
                raise CatalogError(f'OmniRoute catalog connection failure ({type(exc).__name__})') from None
            if len(raw) <= max_bytes:
                break
            if path != '/models' or page_size == 1:
                raise CatalogError('OmniRoute catalog page exceeds 4 MiB')
            page_size = max(1, page_size // 2)
        total_bytes += len(raw)
        if total_bytes > 64 * 1024 * 1024:
            raise CatalogError('OmniRoute catalog exceeded its 64 MiB total safety budget')
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            raise CatalogError('OmniRoute catalog returned invalid JSON') from None
        if not isinstance(body, dict) or body.get('error') or not isinstance(body.get('data'), list):
            raise CatalogError('OmniRoute catalog returned an invalid envelope')
        page = body['data']
        if any(not isinstance(row, dict) for row in page):
            raise CatalogError('OmniRoute catalog contains an invalid row')
        rows.extend(page)
        more = body.get('has_more')
        if more is None and cursor is None:
            # Older gateways may return a full unpaged response.
            return rows
        if more is False:
            return rows
        if more is not True or path != '/models' or not page:
            raise CatalogError('OmniRoute catalog returned invalid pagination metadata')
        next_cursor = body.get('last_id')
        if (not isinstance(next_cursor, str) or not next_cursor or
                next_cursor != page[-1].get('id') or next_cursor in seen or
                len(next_cursor) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in next_cursor)):
            raise CatalogError('OmniRoute catalog cursor is invalid or repeated')
        seen.add(next_cursor)
        cursor = next_cursor
    raise CatalogError('OmniRoute catalog exceeded its page safety budget')


def _matches_kind(row: dict, kind: str) -> bool:
    """Mirror the OmniRoute 3.8.53 model taxonomy without guessing audio roles."""
    if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'].strip():
        return False
    category = str(row.get('type') or 'chat').strip().lower()
    subtype = str(row.get('subtype') or '').strip().lower()
    if kind == 'chat':
        return _is_chat(row)
    if kind == 'image':
        vals = row.get('input_modalities')
        return not isinstance(vals, list) or not vals or 'text' in vals
    if kind == 'video':
        return category == 'video'
    if category == 'audio' and subtype:
        return subtype in ({'speech', 'tts'} if kind == 'tts' else {'transcription', 'stt'})
    targets = {'tts': {'tts', 'speech', 'audio-speech'},
               'stt': {'stt', 'transcription', 'audio-transcriptions'}}
    values = [row.get('type'), row.get('modality'), row.get('category')]
    for field in ('supportedEndpoints', 'supported_endpoints', 'endpoints'):
        if isinstance(row.get(field), list):
            values.extend(row[field])
    return bool({str(v).lower() for v in values if v} & targets.get(kind, set()))


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
    try:
        rows = _fetch_catalog(root, key, opener, path=path)
    except CatalogError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    result = {}
    for row in rows:
        if _matches_kind(row, kind):
            result.setdefault(row['id'], {'id': row['id'], 'label': str(row.get('name') or row['id'])})
    return {'models': list(result.values()), 'kind': kind}
