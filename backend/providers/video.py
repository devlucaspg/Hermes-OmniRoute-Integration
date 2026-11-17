"""OmniRoute 3.8.53 video API adapter, without a global ten-second restriction.

Hermes advertises capabilities at *provider* scope. OmniRoute is a router with
heterogeneous models: use the configured model's live metadata when available,
and defer undocumented limits to the OmniRoute API.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit
from typing import Any

from agent.video_gen_provider import VideoGenProvider, error_response, save_b64_video, success_response
from ..core import OmniError, call_json, configured, model_entries, model_id, picker_models, setting, setup_schema

_DEFAULT_CAPABILITIES = {
    'modalities': ['text'],
    'min_duration': 1,
    # Unknown sizes/durations are deliberately UNCONSTRAINED in Hermes's
    # dynamic schema; OmniRoute itself validates the selected upstream.
    'supports_audio': False,
    'supports_negative_prompt': False,
    'supports_seed': False,
    'max_reference_images': 0,
}


def _validated_reference_url(url: str) -> str:
    """A model-supplied i2v reference must be a public HTTPS URL.

    Hermes video_generate explicitly documents public HTTPS image URLs. Forbid
    non-web/file, embedded credentials, and direct private/loopback targets;
    OmniRoute applies its own outbound URL policy as a second boundary.
    """
    from ipaddress import ip_address
    if not isinstance(url, str) or not url or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise OmniError('Video reference must be a public HTTPS image URL')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.port == 0):
            raise ValueError()
        try:
            address = ip_address(parsed.hostname)
            if not address.is_global:
                raise ValueError()
        except ValueError:
            # Parseable IP addresses that are not global have already been
            # rejected; DNS resolution and redirect safety remain with OmniRoute.
            if parsed.hostname.replace('.', '').isdigit() or ':' in parsed.hostname:
                raise OmniError('Video reference cannot target a private network IP') from None
        if parsed.hostname.lower() in {'localhost', 'host.docker.internal'} or parsed.hostname.endswith(('.local', '.internal', '.home.arpa')):
            raise ValueError()
    except (TypeError, ValueError):
        raise OmniError('Video reference must be a public HTTPS image URL') from None
    return url


def _meta_for_model(name: str) -> dict:
    # This list is cached by the shared catalog; it may be empty while the
    # OmniRoute instance is unavailable. Never invent per-model support.
    return next((row for row in model_entries('video') if row.get('id') == name), {})


def _field(meta: dict, *keys: str):
    for key in keys:
        if key in meta and meta[key] is not None:
            return meta[key]
    return None


def _listed(value, pattern: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(v.strip() for v in value
                              if isinstance(v, str) and re.fullmatch(pattern, v.strip(), re.I)))


def _advertised_limits(row: dict) -> dict:
    """Expose only explicit model metadata; do not assume any upstream's limits."""
    caps = dict(_DEFAULT_CAPABILITIES)
    meta = row.get('media_capabilities') or row.get('mediaCapabilities') or {}
    if not isinstance(meta, dict):
        meta = {}
    # Do not promise image-to-video for every model behind a heterogeneous
    # router. Use explicit catalog capabilities or known provider adapters.
    advertised = _field(meta, 'modalities', 'input_modalities', 'inputModalities')
    known_i2v = str(row.get('id') or '').split('/', 1)[0].lower() in {'xai', 'xai-oauth', 'runway'}
    if isinstance(advertised, (list, tuple)) and advertised:
        values = [m for m in advertised if m in ('text', 'image')]
        if values:
            caps['modalities'] = values
    elif known_i2v:
        # The standard video catalog currently labels every video model as
        # input_modalities=['text'], even when the provider supports an image.
        caps['modalities'] = ['text', 'image']
    elif isinstance(row.get('input_modalities'), (list, tuple)):
        values = [m for m in row['input_modalities'] if m in ('text', 'image')]
        if values:
            caps['modalities'] = values
    aspects = _listed(_field(meta, 'aspect_ratios', 'aspectRatios', 'supported_aspect_ratios') or
                      row.get('supported_sizes') or row.get('supportedSizes'),
                      r'\d{1,4}:\d{1,4}')
    if aspects:
        caps['aspect_ratios'] = aspects
    resolutions = _listed(_field(meta, 'resolutions', 'supported_resolutions', 'supportedResolutions'),
                          r'\d{3,4}p')
    if resolutions:
        caps['resolutions'] = resolutions
    duration = _field(meta, 'duration', 'duration_limits')
    duration = duration if isinstance(duration, dict) else {}
    minimum = _field(meta, 'min_duration', 'minDuration')
    maximum = _field(meta, 'max_duration', 'maxDuration')
    if minimum is None:
        minimum = _field(duration, 'min', 'minimum')
    if maximum is None:
        maximum = _field(duration, 'max', 'maximum')
    if isinstance(minimum, int) and not isinstance(minimum, bool) and minimum >= 1:
        caps['min_duration'] = minimum
    if isinstance(maximum, int) and not isinstance(maximum, bool) and maximum >= caps['min_duration']:
        caps['max_duration'] = maximum
    for field in ('supports_audio', 'supports_negative_prompt', 'supports_seed'):
        val = _field(meta, field, ''.join(p.title() if i else p for i, p in enumerate(field.split('_'))))
        if isinstance(val, bool):
            caps[field] = val
    return caps


class OmniVideo(VideoGenProvider):
    @property
    def name(self): return 'omniroute'

    @property
    def display_name(self): return 'OmniRoute Video'

    def is_available(self): return configured()

    def list_models(self):
        models = picker_models('video', 'OMNIROUTE_VIDEO_MODEL')
        by_id = {x.get('id'): x for x in model_entries('video')}
        for model in models:
            row = by_id.get(model['id']) or {}
            media = row.get('media_capabilities') or row.get('mediaCapabilities') or {}
            if not isinstance(media, dict):
                continue
            bounds = _field(media, 'duration', 'duration_limits')
            bounds = bounds if isinstance(bounds, dict) else {}
            for key, alternatives in {
                'min_duration': ('min_duration', 'minDuration'),
                'max_duration': ('max_duration', 'maxDuration'),
            }.items():
                value = _field(media, *alternatives)
                if value is None:
                    value = _field(bounds, 'min' if key.startswith('min') else 'max')
                if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
                    model[key] = value
            model['modalities'] = _advertised_limits(row)['modalities']
        return models

    def default_model(self): return setting('OMNIROUTE_VIDEO_MODEL') or None

    def get_setup_schema(self): return setup_schema()

    def capabilities(self):
        chosen = setting('OMNIROUTE_VIDEO_MODEL')
        return _advertised_limits(_meta_for_model(chosen)) if chosen else dict(_DEFAULT_CAPABILITIES)

    def generate(self, prompt: str, *, model: str | None = None, image_url: str | None = None,
                 reference_image_urls: list[str] | None = None, duration: int | None = None,
                 aspect_ratio: str = '16:9', resolution: str = '720p', negative_prompt: str | None = None,
                 audio: bool | None = None, seed: int | None = None, **kwargs: Any) -> dict:
        chosen = ''
        try:
            if not (prompt or '').strip():
                raise OmniError('Prompt is required')
            chosen = model_id(model, 'OMNIROUTE_VIDEO_MODEL', 'video')
            row = _meta_for_model(chosen)
            meta = row.get('media_capabilities') or row.get('mediaCapabilities') or {}
            meta = meta if isinstance(meta, dict) else {}
            body: dict[str, Any] = {'model': chosen, 'prompt': prompt}

            references = [s.strip() for s in (reference_image_urls or []) if isinstance(s, str) and s.strip()]
            if image_url and references:
                raise OmniError('One reference image supported for video; do not combine image_url and references')
            if len(references) > 1:
                raise OmniError('This video adapter supports one reference image only')
            source = (image_url or (references[0] if references else None))
            if source:
                if not isinstance(source, str) or not source.strip():
                    raise OmniError('Invalid video reference image')
                # xAI consumes `image` (NOT `image_url`) in v3.8.53;
                # other OmniRoute video handlers accept `image_url`/promptImage.
                prefix = chosen.split('/', 1)[0].lower()
                body['image' if prefix in {'xai', 'xai-oauth'} else 'image_url'] = _validated_reference_url(source.strip())

            if duration is not None:
                if not isinstance(duration, int) or isinstance(duration, bool) or not 1 <= duration <= 3600:
                    raise OmniError('Video duration must be a positive integer (at most 3600 s)')
                # Limit only when there is an explicitly advertised bound; do
                # not impose the Hermes generic 10-second default on all models.
                high = _field(meta, 'max_duration', 'maxDuration')
                duration_meta = _field(meta, 'duration', 'duration_limits')
                if high is None and isinstance(duration_meta, dict):
                    high = _field(duration_meta, 'max', 'maximum')
                if isinstance(high, int) and not isinstance(high, bool) and duration > high:
                    raise OmniError(f'Video model {chosen} advertises maximum duration {high} seconds')
                body['duration'] = duration

            if aspect_ratio and isinstance(aspect_ratio, str):
                # Skip an implicit Hermes default when the model explicitly
                # excludes it. Otherwise preserve the requested control.
                known_aspects = _listed(_field(meta, 'aspect_ratios', 'aspectRatios', 'supported_aspect_ratios') or
                                        row.get('supported_sizes') or row.get('supportedSizes'),
                                        r'\d{1,4}:\d{1,4}')
                if aspect_ratio in known_aspects or not known_aspects and aspect_ratio != '16:9':
                    body['aspect_ratio'] = aspect_ratio
            if resolution and isinstance(resolution, str):
                known_res = _listed(_field(meta, 'resolutions', 'supported_resolutions', 'supportedResolutions'), r'\d{3,4}p')
                if resolution in known_res or not known_res and resolution != '720p':
                    body['resolution'] = resolution
            if isinstance(negative_prompt, str) and negative_prompt.strip():
                body['negative_prompt'] = negative_prompt.strip()
            if audio is not None:
                body['audio'] = bool(audio)
            if seed is not None:
                if not isinstance(seed, int) or isinstance(seed, bool):
                    raise OmniError('Video seed must be an integer')
                body['seed'] = seed

            # Provider-specific controls are passed to OmniRoute. The gateway
            # is authoritative: some registered upstreams do not support them.
            rows = call_json('POST', '/videos/generations', payload=body, timeout=300).get('data', [])
            item = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
            video = item.get('url')
            if not video:
                b64 = item.get('b64_json')
                if not isinstance(b64, str) or not b64:
                    raise OmniError('OmniRoute did not return video data')
                fmt = item.get('format', 'mp4')
                if fmt not in ('mp4', 'webm', 'mov'):
                    raise OmniError('Unsupported video output format')
                video = str(save_b64_video(b64, prefix='omniroute', extension=fmt))
            return success_response(video=video, model=chosen, prompt=prompt,
                                    modality='image' if source else 'text',
                                    aspect_ratio=aspect_ratio, duration=duration or 0, provider=self.name)
        except (OmniError, ValueError, OSError) as exc:
            return error_response(error=str(exc), error_type='omniroute_error', provider=self.name,
                                  model=chosen, prompt=prompt, aspect_ratio=aspect_ratio)
