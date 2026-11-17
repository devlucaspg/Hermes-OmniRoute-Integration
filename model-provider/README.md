# OmniRoute LLM provider

This directory is the **native LLM** component of [OmniRoute for Hermes](../README.md).

Install through `hermes plugins install ./model-provider`; configure the endpoint and credentials in Hermes and select `model.provider: omniroute`, `model.base_url: <your API root>` and `model.default: <model ID>` (Hermes config). The profile delegates chat, streaming and tool calling to Hermes's own OpenAI-compatible transport; only dynamic `GET /models` discovery is implemented here. Additional media features require the sibling `backend` component.

Disclosures and caveats: [root README](../README.md#security-disclosures-marketplace-policy).


## Configuration

No API key is required during installation. Install the accompanying `omniroute-media` backend plugin to expose the OmniRoute tab in the Hermes web dashboard, then save the endpoint, key, and chat model and click **Activate OmniRoute as Hermes chat provider**. The profile is scoped to the user's Hermes configuration.
