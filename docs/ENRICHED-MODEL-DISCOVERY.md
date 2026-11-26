# Enriched discovery — 0.5.0-beta.3

Experimental branch; do not install in production without verification. All inference
remains on OmniRoute. Public catalogs only supplement exact authorized canonical
routing IDs (owner + "/" + root). No upstream credentials are requested or forwarded.

- NVIDIA NGC search + OpenAPI request schema: nim_type_preview; no AVAILABLE-based
  rejection, no name guessing. Non-model resources, null specifications and ambiguous specs are reported as unresolved, not guessed.
- OpenRouter: exact :free variant with zero prompt/completion price; additional
  modalities and positive token prices are not proof of free access.
- xKiro: explicit access_tier. Premium and paid require a paid account; neither proves
  a subscription entitlement. LLM7: turbo + not usage_based_only is a limited offer.
- Ollama: local route only when configuredOnly is enabled; not proof of zero energy cost.
- Profile-local atomic JSON cache, on-demand refresh after TTL (default 6 hours);
  expired/failed entries do not establish free access. Partial results preserve picker.
- Native catalog, effective free summary and exact model health remain authoritative.
  Explicit disabled offers are not resurrected. External pricing can override stale native free claims.
- Quota status is unknown unless a relevant fresh account window is known;
  currently OpenRouter free_daily/free_rpm and xKiro free_daily. No generic
  provider-wide percentage is used as model-specific evidence.
- No automatic inference or billing guarantee. Unverified combos not free.
- Gemini: official Developer API pricing Markdown, exact model IDs and explicit Standard Free Tier cells; mixed pricing is unknown.
- Groq: official HTML Free Plan table with active-tab verification; unlisted exact IDs are unknown rather than inheriting stale native free claims.
- Cloudflare: official Neuron pricing Markdown, exact @cf/ IDs, shared daily 10000 Neurons, explicit paid exceptions. No alias guessing.
- SambaNova: public REST metered prices, not proof of absence of account promotional credit.
- Mistral: official Labs lifecycle policy; only the documented labs- prefix on exact configured routes. Other tiers need account evidence.
- Nara, GitHub, AI Horde and web-only routes remain native-only pending reliable entitlement contracts.
- Documentation parsers fail closed on unexpected formats. Expired quota reset windows are unknown.
- Typed media with missing root match only exact owner-prefixed identifiers.
  Previously saved full four-source selections migrate to the nine-source default; narrower selections are preserved.
- Provider source toggles are per query and saved with the last successful picker
  selection. No background worker or extra CT. Native refresh reloads last applied IDs.

## Fixed providers

Select any configured provider exposed to the current inference key via `GET /configured-providers`. `pinned_providers` is independent of every normal search filter, including model kind, pricing, health, quotas, context and text. The server always requests a configured-only authorized catalog and excludes combos from fixed provider selection. Results are an exact-ID union with `matched_search` and `pinned` flags, `search_count`, `pinned_count` and `pinned_added_count`. A fixed provider is not assumed free; paid or blocked models may be included, without invoking inference. Only chat models reach the conversation picker. Pins persist in the profile's last successful picker selection; restoring normal filters preserves them. Clearing pins removes them on the next successful consultation. No access policy is bypassed.
