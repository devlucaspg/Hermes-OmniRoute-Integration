"""Search and URL extraction through the explicitly configured OmniRoute router."""
from __future__ import annotations
from typing import Any
from agent.web_search_provider import WebSearchProvider
from ..core import OmniError, call_json, configured, setting


class OmniWeb(WebSearchProvider):
    @property
    def name(self): return 'omniroute'
    @property
    def display_name(self): return 'OmniRoute Search & Extract'
    def is_available(self): return configured()
    def supports_search(self): return True
    def supports_extract(self): return True

    def search(self, query: str, limit: int = 5) -> dict:
        if not (query or '').strip(): return {'success': False, 'error': 'Search query is required'}
        try: count = max(1, min(20, int(limit)))
        except (TypeError, ValueError): return {'success': False, 'error': 'Invalid search result limit'}
        body: dict[str, Any] = {'query': query, 'max_results': count}
        provider = setting('OMNIROUTE_SEARCH_PROVIDER')
        if provider: body['provider'] = provider
        try:
            response = call_json('POST', '/search', payload=body, timeout=60)
            results = response.get('results', [])
            if not isinstance(results, list): results = []
            web = []
            for idx, item in enumerate(results[:20], 1):
                if not isinstance(item, dict): continue
                web.append({'title': str(item.get('title') or ''), 'url': str(item.get('url') or ''),
                            'description': str(item.get('snippet') or item.get('content') or '')[:500],
                            'position': item.get('position') if isinstance(item.get('position'), int) else idx})
            return {'success': True, 'data': {'web': web}}
        except (OmniError, ValueError) as exc:
            return {'success': False, 'error': str(exc)}

    def extract(self, urls: list[str], **kwargs: Any) -> list[dict]:
        if isinstance(urls, str): urls = [urls]
        result = []
        for url in (urls or [])[:20]:
            if not isinstance(url, str) or not url.strip(): continue
            try:
                body: dict[str, str] = {'url': url.strip()}
                provider = setting('OMNIROUTE_FETCH_PROVIDER')
                if provider: body['provider'] = provider
                response = call_json('POST', '/web/fetch', payload=body, timeout=60)
                metadata = response.get('metadata') if isinstance(response.get('metadata'), dict) else {}
                metadata = dict(metadata)
                for key in ('provider', 'links', 'screenshot_url'):
                    if response.get(key): metadata[key] = response[key]
                content = str(response.get('content') or '')
                maximum = kwargs.get('max_chars')
                if isinstance(maximum, int) and maximum > 0: content = content[:maximum]
                result.append({'url': str(response.get('url') or url), 'title': str(metadata.get('title') or ''),
                               'content': content, 'raw_content': content, 'metadata': metadata})
            except (OmniError, ValueError) as exc:
                result.append({'url': url, 'title': '', 'content': '', 'raw_content': '', 'error': str(exc)})
        return result
