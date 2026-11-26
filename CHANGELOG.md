## 0.4.0-beta.2 — Complete authorized model discovery

- Retrieve the unified catalog with bounded, cursor-based paging (`limit` / `after`), preserving the alias namespace and API-key policy. Do not use the narrower literal `kind=chat` server filter; classify chat locally, including legitimate chat subtypes and combos.
- Remove the dashboard's 1,000-model truncation; deduplicate IDs after modality selection.
- Keep the 4 MiB per-response safety budget, shrink oversized pages, use a 20-second default per-request timeout, and reject malformed/repeated cursors rather than publish partial catalogs.
- Register the Hermes v0.23.2 provider-owned catalog hook and base-URL environment metadata without a global endpoint or credential. Do not replace an explicitly empty key with another credential.
- Log sanitized discovery failures, reduce successful media cache TTL to 60 seconds, and do not cache failed catalogs.
- Add offline regression coverage for large catalogs, cursor handling, modality segregation, and independent package parity. Hermes Desktop's initial 50-model visibility setting remains unchanged.
- Candidate release; live deployment and official validator results must be checked separately.

## 0.4.0-beta.1 — Native Hermes Desktop settings

- Added a `backend/desktop/plugin.js` half to the existing `omniroute-media` package; it registers a native OmniRoute settings page and uses `ctx.rest` against the existing profile-scoped API.
- Added a Windows-only local Desktop installer with automatic backup and TXT log, without touching CT221 or OmniRoute.
- Kept the existing LLM/media Python adapters and dashboard API behavior unchanged.
- Corrected the local developer installer for Hermes 0.23.2: validate both components, stage a local Git snapshot and use `file://...#component` instead of a bare folder path. GitHub remains the intended distribution mechanism.
- Added isolated Desktop mock tests, status/activation guards and documentation for remote Hermes backends.
- Official Desktop SDK validation and live Windows/CT221 runtime tests remain pending.

# Changelog

## 0.3.2-beta.1 — Hermes dashboard + Marketplace hardening

- STT: reject control characters in multipart text fields; sanitize transmitted filenames.
- TTS: detect actual output media format from response MIME and magic bytes before saving; no universal OpenAI voice claims.
- Hermes Dashboard: add preference editors (TTS voice and search/extract provider overrides), explicit chat activation, and profile-scoped secret lookup.
- Registration: make endpoint and API key optional at install, so the web dashboard can be used for first-time configuration; declare the key as masked `password` and `secret` metadata.
- Model capabilities: conservative image edit and video input declarations when support is unknown; retain known compatible provider paths.
- CI: fix `hermes-ref: v0.23.2` in the official validator action and extend Python tests to 3.14.
- Security: new adversarial regression tests and dashboard API profile isolation simulation; correct packaging and release guidance.

## 0.3.2-beta.1 — OmniRoute v3.8.53 compatibility update

- LLM picker now queries `/v1/models?kind=chat&prefix=alias` and excludes explicit non-chat models.
- TTS/STT selectors correctly interpret `type: audio` with `subtype: speech` or `transcription` (backend and dashboard).
- Image generation omits unsupported arbitrary `size` defaults; explicit pixel-sized overrides remain available.
- Reference image limits now follow supported edit-family contracts instead of claiming a universal eight images.
- xAI image-to-video requests send `image`; other routes continue to use `image_url`.
- Video removes the generic ten-second dispatch restriction, exposes supported per-model duration/modalities and accepts longer models when upstream permits.
- HTTP 4xx/5xx errors preserve safe structured upstream codes without echoing upstream error bodies or secrets.
- Extended offline contract test suite to 52 tests, including dashboard HTTP adapter and native model-provider discovery.

### Validation status

Source contract checked against OmniRoute tag `v3.8.53` and Hermes tag `v0.23.2`. Offline tests passed. Official Hermes `plugins validate` and full live OmniRoute/Hermes integration remain pending. Marketplace not submitted.
