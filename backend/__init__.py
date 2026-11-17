"""OmniRoute multi-backend plugin for Hermes Agent.

All backends are registered through Hermes public PluginContext methods. The LLM
provider is in the companion model-provider/ plugin because Hermes uses a
separate lazy discovery loader for kind:model-provider.
"""
from __future__ import annotations

from .providers.image import OmniImage
from .providers.video import OmniVideo
from .providers.web import OmniWeb
from .providers.audio import OmniTTS, OmniSTT


def register(ctx):
    ctx.register_image_gen_provider(OmniImage())
    ctx.register_video_gen_provider(OmniVideo())
    ctx.register_web_search_provider(OmniWeb())
    ctx.register_tts_provider(OmniTTS())
    ctx.register_transcription_provider(OmniSTT())
