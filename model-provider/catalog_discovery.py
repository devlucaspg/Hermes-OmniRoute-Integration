"""Canonical OmniRoute catalog transport, classification and diagnostics.

Edit only this source. scripts/sync_catalog.py distributes an identical copy
to the standalone model-provider package. Standard library only.
"""
from __future__ import annotations

import http.client
import json
import logging
import time
from urllib import request, error, parse


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


def _fetch_pages(root, key, opener, timeout, path, stats, query_params=None):
    """Retrieve every authorized page, never report a partial catalog as success."""
    if not key or any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise CatalogError('Invalid OmniRoute API key')
    if path not in {'/models', '/images/generations', '/videos/generations'}:
        raise CatalogError('Invalid catalog endpoint')
    query_params = dict(query_params or {})
    allowed = {'prefix', 'configuredOnly', 'kind', 'capability', 'min_context', 'q'}
    if not set(query_params) <= allowed or (query_params and path != '/models'):
        raise CatalogError('Invalid catalog filter parameters')
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
            query = list({'prefix': 'alias', **query_params}.items()) + [('limit', str(page_size))]
            if cursor is not None:
                query.append(('after', cursor))
            url = root + path
            if path == '/models':
                url += '?' + parse.urlencode(query)
            stats['requests'] += 1
            try:
                req = request.Request(url, headers={
                    'Authorization': 'Bearer ' + key, 'Accept': 'application/json',
                    'User-Agent': 'hermes-omniroute-community/0.4.0-beta.5',
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
        stats['pages'] += 1
        stats['received'] += len(page)
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


def new_diagnostics(source='api'):
    """No keys, endpoint URLs, cursor values, raw IDs or upstream bodies."""
    return {'source': source, 'status': 'ok', 'pages': 0, 'requests': 0,
            'received': 0, 'duration_ms': 0, 'error': None}


def _fetch_catalog(root, key, opener, timeout=20.0, path='/models', *, diagnostics=None, query_params=None):
    stats = diagnostics if diagnostics is not None else {}
    stats.update(new_diagnostics())
    started = time.monotonic()
    try:
        return _fetch_pages(root, key, opener, timeout, path, stats, query_params)
    except CatalogError as exc:
        # All CatalogError messages originate from our fixed templates.
        stats.update(status='error', error=str(exc))
        raise
    finally:
        stats['duration_ms'] = round((time.monotonic() - started) * 1000, 2)


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

def _matches_kind(row, kind, path='/models'):
    if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'].strip():
        return False
    if kind == 'chat':
        return _is_chat(row)
    if kind == 'image' and path == '/images/generations':
        vals = row.get('input_modalities')
        return not isinstance(vals, list) or not vals or 'text' in vals
    if kind == 'video' and path == '/videos/generations':
        return str(row.get('type') or 'video').strip().lower() == 'video'
    return _is_modality(row, kind)


def _is_combo(row):
    return (str(row.get('owned_by') or '').strip().lower() == 'combo'
            or str(row.get('type') or '').strip().lower() == 'combo')


def select_rows(rows, kind, path='/models'):
    """Preserve the first occurrence and original routing ID."""
    selected = {}
    for row in rows:
        if _matches_kind(row, kind, path):
            selected.setdefault(row['id'], row)
    return list(selected.values())


def catalog_diagnostics(rows, kind, path='/models', *, stats=None, delivered=None):
    """Counts describe the endpoint queried, not a second global API request.

    Modality counts are raw matching rows and may overlap. Combos are a subset
    of chat (or a separately tagged combo). Duplicate counts are for the chosen
    modality. 'delivered' is the actual count at the caller's output boundary.
    """
    result = dict(new_diagnostics(), **(stats or {}))
    if result['status'] == 'ok':
        result['received'] = len(rows)
    kinds = ('chat', 'image', 'video', 'tts', 'stt')
    # Specialty endpoints are authoritative for their own modality; never
    # count an untyped specialty row as a legacy chat entry.
    scope = (('image',) if path == '/images/generations' else
             ('video',) if path == '/videos/generations' else kinds)
    counts = dict.fromkeys(kinds, 0)
    others = 0
    combos = 0
    for row in rows:
        matched = [name for name in scope if _matches_kind(row, name, path)]
        for name in matched:
            counts[name] += 1
        if not matched:
            others += 1
        if isinstance(row, dict) and _is_combo(row):
            combos += 1
    selected = select_rows(rows, kind, path)
    result.update(kind=kind, classified=counts, combos=combos, other=others,
                  duplicates_removed=max(0, counts.get(kind, 0) - len(selected)),
                  delivered=len(selected) if delivered is None else delivered)
    return result


def log_diagnostics(logger, diagnostics):
    """Structured, sanitized telemetry, including failed discovery attempts."""
    level = logging.WARNING if diagnostics['status'] == 'error' else logging.INFO
    logger.log(level, 'OmniRoute catalog: %s', json.dumps(diagnostics, sort_keys=True))


# Profile-local applied catalog. No credentials are persisted.
def _picker_path(home):
    from pathlib import Path
    return Path(home) / 'plugin-data' / 'omniroute-media' / 'picker-selection.json'


def _valid_picker_ids(ids):
    return (isinstance(ids, list) and all(isinstance(x, str) and 0 < len(x) <= 256
            and not any(ord(c) < 32 or ord(c) == 127 for c in x) for x in ids))


def read_picker_selection(home, base):
    """None means no selection for this endpoint; an empty list is authoritative."""
    path = _picker_path(home)
    try:
        with path.open('rb') as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise CatalogError('Saved picker selection exceeds size limit')
        data = json.loads(raw)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError):
        raise CatalogError('Saved picker selection cannot be read') from None
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise CatalogError('Invalid saved picker selection')
    if data.get('base_url') != base:
        return None
    if not _valid_picker_ids(data.get('ids')) or not isinstance(data.get('filters'), dict):
        raise CatalogError('Invalid saved picker selection')
    return data


def write_picker_selection(home, base, filters, ids):
    import os
    import tempfile
    if not _valid_picker_ids(ids):
        raise CatalogError('Invalid picker model IDs')
    path = _picker_path(home)
    payload = json.dumps({'schema': 1, 'base_url': base, 'filters': filters,
                          'ids': list(dict.fromkeys(ids))}, ensure_ascii=True).encode()
    if len(payload) > 16 * 1024 * 1024:
        raise CatalogError('Saved picker selection exceeds size limit')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.picker-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def clear_picker_selection(home):
    _picker_path(home).unlink(missing_ok=True)
