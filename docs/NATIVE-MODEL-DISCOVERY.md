# Native model discovery (OmniRoute 3.8.53)

Desktop and Dashboard include a general catalog, separate from the existing
chat/media configuration. Defaults: all eight types, no capability restriction,
configured only, include combos, no free-only or context restriction. Filters
are temporary UI state and do not modify the OmniRoute or Hermes configuration.
No MCP is used.

- All types omits kind; a single non-chat type uses native kind. Chat deliberately retains the stable picker's typed combos and legacy aliases. Multiple types are a
  simple membership check against returned type (missing type means chat).
- AND capabilities use the native API capability query; OR uses a simple
  any-match over the returned boolean flags in one request rather than
  issuing a Cartesian product of requests. Selecting all capabilities with
  AND is different from no restriction. Empty types return zero results.
- Native configuredOnly, min_context and q are forwarded. The catalog uses
  prefix=canonical, preserves the complete returned id, and deduplicates by id. It reuses the stable beta.2 paginated transport (200 rows/page, adaptive size, bounded total, fail-closed on incomplete pages).
- Free-only requires an exact owned_by/root match against provider/modelId
  from /api/free-models and excludes discontinued/unknown offers and unverified
  combos. Missing catalog data fails closed. A listing is not a zero-cost guarantee.
- Optional profile-scoped OMNIROUTE_READ_TOKEN can be saved in either UI.
  It is never returned or sent over HTTP. Changing the endpoint with a stored read token requires explicit replacement or removal. A preexisting inference key with
  management access can also support free-only discovery. The separate read
  token enables provider health and global summary enrichment when supported.
  An existing inference key is used for management only on explicit free-only discovery if no separate token exists.
  Global totals are not account-specific quotas. The effective summary can retire a baseline offer; these rows are not revived. If the summary cannot be read, the UI warns that only baseline offers are represented. Rankings are not model prices.
- Inference continues to use the existing API key. TLS verification and
  no-redirect behavior are preserved. The existing model-provider and
  per-category pickers remain intact, and only compatible chat/image/video
  rows can populate those corresponding fields; saving remains explicit.
- A catalog may include keyless providers and aliases even with configuredOnly.
  Listing a model does not confirm live inference success.
- Tests use synthetic contract data; private instance JSON is not published.


## Applied conversation catalog

A successful query from either plugin UI publishes only the matching chat IDs to the current Hermes profile, preserving exact routing IDs. The native provider and configured relay catalog paths read the same snapshot. The native conversation menu's Refresh Models button reloads the applied selection; run Consultar catálogo again for fresh upstream data or to change filters. Non-chat results remain in the general catalog; the selected model and other providers are unchanged. An empty successful chat result is intentional; a failed query leaves the previous selection in place. No credentials are stored in the snapshot. Replacing the endpoint or inference key clears the applied selection. This is a picker preference, not an inference access-control policy.
