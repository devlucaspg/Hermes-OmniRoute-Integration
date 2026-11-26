"""Native Hermes model-provider profile for a self-hosted OmniRoute API.

A second Hermes plugin kind is needed for reliable profile-scoped lazy loading.
The actual inference transport and tool calling remain Hermes-owned.
"""
from __future__ import annotations

import ipaddress
import logging
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


# The Hermes loader may import this entrypoint without a package context.
# Load the sibling catalog module by absolute file path; do not change sys.path.
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

_catalog_spec = spec_from_file_location(__name__ + '_catalog_discovery',
                                        Path(__file__).resolve().parent / 'catalog_discovery.py')
_catalog_module = module_from_spec(_catalog_spec)
_catalog_spec.loader.exec_module(_catalog_module)
CatalogError = _catalog_module.CatalogError
_fetch_catalog = _catalog_module._fetch_catalog
_is_chat = _catalog_module._is_chat
select_rows = _catalog_module.select_rows
catalog_diagnostics = _catalog_module.catalog_diagnostics
new_diagnostics = _catalog_module.new_diagnostics
log_diagnostics = _catalog_module.log_diagnostics

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
        # The provider hook and configured-relay path both call fetch_models.
        try:
            from hermes_constants import get_hermes_home
            saved = _catalog_module.read_picker_selection(get_hermes_home(), root)
            if saved is not None:
                return saved['ids']
        except ImportError:
            pass
        except CatalogError as exc:
            logging.getLogger(__name__).warning('OmniRoute picker: %s', exc)
            return []
        stats = new_diagnostics()
        try:
            http = request.build_opener(request.ProxyHandler({}), _NoRedirect())
            rows = _fetch_catalog(root, key, http, timeout, diagnostics=stats)
            ids = [row['id'] for row in select_rows(rows, 'chat')]
            log_diagnostics(logging.getLogger(__name__), catalog_diagnostics(rows, 'chat', stats=stats, delivered=len(ids)))
            return ids
        except CatalogError as exc:
            stats.update(status='error', error=str(exc))
            log_diagnostics(logging.getLogger(__name__), catalog_diagnostics([], 'chat', stats=stats))
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
