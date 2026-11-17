"""Native Hermes model-provider profile for a self-hosted OmniRoute API.

A second Hermes plugin kind is needed for reliable profile-scoped lazy loading.
The actual inference transport and tool calling remain Hermes-owned.
"""
from __future__ import annotations

import ipaddress
import json
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
            or u.password is not None or u.query or u.fragment or not u.path.rstrip("/").endswith(("/v1","/api/v1"))):
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


class OmniRouteProfile(ProviderProfile):
    def build_client_kwargs_extras(self, **context):
        """Supply the profile's self-hosted endpoint unless Hermes has an explicit override.

        Hermes's normal transport owns streaming and tool calls; this hook only
        sets a default and never reads credentials from a different profile.
        """
        root = _valid_base(_env('OMNIROUTE_BASE_URL'))
        return {'base_url': root} if root else {}

    def fetch_models(self, *, api_key=None, base_url=None, timeout=8.0):
        """Live list. No static/fictitious fallbacks and no redirects."""
        root = _valid_base(base_url or self.base_url or _env('OMNIROUTE_BASE_URL'))
        if not root: return None
        key = api_key or _env('OMNIROUTE_API_KEY')
        if not key: return None
        try:
            http = request.build_opener(request.ProxyHandler({}), _NoRedirect())
            req = request.Request(root + '/models?kind=chat&prefix=alias', headers={
                'Authorization': 'Bearer ' + key,
                'Accept': 'application/json',
                'User-Agent': 'hermes-omniroute-community/0.3.2-beta.1',
            })
            with http.open(req, timeout=timeout) as r:
                raw = r.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024: return None
            data = json.loads(raw)
            rows = data.get('data', []) if isinstance(data, dict) else []
            if not isinstance(rows, list): return None
            # Only LLM/chat entries belong in the Hermes model picker.
            # Keep untyped OpenAI-compatible rows, but exclude typed audio,
            # embeddings, images, video and other specialty models.
            return list(dict.fromkeys(
                m['id'] for m in rows
                if isinstance(m, dict) and isinstance(m.get('id'), str) and
                m['id'].strip() and not m.get('subtype') and
                str(m.get('type') or 'chat').lower() in {'chat', 'text', 'language', 'llm', 'combo'}
            ))
        except (error.URLError, TimeoutError, ValueError, OSError):
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
register_provider(omniroute)
