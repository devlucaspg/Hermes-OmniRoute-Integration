"""Shared OmniRoute HTTP/credentials/catalog implementation (standard library only).

No network on import or availability checks. No retries on non-idempotent requests.
No redirects: prevents accidentally forwarding an API key off the chosen origin.
"""
from __future__ import annotations

import ipaddress
import json
import http.client
import logging
import re
import threading
import time
from urllib import error, parse, request

VERSION = '0.4.0-beta.2'


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


class Catalog:
    def __init__(self):
        self._cached: dict[str, tuple[float, list[dict], tuple[str, str]]] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> list[dict]:
        # Credentials in cache key aren't exposed; only a fingerprint to avoid cross-key reuse.
        import hashlib
        try:
            root, key = api_base(), api_key()
            identity = (root, hashlib.sha256(key.encode()).hexdigest())
        except OmniError:
            return []
        with self._lock:
            hit = self._cached.get(path)
            if hit and hit[0] > time.monotonic() and hit[2] == identity:
                return [dict(x) for x in hit[1]]
        try:
            rows = _fetch_catalog(root, key, _OPENER, path=path)
        except CatalogError as exc:
            logging.getLogger(__name__).warning('%s', exc)
            # Never cache a failed or partial discovery as an empty success.
            return []
        ttl = 60
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
    return _is_chat(row)


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
        return [x for x in catalog.get('/models') if is_chat_model(x)]
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
