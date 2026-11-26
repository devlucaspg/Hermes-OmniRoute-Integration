"""Native Hermes model-provider profile for a self-hosted OmniRoute API.

A second Hermes plugin kind is needed for reliable profile-scoped lazy loading.
The actual inference transport and tool calling remain Hermes-owned.
"""
from __future__ import annotations

import ipaddress
import json
import http.client
import logging
import time
from urllib import request, error, parse
from providers import register_provider
from providers.base import ProviderProfile


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _valid_base(root):
    root = (root or "").strip().rstrip("/")
    try:
        u = parse.urlsplit(root)
    except ValueError:
        return ''
    if (u.scheme not in ("http", "https") or not u.hostname or u.username is not None
            or u.password is not None or u.query or u.fragment or any(c in root for c in '\r\n\t') or not u.path.rstrip("/").endswith(("/v1","/api/v1"))):
        return ""
    try:
        _ = u.port
    except ValueError:
        return ""
    if u.scheme == "http":
        hostname = u.hostname.lower().rstrip(".")
        try:
            address = ipaddress.ip_address(hostname)
            local = address.is_private or address.is_loopback or address.is_link_local
        except ValueError:
            local = hostname in {"localhost", "host.docker.internal"} or hostname.endswith((".home.arpa", ".local", ".internal"))
        if not local: return ""
    return root


def _env(name):
    from agent.secret_scope import get_secret_str
    value = get_secret_str(name)
    return str(value or '').strip()


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


class OmniRouteProfile(ProviderProfile):
    def build_client_kwargs_extras(self, **context):
        """Supply the profile's self-hosted endpoint unless Hermes has an explicit override.

        Hermes's normal transport owns streaming and tool calls; this hook only
        sets a default and never reads credentials from a different profile.
        """
        root = _valid_base(_env('OMNIROUTE_BASE_URL'))
        return {'base_url': root} if root else {}

    def fetch_models(self, *, api_key=None, base_url=None, timeout=20.0):
        """Live catalog using the same scoped credentials for every page."""
        scoped_root = _valid_base(_env('OMNIROUTE_BASE_URL'))
        root = _valid_base(base_url) if base_url is not None else scoped_root
        if not root:
            return None
        # Explicit empty credentials are a deliberate keyless probe from Hermes.
        # Never substitute the scoped key on an explicitly different endpoint.
        key = api_key if api_key is not None else (_env('OMNIROUTE_API_KEY') if root == scoped_root else '')
        if not key:
            return None
        try:
            http = request.build_opener(request.ProxyHandler({}), _NoRedirect())
            rows = _fetch_catalog(root, key, http, timeout)
            return list(dict.fromkeys(row['id'] for row in rows if _is_chat(row)))
        except CatalogError as exc:
            logging.getLogger(__name__).warning('%s', exc)
            return None


omniroute = OmniRouteProfile(
    name='omniroute',
    aliases=('omni-route',),
    display_name='OmniRoute (self-hosted)',
    description='Route chat and tool calls through your own OmniRoute deployment',
    auth_type='api_key',
    api_mode='chat_completions',
    # Base URL is kept empty at discovery: each Hermes profile supplies its own endpoint.
    base_url='',
    env_vars=('OMNIROUTE_API_KEY',),
    fallback_models=(),
    supports_model_listing=True,
    supports_health_check=True,
    # OmniRoute accepts multimodal Chat Completions; the selected upstream model
    # must independently support image inputs.
    supports_vision=True,
)
# Official Hermes v0.23.2 hook bypasses the generic non-empty base_url gate.
# Resolve the endpoint and secret at call time, never at plugin import.
omniroute.base_url_env_var = 'OMNIROUTE_BASE_URL'
omniroute.picker_catalog = lambda force_refresh: omniroute.fetch_models()
register_provider(omniroute)
