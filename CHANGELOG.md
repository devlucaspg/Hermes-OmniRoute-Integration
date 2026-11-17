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
