"""Profile-aware OmniRoute speech and transcription adapters (stdlib multipart)."""
from __future__ import annotations

import json
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any

from agent.tts_provider import TTSProvider
from agent.transcription_provider import TranscriptionProvider
from ..core import OmniError, call, configured, model_id, picker_models, setting, setup_schema

# Content types are advisory: detect known magic bytes before trusting a server's
# declared MIME, so an upstream MP3 response is never written with a WAV suffix.
_AUDIO_MIME = {
    'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/x-mpeg': 'mp3',
    'audio/wav': 'wav', 'audio/wave': 'wav', 'audio/x-wav': 'wav',
    'audio/ogg': 'opus', 'audio/opus': 'opus',
}


def _audio_extension(body: bytes, content_type: str, requested: str) -> str:
    if body.startswith(b'RIFF') and body[8:12] == b'WAVE':
        return 'wav'
    if body.startswith(b'ID3') or (len(body) >= 2 and body[0] == 0xff and body[1] & 0xe0 == 0xe0):
        return 'mp3'
    if body.startswith(b'OggS') or body.startswith(b'OpusHead'):
        return 'opus'
    mime = (content_type or '').split(';', 1)[0].strip().lower()
    if mime in _AUDIO_MIME:
        return _AUDIO_MIME[mime]
    if mime.startswith(('application/json', 'text/', 'text/json')):
        raise OmniError('OmniRoute returned JSON/text instead of synthesized audio')
    if mime not in ('', 'application/octet-stream', 'binary/octet-stream'):
        raise OmniError('OmniRoute returned an unsupported audio format')
    # Opaque binary: no contradictory MIME and no detected signature.
    return requested


def _safe_form_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise OmniError(f'Invalid {label} field for multipart upload')
    return value


def _safe_filename(filename: str) -> str:
    # Filename is metadata, never a trusted MIME or filesystem path. No CRLF or
    # quote/backslash can escape the Content-Disposition quoted parameter.
    return re.sub(r'[\x00-\x1f\x7f"\\/]', '_', filename)[-180:] or 'audio.bin'


def _multipart_upload(path: Path, model: str, language: str | None, *, limit: int = 25 * 1024 * 1024):
    """Build one bounded form-data body, validating text before constructing parts."""
    model = _safe_form_text(model, 'model')
    language = _safe_form_text(language, 'language') if language is not None else None
    if not path.is_file() or path.stat().st_size > limit:
        raise OmniError('STT input must be an audio file up to 25 MiB')
    name = _safe_filename(path.name)
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    boundary = '----omniroute-' + uuid.uuid4().hex
    data = bytearray()
    fields = {'model': model, 'response_format': 'json'}
    if language is not None:
        fields['language'] = language
    for field, value in fields.items():
        data.extend((f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n'
                     f'{value}\r\n').encode('utf-8'))
    data.extend((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                 f'Content-Type: {mime}\r\n\r\n').encode('utf-8'))
    data.extend(path.read_bytes())
    data.extend(f'\r\n--{boundary}--\r\n'.encode('ascii'))
    return bytes(data), f'multipart/form-data; boundary={boundary}'


class OmniTTS(TTSProvider):
    @property
    def name(self): return 'omniroute'
    @property
    def display_name(self): return 'OmniRoute Text-to-Speech'
    def is_available(self): return configured()
    def list_models(self): return picker_models('tts', 'OMNIROUTE_TTS_MODEL')
    def default_model(self): return setting('OMNIROUTE_TTS_MODEL') or None

    def list_voices(self):
        # /v1/models does not list a canonical set of voices for every upstream.
        # Declaring stock OpenAI voices as universally available was incorrect.
        # Operators can set OMNIROUTE_TTS_VOICE in the Hermes dashboard.
        v = setting('OMNIROUTE_TTS_VOICE')
        return [{'id': v, 'display': v}] if v else []

    def default_voice(self): return setting('OMNIROUTE_TTS_VOICE') or None
    def get_setup_schema(self): return setup_schema()

    def synthesize(self, text: str, output_path: str, *, voice: str | None = None,
                   model: str | None = None, speed: float | None = None,
                   format: str = 'mp3', **extra: Any) -> str:
        if not (text or '').strip():
            raise OmniError('TTS requires text')
        chosen = model_id(model, 'OMNIROUTE_TTS_MODEL', 'TTS')
        fmt = format if format in ('mp3', 'opus', 'wav') else 'mp3'
        payload: dict[str, Any] = {'model': chosen, 'input': text, 'response_format': fmt}
        chosen_voice = voice or self.default_voice()
        if chosen_voice:
            payload['voice'] = _safe_form_text(chosen_voice, 'voice')
        if speed is not None:
            if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.25 <= speed <= 4:
                raise OmniError('TTS speed must be from 0.25 to 4')
            payload['speed'] = speed
        raw, content_type = call('POST', '/audio/speech', payload=payload, timeout=120, limit=32 * 1024 * 1024)
        if not raw:
            raise OmniError('OmniRoute returned empty synthesized audio')
        actual_format = _audio_extension(raw, content_type, fmt)
        path = Path(output_path).expanduser().absolute().with_suffix('.' + actual_format)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return str(path)

    @property
    def voice_compatible(self): return True


class OmniSTT(TranscriptionProvider):
    @property
    def name(self): return 'omniroute'
    @property
    def display_name(self): return 'OmniRoute Speech-to-Text'
    def is_available(self): return configured()
    def list_models(self): return picker_models('stt', 'OMNIROUTE_STT_MODEL')
    def default_model(self): return setting('OMNIROUTE_STT_MODEL') or None
    def get_setup_schema(self): return setup_schema()

    def transcribe(self, file_path: str, *, model: str | None = None,
                   language: str | None = None, **extra: Any) -> dict:
        try:
            chosen = model_id(model, 'OMNIROUTE_STT_MODEL', 'STT')
            data, mime = _multipart_upload(Path(file_path).expanduser(), chosen, language)
            raw, _ = call('POST', '/audio/transcriptions', data=data, content_type=mime, timeout=120)
            try:
                response = json.loads(raw)
            except (TypeError, ValueError):
                raise OmniError('OmniRoute returned an invalid transcription') from None
            transcript = str(response.get('text') or '').strip() if isinstance(response, dict) else ''
            if not transcript:
                raise OmniError('OmniRoute returned an empty transcription')
            return {'success': True, 'transcript': transcript, 'provider': self.name}
        except (OmniError, OSError, ValueError) as exc:
            return {'success': False, 'transcript': '', 'error': str(exc), 'provider': self.name}
