"""Hermes Dashboard extension: no secrets ever returned to the browser.

Uses the host's profile-scoped env persistence API. All handlers are sync to
keep blocking network access out of the gateway asyncio event loop.
"""
from __future__ import annotations

import json
import logging
import http.client
from urllib import request, error, parse
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from agent.secret_scope import get_secret_str
from hermes_cli.config import get_env_value, save_env_value, save_env_value_secure, load_config, set_config_value

# The dashboard may live outside the backend Python import package. Keep
# endpoint validation self-contained but identical to backend/core.py.
import ipaddress

router = APIRouter()

PLUGIN_VERSION = '0.4.0-beta.6'

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
    clear_read_token: bool = False


class ModelSelection(BaseModel):
    kind: str
    model: str = Field(min_length=1, max_length=256)


@router.get('/status')
def status():
    selection = _saved_picker_status()
    return {
        'plugin_version': PLUGIN_VERSION,
        **selection,
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
    if not body.base_url and not body.api_key and not body.read_token and not body.clear_read_token:
        raise HTTPException(status_code=422, detail='Supply a base URL or a new API key')
    # Validate the entire request BEFORE writing any configuration keys.
    checked = _valid_url(body.base_url) if body.base_url else None
    if body.api_key and any(ord(c) < 32 or ord(c) == 127 for c in body.api_key):
        raise HTTPException(status_code=422, detail='API key cannot contain control characters')
    if body.read_token and any(ord(c) < 32 or ord(c) == 127 for c in body.read_token):
        raise HTTPException(status_code=422, detail='Read token cannot contain control characters')
    if body.read_token and body.clear_read_token:
        raise HTTPException(status_code=422, detail='Replace or clear the read token, not both')
    if checked and checked != _value('OMNIROUTE_BASE_URL').rstrip('/') and _secret('OMNIROUTE_READ_TOKEN') and not (body.read_token or body.clear_read_token):
        raise HTTPException(status_code=422, detail='Replace or clear the read token when changing the endpoint')
    if body.read_token and not (checked or _value('OMNIROUTE_BASE_URL')).startswith('https://'):
        raise HTTPException(status_code=422, detail='Management token requires HTTPS')
    if (checked and checked != _value('OMNIROUTE_BASE_URL').rstrip('/')) or body.api_key:
        _clear_applied_picker()
    if checked:
        save_env_value('OMNIROUTE_BASE_URL', checked)
        if _native_model_is_omniroute():
            set_config_value('model.base_url', checked)
    if body.api_key:
        save_env_value_secure('OMNIROUTE_API_KEY', body.api_key)
    if body.read_token or body.clear_read_token:
        save_env_value_secure('OMNIROUTE_READ_TOKEN', body.read_token)
    result = status()
    if body.read_token or body.clear_read_token:
        result['read_token_configured'] = bool(body.read_token)
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
    apply_to_picker: bool = False


def _picker_home():
    from hermes_constants import get_hermes_home
    return get_hermes_home()


def _saved_picker_status():
    try:
        saved = _catalog_module.read_picker_selection(_picker_home(), _value('OMNIROUTE_BASE_URL').rstrip('/'))
    except (ImportError, CatalogError):
        saved = None
    return {'picker_filters': saved['filters'] if saved is not None else None,
            'picker_count': len(saved['ids']) if saved is not None else None}


def _invalidate_picker():
    from hermes_cli.models import clear_provider_models_cache
    clear_provider_models_cache('omniroute')


def _clear_applied_picker():
    try:
        _catalog_module.clear_picker_selection(_picker_home())
        _invalidate_picker()
    except ImportError:
        pass


def _apply_picker(filters, models, base):
    ids = [m['id'] for m in models if m['kind'] == 'chat']
    settings = filters.model_dump(exclude={'apply_to_picker'})
    try:
        _catalog_module.write_picker_selection(_picker_home(), base, settings, ids)
        _invalidate_picker()
    except (OSError, CatalogError, ImportError):
        raise HTTPException(status_code=500, detail='Could not apply the conversation catalog') from None
    return {'picker_count': len(ids), 'picker_filters': settings}


def _discovery_query(filters: DiscoveryFilters) -> str:
    if (not set(filters.kinds) <= set(DISCOVERY_KINDS) or
            not set(filters.capabilities) <= set(DISCOVERY_CAPS) or
            filters.match not in {'and', 'or'}):
        raise HTTPException(status_code=422, detail='Invalid discovery filter')
    params = {'prefix': 'canonical'}
    if filters.configured_only:
        params['configuredOnly'] = 'true'
    # Keep typed combos and legacy chat aliases visible as in the stable picker.
    if len(set(filters.kinds)) == 1 and filters.kinds[0] != 'chat':
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
    except (error.URLError, ValueError, OSError, http.client.HTTPException):
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
        if row.get('enabled') is False:
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
        is_combo = _catalog_module._is_combo(row)
        owner = owner if isinstance(owner, str) else ('combo' if is_combo else '')
        raw_kind = row.get('type')
        if _is_chat(row):
            kind = 'chat'
        elif _catalog_module._is_modality(row, 'tts') or _catalog_module._is_modality(row, 'stt'):
            kind = 'audio'
        elif isinstance(raw_kind, str) and raw_kind in DISCOVERY_KINDS and raw_kind != 'chat':
            kind = raw_kind
        else:
            continue
        if kind not in kinds:
            continue
        if not filters.include_combos and is_combo:
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
        budget = free.get((owner, root)) if isinstance(root, str) and not is_combo else None
        if filters.free_only and not budget:
            continue
        rank = rankings.get(owner, {})
        if any(ord(c) < 32 or ord(c) == 127 for c in identifier):
            continue
        result.setdefault(identifier, {'id': identifier, 'label': str(row.get('display_name') or row.get('name') or identifier)[:256],
                              'kind': kind, 'provider': owner, 'context_length': context,
                              'capabilities': [cap for cap in DISCOVERY_CAPS if flags.get(cap) is True],
                              'free_type': budget.get('freeType') if budget else None,
                              'free_metadata': {f: budget.get(f) for f in ('monthlyTokens', 'creditTokens', 'poolKey', 'tos', 'hardStopGuaranteed', 'trainsOnPrompts', 'eligibilityGate')} if budget else None,
                              'provider_state': rank.get('state'), 'provider_usage': rank.get('usage'),
                              'route_label': identifier if '/' in identifier or not owner else owner + '/' + identifier})
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
    params = dict(parse.parse_qsl(parse.urlsplit(path).query))
    stats = new_diagnostics()
    try:
        opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
        rows = _fetch_catalog(base, key, opener, diagnostics=stats, query_params=params)
    except CatalogError as exc:
        log_diagnostics(logging.getLogger(__name__), stats)
        raise HTTPException(status_code=502, detail=str(exc)) from None
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
        if token or filters.free_only:
            try:
                items = _discovery_get(root + '/free-provider-rankings?configuredOnly=true&availableOnly=true&withUsage=true&sortBy=reliability&limit=100', management).get('rankings')
                if not isinstance(items, list):
                    raise ValueError('Invalid rankings')
                for r in items:
                    if not isinstance(r, dict) or not isinstance(r.get('id'), str):
                        continue
                    rel = r.get('reliability')
                    if not isinstance(rel, dict):
                        continue
                    usage = rel.get('usage')
                    rankings[r['id']] = {'state': rel.get('state'),
                        'usage': {k: usage.get(k) for k in ('requests', 'successes', 'successRate', 'avgLatencyMs', 'windowHours')}
                        if isinstance(usage, dict) else None}
            except (HTTPException, ValueError):
                warnings.append('Provider rankings unavailable')
            try:
                data = _discovery_get(root + '/free-tier/summary', management)
                summary = {k: data.get(k) for k in ('modelCount', 'poolCount', 'steadyRecurringTokens',
                                                     'firstMonthRealisticTokens', 'catalogUpdatedAt', 'catalogSource')}
                # Summary is a global catalog estimate, never an account balance.
                budgets = data.get('perModel')
                if not isinstance(budgets, list):
                    raise HTTPException(status_code=502, detail='Invalid free tier summary')
                if free:
                    detailed = _free_index(budgets)
                    # Only enrich existing exact matches, never promote an
                    # unknown row based on global or provider-level totals.
                    # The active overlay can retire baseline entries. Do not revive
                    # an offer missing/disabled in the effective summary.
                    free = {k: dict(v, **{f: detailed[k][f] for f in
                             ('freeType', 'monthlyTokens', 'creditTokens', 'poolKey', 'tos',
                              'hardStopGuaranteed', 'trainsOnPrompts', 'eligibilityGate')
                             if f in detailed[k]}) if k in detailed else v for k, v in free.items()
                            if k in detailed}
            except HTTPException:
                warnings.append('Free tier summary unavailable')
    elif filters.free_only:
        raise HTTPException(status_code=409, detail='Free discovery requires HTTPS')
    if filters.free_only:
        if summary is None:
            warnings.append('Free-tier summary could not be verified; results reflect the baseline catalog only.')
        warnings.append('Cataloged free offers only; account eligibility and zero cost are not guaranteed. Unverified combos excluded.')
    models = _filtered_rows(rows, filters, free, rankings)
    # Only publish a completed successful discovery, including empty results.
    selection = _apply_picker(filters, models, base) if filters.apply_to_picker else {}
    stats['delivered'] = len(models)
    log_diagnostics(logging.getLogger(__name__), stats)
    return {'models': models, 'count': len(models), 'warnings': warnings, 'free_summary': summary,
            'diagnostics': stats, **selection}
