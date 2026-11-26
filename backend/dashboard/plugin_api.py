"""Hermes Dashboard extension: no secrets ever returned to the browser.

Uses the host's profile-scoped env persistence API. All handlers are sync to
keep blocking network access out of the gateway asyncio event loop.
"""
from __future__ import annotations

import json
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
    read_token: str = Field(default='', max_length=8192)


class ModelSelection(BaseModel):
    kind: str
    model: str = Field(min_length=1, max_length=256)


@router.get('/status')
def status():
    return {
        'base_url': _value('OMNIROUTE_BASE_URL'),
        'api_key_configured': bool(_secret('OMNIROUTE_API_KEY')),
        'read_token_configured': bool(_secret('OMNIROUTE_READ_TOKEN')),
        'models': {kind: _value(env) for kind, env in KINDS.items()},
        'preferences': {name: _value(env) for name, env in PREFERENCES.items()},
        'native_chat_provider_active': _native_model_is_omniroute(),
        'reload_may_be_needed': True,
    }


@router.post('/connection')
def save_connection(body: Connection):
    if not body.base_url and not body.api_key and not body.read_token:
        raise HTTPException(status_code=422, detail='Supply a base URL or a new API key')
    # Validate the entire request BEFORE writing any configuration keys.
    checked = _valid_url(body.base_url) if body.base_url else None
    if body.api_key and any(ord(c) < 32 or ord(c) == 127 for c in body.api_key):
        raise HTTPException(status_code=422, detail='API key cannot contain control characters')
    if body.read_token and any(ord(c) < 32 or ord(c) == 127 for c in body.read_token):
        raise HTTPException(status_code=422, detail='Read token cannot contain control characters')
    if body.read_token and not (checked or _value('OMNIROUTE_BASE_URL')).startswith('https://'):
        raise HTTPException(status_code=422, detail='Management token requires HTTPS')
    if checked:
        save_env_value('OMNIROUTE_BASE_URL', checked)
        if _native_model_is_omniroute():
            set_config_value('model.base_url', checked)
    if body.api_key:
        save_env_value_secure('OMNIROUTE_API_KEY', body.api_key)
    if body.read_token:
        save_env_value_secure('OMNIROUTE_READ_TOKEN', body.read_token)
    result = status()
    if body.read_token:
        result['read_token_configured'] = True
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


def _matches_kind(row: dict, kind: str) -> bool:
    """Mirror the OmniRoute 3.8.53 model taxonomy without guessing audio roles."""
    if not isinstance(row.get('id'), str) or not row['id'].strip():
        return False
    category = str(row.get('type') or 'chat').strip().lower()
    subtype = str(row.get('subtype') or '').strip().lower()
    if kind == 'chat':
        return category in {'chat', 'text', 'language', 'llm', 'combo'} and not subtype
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
            '/videos/generations' if kind == 'video' else
            '/models?kind=chat&prefix=alias' if kind == 'chat' else '/models')
    url = _valid_url(base) + path
    opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
    req = request.Request(url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json',
                                        'User-Agent': 'hermes-omniroute-community/0.3.2-beta.1'})
    try:
        with opener.open(req, timeout=12) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024: raise ValueError('Model catalog too large')
        body = json.loads(raw)
    except (error.URLError, ValueError, OSError):
        raise HTTPException(status_code=502, detail='Unable to retrieve the OmniRoute model catalog') from None
    rows = body.get('data') if isinstance(body, dict) else None
    if not isinstance(rows, list): rows = []
    result = []
    for row in rows:
        if _matches_kind(row, kind):
            result.append({'id': row['id'], 'label': str(row.get('name') or row['id'])})
    return {'models': result[:1000], 'kind': kind}


# Read-only general discovery. The existing category-specific picker remains
# compatible with older Hermes and OmniRoute installations.
DISCOVERY_KINDS = ('chat', 'embedding', 'image', 'audio', 'video', 'rerank', 'moderation', 'music')
DISCOVERY_CAPS = ('tool_calling', 'reasoning', 'thinking', 'vision',
                  'structured_output', 'attachment', 'temperature')


class DiscoveryFilters(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: list(DISCOVERY_KINDS), max_length=8)
    capabilities: list[str] = Field(default_factory=list, max_length=7)
    match: str = 'and'
    configured_only: bool = True
    free_only: bool = False
    include_combos: bool = True
    min_context: int = Field(default=0, ge=0, le=100000000)
    q: str = Field(default='', max_length=200)


def _discovery_query(filters: DiscoveryFilters) -> str:
    if (not set(filters.kinds) <= set(DISCOVERY_KINDS) or
            not set(filters.capabilities) <= set(DISCOVERY_CAPS) or
            filters.match not in {'and', 'or'}):
        raise HTTPException(status_code=422, detail='Invalid discovery filter')
    params = {'prefix': 'canonical'}
    if filters.configured_only:
        params['configuredOnly'] = 'true'
    if len(set(filters.kinds)) == 1:
        params['kind'] = filters.kinds[0]
    if filters.capabilities and (filters.match == 'and' or len(set(filters.capabilities)) == 1):
        params['capability'] = ','.join(dict.fromkeys(filters.capabilities))
    if filters.min_context:
        params['min_context'] = str(filters.min_context)
    if filters.q.strip():
        params['q'] = filters.q.strip()
    return '/models?' + parse.urlencode(params)


def _discovery_get(url: str, credential: str) -> dict:
    if not credential or any(ord(c) < 32 or ord(c) == 127 for c in credential):
        raise HTTPException(status_code=409, detail='Configure OmniRoute credentials first')
    opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
    req = request.Request(url, headers={'Authorization': 'Bearer ' + credential,
                                       'Accept': 'application/json'})
    try:
        with opener.open(req, timeout=15) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('Response too large')
        body = json.loads(raw)
        if not isinstance(body, dict) or body.get('error'):
            raise ValueError('Unexpected response')
        return body
    except (error.URLError, ValueError, OSError):
        raise HTTPException(status_code=502, detail='OmniRoute discovery request failed') from None


def _management_root(base: str) -> str:
    return base[:-len('/api/v1')] + '/api' if base.endswith('/api/v1') else base[:-len('/v1')] + '/api'


def _free_index(rows: list) -> dict:
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        provider, model = row.get('provider'), row.get('modelId')
        if not isinstance(provider, str) or not isinstance(model, str):
            continue
        if row.get('freeType') not in {'recurring-daily', 'recurring-monthly',
                'recurring-uncapped', 'recurring-credit', 'one-time-initial', 'keyless'}:
            continue
        result[(provider, model)] = row
    return result


def _filtered_rows(rows: list, filters: DiscoveryFilters, free: dict, rankings: dict) -> list:
    result = {}
    kinds = set(filters.kinds)
    caps = set(filters.capabilities)
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier, owner = row.get('id'), row.get('owned_by')
        if not isinstance(identifier, str) or not identifier or len(identifier) > 256:
            continue
        if not isinstance(owner, str):
            continue
        kind = row.get('type') or 'chat'
        if not isinstance(kind, str) or kind not in kinds:
            continue
        if not filters.include_combos and owner == 'combo':
            continue
        flags = row.get('capabilities')
        flags = flags if isinstance(flags, dict) else {}
        matches = [flags.get(cap) is True for cap in caps]
        if matches and not (all(matches) if filters.match == 'and' else any(matches)):
            continue
        context = row.get('context_length')
        if filters.min_context and (not isinstance(context, (float, int)) or context < filters.min_context):
            continue
        root = row.get('root')
        # No suffix stripping or name matching: variants and aliases may have
        # distinct prices. Combos are not proven free by their names or ranking.
        budget = free.get((owner, root)) if isinstance(root, str) and owner != 'combo' else None
        if filters.free_only and not budget:
            continue
        rank = rankings.get(owner, {})
        result[identifier] = {'id': identifier, 'label': str(row.get('display_name') or row.get('name') or identifier)[:256],
                              'kind': kind, 'provider': owner, 'context_length': context,
                              'capabilities': [cap for cap in DISCOVERY_CAPS if flags.get(cap) is True],
                              'free_type': budget.get('freeType') if budget else None,
                              'free_metadata': {f: budget.get(f) for f in ('monthlyTokens', 'creditTokens', 'poolKey', 'tos', 'hardStopGuaranteed', 'trainsOnPrompts', 'eligibilityGate')} if budget else None,
                              'provider_state': rank.get('state')}
    return list(result.values())


@router.post('/discover-models')
def discover_models(filters: DiscoveryFilters):
    path = _discovery_query(filters)
    if not filters.kinds:
        return {'models': [], 'count': 0, 'warnings': []}
    base = _value('OMNIROUTE_BASE_URL')
    key = _secret('OMNIROUTE_API_KEY')
    if not base or not key:
        raise HTTPException(status_code=409, detail='Configure OmniRoute first')
    base = _valid_url(base)
    body = _discovery_get(base + path, key)
    rows = body.get('data')
    if not isinstance(rows, list) or body.get('has_more') is True:
        raise HTTPException(status_code=502, detail='Incomplete OmniRoute catalog')
    warnings = []
    free = {}
    rankings = {}
    summary = None
    token = _secret('OMNIROUTE_READ_TOKEN')
    # A separate read-only token is preferred. Never send a management
    # credential over plain HTTP, or silently escalate privileges.
    management = token or key
    if base.startswith('https://'):
        root = _management_root(base)
        if token or filters.free_only:
            try:
                catalog = _discovery_get(root + '/free-models', management).get('models')
                if not isinstance(catalog, list) or not catalog:
                    raise HTTPException(status_code=502, detail='Free catalog unavailable')
                free = _free_index(catalog)
            except HTTPException:
                if filters.free_only:
                    raise HTTPException(status_code=502, detail='Free catalog unavailable; configure a read token') from None
                warnings.append('Free catalog unavailable')
        if token:
            try:
                items = _discovery_get(root + '/free-provider-rankings?configuredOnly=true&availableOnly=true&withUsage=true&sortBy=reliability&limit=100', token).get('rankings')
                if not isinstance(items, list):
                    raise ValueError('Invalid rankings')
                rankings = {r['id']: {'state': r['reliability'].get('state')}
                            for r in items if isinstance(r, dict) and isinstance(r.get('id'), str)
                            and isinstance(r.get('reliability'), dict)}
            except (HTTPException, ValueError):
                warnings.append('Provider rankings unavailable')
            try:
                data = _discovery_get(root + '/free-tier/summary', token)
                summary = {k: data.get(k) for k in ('modelCount', 'poolCount', 'steadyRecurringTokens',
                                                     'catalogUpdatedAt', 'catalogSource')}
                # Summary is a global catalog estimate, never an account balance.
                budgets = data.get('perModel')
                if isinstance(budgets, list) and free:
                    detailed = _free_index(budgets)
                    # Only enrich existing exact matches, never promote an
                    # unknown row based on global or provider-level totals.
                    free = {k: dict(v, **{f: detailed[k][f] for f in
                             ('hardStopGuaranteed', 'trainsOnPrompts', 'eligibilityGate')
                             if f in detailed[k]}) if k in detailed else v for k, v in free.items()}
            except HTTPException:
                warnings.append('Free tier summary unavailable')
    elif filters.free_only:
        raise HTTPException(status_code=409, detail='Free discovery requires HTTPS')
    if filters.free_only:
        warnings.append('Cataloged free offers only; account eligibility and zero cost are not guaranteed. Unverified combos excluded.')
    models = _filtered_rows(rows, filters, free, rankings)
    return {'models': models, 'count': len(models), 'warnings': warnings, 'free_summary': summary}
