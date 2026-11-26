# Native model discovery (OmniRoute 3.8.53)

Desktop and Dashboard include a general catalog, separate from the existing
chat/media configuration. Defaults: all eight types, no capability restriction,
configured only, include combos, no free-only or context restriction. Filters
are temporary UI state and do not modify the OmniRoute or Hermes configuration.
No MCP is used.

- All types omits kind; a single type uses native kind. Multiple types are a
  simple membership check against returned type (missing type means chat).
- AND capabilities use the native API capability query; OR uses a simple
  any-match over the returned boolean flags in one request rather than
  issuing a Cartesian product of requests. Selecting all capabilities with
  AND is different from no restriction. Empty types return zero results.
- Native configuredOnly, min_context and q are forwarded. The catalog uses
  prefix=canonical, preserves the complete returned id, and deduplicates by id.
- Free-only requires an exact owned_by/root match against provider/modelId
  from /api/free-models and excludes discontinued/unknown offers and unverified
  combos. Missing catalog data fails closed. A listing is not a zero-cost guarantee.
- Optional profile-scoped OMNIROUTE_READ_TOKEN can be saved in either UI.
  It is never returned or sent over HTTP. A preexisting inference key with
  management access can also support free-only discovery. The separate read
  token enables provider health and global summary enrichment when supported.
  Global totals are not account-specific quotas. Rankings are not model prices.
- Inference continues to use the existing API key. TLS verification and
  no-redirect behavior are preserved. The existing model-provider and
  per-category pickers remain intact, and only compatible chat/image/video
  rows can populate those corresponding fields; saving remains explicit.
- A catalog may include keyless providers and aliases even with configuredOnly.
  Listing a model does not confirm live inference success.
- Tests use synthetic contract data; private instance JSON is not published.
