# Enriched discovery — 0.5.0-beta.1

Experimental branch; do not install in production without verification. All inference
remains on OmniRoute. Public catalogs only supplement exact authorized canonical
routing IDs (owner + "/" + root). No upstream credentials are requested or forwarded.

- NVIDIA NGC search + OpenAPI request schema: nim_type_preview; no AVAILABLE-based
  rejection, no name guessing. Non-model resources and ambiguous specs are reported.
- OpenRouter: exact :free variant with zero prompt/completion price; additional
  modalities and positive token prices are not proof of free access.
- xKiro: explicit access_tier. Premium is subscription classification, not proof
  of entitlement. LLM7: turbo + not usage_based_only is a limited offer.
- Ollama: local route only when configuredOnly is enabled; not proof of zero energy cost.
- Profile-local atomic JSON cache, on-demand refresh after TTL (default 6 hours);
  expired/failed entries do not establish free access. Partial results preserve picker.
- Native catalog, effective free summary and exact model health remain authoritative.
  Explicit disabled offers are not resurrected. External pricing can override stale native free claims.
- Quota status is unknown unless a relevant fresh account window is known;
  currently OpenRouter free_daily/free_rpm and xKiro free_daily. No generic
  provider-wide percentage is used as model-specific evidence.
- No automatic inference or billing guarantee. Unverified combos not free.
- Gemini, Groq, Mistral, Cloudflare, SambaNova, Nara and GitHub remain native-only
  pending provider-specific entitlement contracts. Unsupported tags remain unknown.
- Provider source toggles are per query and saved with the last successful picker
  selection. No background worker or extra CT. Native refresh reloads last applied IDs.
