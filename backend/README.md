# OmniRoute Media / Web / Voice

This directory is the **backend component** of [OmniRoute for Hermes](../README.md).

Capabilities: image generation/editing, video generation, web search / extraction, TTS and STT, via a user-configured OmniRoute endpoint. Install with `hermes plugins install ./backend --enable` from the repository root. Configure `OMNIROUTE_BASE_URL` and `OMNIROUTE_API_KEY` via Hermes's credential/config UI, then select the desired backend in Hermes config. For native LLM chat, install `../model-provider` separately.

Disclosures and caveats: [root README](../README.md#security-disclosures-marketplace-policy).


## Hermes dashboard configuration

The backend plugin installs without mandatory credentials and adds an OmniRoute tab to the authenticated Hermes dashboard. Configure the server URL, API key, models, TTS voice and web-provider preferences. Chat activation is an explicit button, not a silent override. Changes may require reloading Hermes. The LLM plugin is a separate catalog entry because Hermes discovers native model providers independently.
