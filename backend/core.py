"""Shared OmniRoute HTTP/credentials/catalog implementation (standard library only).

No network on import or availability checks. No retries on non-idempotent requests.
No redirects: prevents accidentally forwarding an API key off the chosen origin.
"""
from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from urllib import error, parse, request

VERSION = '0.3.2-beta.1'


class OmniError(RuntimeError):
    pass


def setting(name: str, default: str = '') -> str:
    """Use Hermes' profile-aware secrets lookup; never bypass a scoped miss."""
    from agent.secret_scope import get_secret_str
    value = get_secret_str(name, default)
    return str(value or default).strip()


def validated_base(url: str) -> str:
    """Validate an operator-selected API root. Plain HTTP is local-network only.

    Domain names are not resolved here: the operator may use LAN split DNS,
    but unknown/public domains must use TLS. This is not a DNS rebinding defence;
    the API endpoint itself is a trusted operator configuration.
    """
    url = (url or '').strip().rstrip('/')
    try:
        parts = parse.urlsplit(url)
    except ValueError as exc:
        raise OmniError('Invalid OmniRoute URL') from exc
    if (parts.scheme not in {'http', 'https'} or not parts.hostname or
            parts.username is not None or parts.password is not None or
            parts.query or parts.fragment or not parts.path or
            not parts.path.rstrip('/').endswith(('/v1', '/api/v1')) or
            any(c in url for c in '\r\n\t')):
        raise OmniError('OMNIROUTE_BASE_URL must be a valid API root ending in /v1 or /api/v1')
    try:
        _ = parts.port
    except ValueError as exc:
        raise OmniError('Invalid OmniRoute URL port') from exc
    if parts.scheme == 'http':
        host = parts.hostname.lower().rstrip('.')
        try:
            address = ipaddress.ip_address(host)
            allowed = address.is_private or address.is_loopback or address.is_link_local
        except ValueError:
            allowed = host in {'localhost', 'host.docker.internal'} or host.endswith(('.home.arpa','.local','.internal'))
        if not allowed:
            raise OmniError('Plain HTTP is restricted to local endpoints; use HTTPS for public hosts')
    return url


def api_base() -> str:
    url = setting('OMNIROUTE_BASE_URL')
    if not url:
        raise OmniError('Set OMNIROUTE_BASE_URL to your OmniRoute API root (/v1 or /api/v1)')
    return validated_base(url)


def api_key() -> str:
    key = setting('OMNIROUTE_API_KEY')
    if not key:
        raise OmniError('Set OMNIROUTE_API_KEY for the configured OmniRoute instance')
    if any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise OmniError('API key contains a control character')
    return key


def configured() -> bool:
    try:
        api_base()
        api_key()
        return True
    except (OmniError, ValueError):
        return False


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = request.build_opener(request.ProxyHandler({}), _NoRedirect())


def call(method: str, path: str, *, payload: object = None,
         data: bytes | None = None, content_type: str | None = None,
         timeout: float = 45.0, limit: int = 64 * 1024 * 1024) -> tuple[bytes, str]:
    # 3.8.53 supports server-side model discovery filters. Only the exact
    # audited query is allowed; no caller-provided URL/query is interpolated.
    if ((not path.startswith('/') or '://' in path or '#' in path or
         any(c in path for c in '\r\n\t')) or
            ('?' in path and path != '/models?kind=chat&prefix=alias')):
        raise OmniError('Invalid OmniRoute API path')
    url = api_base() + path
    headers = {
        'Authorization': 'Bearer ' + api_key(),
        'Accept': 'application/json, application/octet-stream, */*',
        'User-Agent': 'hermes-omniroute-community/' + VERSION,
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        content_type = 'application/json'
    if content_type:
        headers['Content-Type'] = content_type
    req = request.Request(url, headers=headers, data=data, method=method.upper())
    try:
        with _OPENER.open(req, timeout=timeout) as response:
            body = response.read(limit + 1)
            if len(body) > limit:
                raise OmniError('OmniRoute response exceeds safety size limit')
            return body, response.headers.get('Content-Type', '')
    except error.HTTPError as exc:
        # OmniRoute 3.8.53 uses typed error codes for key-scope rejection,
        # model/endpoint incompatibility and quotas. Expose only well-formed
        # short code/type tokens, NEVER the upstream message/request body.
        suffix = ''
        try:
            raw = exc.read(8192)
            envelope = json.loads(raw)
            problem = envelope.get('error') if isinstance(envelope, dict) else None
            if isinstance(problem, dict):
                code = problem.get('code') or problem.get('type')
                if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', code):
                    suffix = f' ({code})'
        except (ValueError, TypeError, OSError, AttributeError):
            pass
        raise OmniError(f'OmniRoute HTTP {exc.code}{suffix} at {path}') from None
    except (error.URLError, OSError, TimeoutError) as exc:
        raise OmniError(f'OmniRoute connection failure at {path} ({type(exc).__name__})') from None


def call_json(method: str, path: str, *, payload: object = None, timeout: float = 45.0) -> dict:
    body, _ = call(method, path, payload=payload, timeout=timeout)
    try:
        value = json.loads(body.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise OmniError('OmniRoute returned invalid JSON') from exc
    if not isinstance(value, dict):
        raise OmniError('OmniRoute returned an unexpected JSON envelope')
    if value.get('error'):
        raise OmniError('OmniRoute API reported an error')
    return value


def data_items(response: dict) -> list[dict]:
    value = response.get('data')
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


class Catalog:
    def __init__(self):
        self._cached: dict[str, tuple[float, list[dict], tuple[str, str]]] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> list[dict]:
        # Credentials in cache key aren't exposed; only a fingerprint to avoid cross-key reuse.
        import hashlib
        try:
            identity = (api_base(), hashlib.sha256(api_key().encode()).hexdigest())
        except OmniError:
            return []
        with self._lock:
            hit = self._cached.get(path)
            if hit and hit[0] > time.monotonic() and hit[2] == identity:
                return [dict(x) for x in hit[1]]
        try:
            rows = data_items(call_json('GET', path, timeout=10.0))
        except OmniError:
            rows = []
            ttl = 15
        else:
            ttl = 300
        with self._lock:
            self._cached[path] = (time.monotonic() + ttl, rows, identity)
        return [dict(x) for x in rows]


catalog = Catalog()


def model_id(explicit: str | None, env_name: str, category: str) -> str:
    value = (explicit or '').strip() or setting(env_name)
    if not value:
        raise OmniError(f'Choose a {category} model using {env_name} (or the Hermes model picker)')
    return value


def is_chat_model(row: dict) -> bool:
    """Honor OmniRoute's `type` taxonomy, including combos with missing type.

    A missing type is treated as chat for backward compatibility with OpenAI
    catalogs; explicit embedding/media/rerank models must never enter the LLM
    selector. Audio `subtype` is also checked for malformed third-party rows.
    """
    if not isinstance(row.get('id'), str) or not row['id'].strip():
        return False
    category = str(row.get('type') or 'chat').strip().lower()
    return category in {'chat', 'text', 'language', 'llm', 'combo'} and not row.get('subtype')


def _is_modality(row: dict, kind: str) -> bool:
    """Map 3.8.53 model types: audio + subtype speech/transcription."""
    category = str(row.get('type') or '').strip().lower()
    subtype = str(row.get('subtype') or '').strip().lower()
    if kind in {'tts', 'stt'} and category == 'audio':
        if subtype:
            return subtype in ({'speech', 'tts'} if kind == 'tts' else {'transcription', 'stt'})
        # A generic audio entry without subtype is not enough to infer TTS/STT.
    fields = {str(row.get(k) or '').strip().lower() for k in ('type', 'modality', 'category')}
    endpoint_names = {
        'image': ('image', 'images'), 'video': ('video', 'videos'),
        'tts': ('speech', 'tts', 'audio-speech'),
        'stt': ('transcription', 'stt', 'audio-transcriptions'),
    }
    for key in ('supportedEndpoints', 'supported_endpoints', 'endpoints'):
        values = row.get(key)
        if isinstance(values, (tuple, list, set)):
            fields.update(str(v).strip().lower() for v in values if isinstance(v, str))
    return any(alias in fields for alias in endpoint_names.get(kind, (kind,)))


def model_entries(kind: str) -> list[dict]:
    if kind in {'image', 'video'}:
        endpoint = '/images/generations' if kind == 'image' else '/videos/generations'
        rows = catalog.get(endpoint)
        if rows:
            if kind == 'image':
                # Keep text-capable image models in the generation picker.
                return [x for x in rows if isinstance(x.get('id'), str) and (
                    not isinstance(x.get('input_modalities'), list) or
                    not x['input_modalities'] or 'text' in x['input_modalities'])]
            return [x for x in rows if isinstance(x.get('id'), str)]
    if kind == 'chat':
        # Filter at OmniRoute BEFORE paging/aliases, then defensively filter
        # again in case a compatible gateway ignores unknown query params.
        return [x for x in catalog.get('/models?kind=chat&prefix=alias') if is_chat_model(x)]
    return [x for x in catalog.get('/models') if isinstance(x.get('id'), str) and
            _is_modality(x, kind)]


def picker_models(kind: str, env: str) -> list[dict]:
    rows = model_entries(kind)
    found = [{'id': row['id'], 'display': str(row.get('name') or row['id'])} for row in rows]
    preferred = setting(env)
    if preferred and preferred not in {x['id'] for x in found}:
        found.insert(0, {'id': preferred, 'display': preferred + ' (configured)'})
    return found


def setup_schema() -> dict:
    return {'name': 'OmniRoute', 'tag': 'OpenAI-compatible self-hosted gateway', 'env_vars': [
        {'key': 'OMNIROUTE_BASE_URL', 'prompt': 'Your OmniRoute API base URL'},
        {'key': 'OMNIROUTE_API_KEY', 'prompt': 'Your OmniRoute inference API key', 'secret': True},
    ]}
