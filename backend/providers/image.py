"""Text-to-image and image-edit adapter. No model hardcoded for any instance."""
from __future__ import annotations
import base64
import mimetypes
import re
from pathlib import Path
from typing import Any

from agent.image_gen_provider import ImageGenProvider, error_response, save_b64_image, save_url_image, success_response
from ..core import OmniError, call_json, configured, model_id, model_entries, picker_models, setup_schema


def _orientation(size: str) -> str:
    try:
        sep = 'x' if 'x' in size.lower() else ':'
        w, h = (int(i) for i in size.lower().split(sep))
        return 'landscape' if w > h else 'portrait' if w < h else 'square'
    except (ValueError, TypeError):
        return 'unknown'


_PIXELS = re.compile(r'^[1-9][0-9]{1,4}x[1-9][0-9]{1,4}$', re.I)


def _size(rows: list[dict], model: str, aspect: str) -> str | None:
    """Only send pixel sizes explicitly advertised by this image model.

    OmniRoute 3.8.53 rejects an explicit size for certain models (notably
    zm/inclusionai/ming-image-0.1-design). Ratio-only supported_sizes are not
    pixel sizes; sending e.g. `16:9` as OpenAI `size` is also unsafe.
    When uncertain, OMIT size and let OmniRoute decide the provider default.
    """
    entry = next((row for row in rows if row.get('id') == model), {})
    advertised = entry.get('supported_sizes') or entry.get('supportedSizes') or []
    pixels = [v for v in advertised if isinstance(v, str) and _PIXELS.fullmatch(v.strip())] \
        if isinstance(advertised, (list, tuple)) else []
    return next((v for v in pixels if _orientation(v) == aspect), pixels[0] if pixels else None)


def _max_references(model: str) -> int:
    """Conservative limits from OmniRoute 3.8.53 images/edits route.

    For nested combo names the underlying target may differ; use the default
    one-reference path rather than guessing the target's capabilities.
    """
    name = model.lower()
    if name.startswith('codex/'):
        return 16 if '/gpt-image-' in name else 8
    if name.startswith(('adobe-firefly/', 'firefly/')):
        return 4
    return 1


def _extension(raw_b64: str) -> str:
    try:
        sig = base64.b64decode(raw_b64.split(',', 1)[-1][:32])
    except Exception:
        return 'png'
    if sig.startswith(b'\xff\xd8\xff'): return 'jpg'
    if sig.startswith(b'GIF8'): return 'gif'
    if sig.startswith(b'RIFF') and sig[8:12] == b'WEBP': return 'webp'
    return 'png'


def _image_ref(value: str) -> str:
    """OmniRoute JSON edit parsing accepts DATA URLs, not arbitrary HTTP URLs.

    Download remote URLs only through Hermes's vetted image download helper,
    then encode the bytes. The plugin itself never fetches an arbitrary URL.
    """
    import binascii
    import re
    value = value.strip()
    if value.startswith(('https://', 'http://')):
        try:
            value = str(save_url_image(value, prefix='omniroute-input'))
        except Exception as exc:
            raise OmniError('Hermes could not download the supplied reference image URL') from None
    if value.startswith('data:image/'):
        match = re.fullmatch(r'data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=]+)', value, flags=re.I)
        if not match:
            raise OmniError('Reference image must be a valid PNG/JPEG/WebP/GIF base64 data URL')
        encoded = match.group(2)
        if len(encoded) > 28 * 1024 * 1024:
            raise OmniError('Reference image exceeds 20 MiB')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise OmniError('Invalid reference image base64') from exc
        if len(raw) > 20 * 1024 * 1024 or not raw:
            raise OmniError('Reference image must contain 1 to 20 MiB')
        return 'data:' + match.group(1).lower() + ';base64,' + encoded
    path = Path(value).expanduser()
    if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
        raise OmniError('Referenced image must be a file, data URL or downloadable image URL up to 20 MiB')
    mime = mimetypes.guess_type(path.name)[0] or ''
    if mime not in {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}:
        raise OmniError('Referenced local image must be PNG, JPEG, WebP or GIF')
    return 'data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


class OmniImage(ImageGenProvider):
    @property
    def name(self): return 'omniroute'

    @property
    def display_name(self): return 'OmniRoute Images'

    def is_available(self): return configured()
    def list_models(self): return picker_models('image', 'OMNIROUTE_IMAGE_MODEL')
    def default_model(self):
        from ..core import setting
        return setting('OMNIROUTE_IMAGE_MODEL') or None
    def get_setup_schema(self): return setup_schema()
    def capabilities(self):
        # Hermes exposes capabilities at provider scope: derive the optional
        # reference count from the configured model, never advertise eight
        # images universally for a mixed-model router.
        from ..core import setting
        selected = setting('OMNIROUTE_IMAGE_MODEL')
        # An OmniRoute router may expose image-generation-only models. Avoid
        # advertising edits if the selected model is unknown or not edit-capable.
        known_edit_prefixes = ('codex/', 'adobe-firefly/', 'firefly/', 'fal-ai/', 'openrouter/')
        known_edit = bool(selected and selected.lower().startswith(known_edit_prefixes))
        limits = _max_references(selected) if known_edit else 0
        return {'modalities': ['text', 'image'] if known_edit else ['text'],
                'max_reference_images': limits}

    def generate(self, prompt: str, aspect_ratio: str = 'landscape', *, image_url: str | None = None,
                 reference_image_urls: list[str] | None = None, **kwargs: Any) -> dict:
        name = ''
        try:
            if not (prompt or '').strip():
                raise OmniError('Prompt is required')
            name = model_id(kwargs.get('model'), 'OMNIROUTE_IMAGE_MODEL', 'image')
            refs = ([image_url] if image_url else []) + list(reference_image_urls or [])
            maximum = _max_references(name)
            if len(refs) > maximum:
                raise OmniError(f'Image edit model {name} supports up to {maximum} reference image(s)')
            references = [_image_ref(x) for x in refs if isinstance(x, str) and x.strip()]
            if sum(len(x) for x in references) > 28 * 1024 * 1024:
                raise OmniError('Total reference image payload exceeds 20 MiB')
            aspect = aspect_ratio if aspect_ratio in ('landscape', 'portrait', 'square') else 'square'
            payload = {'model': name, 'prompt': prompt}
            requested_size = kwargs.get('size')
            if requested_size is not None:
                if not isinstance(requested_size, str) or not _PIXELS.fullmatch(requested_size):
                    raise OmniError('Explicit image size must be WxH pixels')
                # A caller-provided override is intentional; OmniRoute decides
                # whether the selected provider accepts those dimensions.
                payload['size'] = requested_size
            else:
                size = _size(model_entries('image'), name, aspect)
                if size is not None:
                    payload['size'] = size
            if references:
                # OmniRoute's extractImageEditInputFromJson reads `image` and
                # `images[][].image_url`; reference_images is not parsed.
                payload['images'] = [{'image_url': ref} for ref in references]
            route = '/images/edits' if references else '/images/generations'
            rows = call_json('POST', route, payload=payload, timeout=120).get('data', [])
            item = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
            url = item.get('url')
            if isinstance(url, str) and url.startswith(('https://', 'http://')):
                # Cache when possible using Hermes's own hardened media fetcher;
                # preserve the upstream URL if its CDN cannot be downloaded.
                try:
                    url = str(save_url_image(url, prefix='omniroute-generated'))
                except Exception:
                    pass
            if not url:
                b64 = item.get('b64_json')
                if not isinstance(b64, str) or not b64:
                    raise OmniError('OmniRoute did not return an image URL or base64 data')
                url = str(save_b64_image(b64, prefix='omniroute', extension=_extension(b64)))
            return success_response(image=url, model=name, prompt=prompt, aspect_ratio=aspect, provider=self.name,
                                    modality='image' if references else 'text')
        except (OmniError, OSError, ValueError) as exc:
            return error_response(error=str(exc), error_type='omniroute_error', provider=self.name,
                                  model=name, prompt=prompt, aspect_ratio=aspect_ratio)
