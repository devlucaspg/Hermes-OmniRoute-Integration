# OmniRoute for Hermes 0.3.2-beta.1 — verification and release gates

Review date: 2026-11-16 (contract corrections through OmniRoute v3.8.53). This is a **candidate**, not a Marketplace-approved release.

## Authoritative upstream contracts inspected

- OmniRoute tag v3.8.53 (`cheaper-inference/OmniRoute`):
  - `src/app/api/v1/images/generations/route.ts`: `GET` lists image models and `POST` generates images.
  - `src/app/api/v1/images/edits/route.ts`: accepts JSON or multipart edits; validates model-specific image count.
  - `src/lib/images/imageRouteModel.ts`: extracts JSON `image` and `images` entries containing data URLs; **not** `reference_images`.
  - `src/app/api/v1/videos/generations/route.ts`: `GET` lists video models; `POST` supports video generation, including combos.
  - `src/app/api/v1/audio/speech/route.ts` and `audio/transcriptions/route.ts`: JSON speech output and multipart transcription input, respectively.
  - `src/app/api/v1/search/route.ts`, `web/fetch/route.ts`: search JSON and per-URL web extraction.
  - `src/app/api/v1/_shared/specialtyCatalog.ts`: specialty model endpoints select `type=image` and `type=video`.
- OmniRoute v3.8.53 additional contracts:
  - `src/app/api/v1/models/catalog.ts`: audio rows use `type: audio` with `subtype: speech|transcription`, and model catalog implements `?kind=chat&prefix=alias`.
  - `docs/reference/API_REFERENCE.md`: `GET /v1/models?kind=chat` and `prefix=alias`, per-model image size caveats; inclusionai/ming-image rejects explicit dimensions.
  - `open-sse/handlers/videoGeneration/xaiGrokImagineHandler.ts`: xAI image-to-video consumes `image` rather than `image_url`.
  - `src/app/api/v1/images/edits/route.ts`: one reference for most edits, four for Firefly, special limits for Codex.
  - `src/app/api/v1/audio/speech/route.ts` and `search/route.ts`: v3.8.53 uses API-key connection scope guards.
- Hermes Agent tag `v0.23.2` (`NousResearch/hermes-agent`):
  - `hermes_cli/plugins_context.py`: all five required backend registrars exist.
  - `providers/base.py`: `ProviderProfile.build_client_kwargs_extras()` exists.
  - `agent/image_gen_provider.py`: `save_url_image` is available.
  - `hermes_cli/web_server_dashboard.py`: dashboard plugin discovery exists.
  - `.github/actions/plugin-validate/action.yml`: official composite validator exists.

The above checks inspect **source-level contracts**; they are not runtime integration tests.

## Corrections through v0.3.2-beta.1

1. Image catalog no longer crashes when `input_modalities` is `null`/missing.
2. Video catalog uses the official `GET /v1/videos/generations` specialty endpoint, with fallback to generic `/models`.
3. Image edits send `images: [{image_url: "data:image/...;base64,..."}]` instead of ignored `reference_images`.
4. Reference images now use a bounded decode or Hermes's vetted image download; no raw plugin HTTP fetch to arbitrary reference URLs.
5. Video optional `negative_prompt`, `seed`, and `audio` controls are no longer silently discarded; upstream/model support varies.
6. OmniRoute API credentials use Hermes profile-scoped secret retrieval. External HTTP redirects and implicit HTTP proxies are disabled for authenticated API calls.
7. Plain HTTP API endpoints are limited to explicitly local/private addresses and hostname conventions; public addresses require HTTPS.
8. Dashboard selection of video models now queries the video specialty catalog. Connection data is validated before any write.
9. Native LLM provider supplies a profile-scoped default `base_url` via Hermes's `ProviderProfile` hook; an explicit Hermes model endpoint continues to take precedence.
10. Added the official Hermes validator composite action to GitHub CI, pinned to stable `v0.23.2`.
11. Both manifests and both Marketplace templates now declare conservative `requires_hermes: ">=0.23.2"`, backed by source-level API verification.
12. Generated image URLs are cached through Hermes's own safe image downloader where possible; URL fallback remains available.

## Delta vs previous v0.3.0-beta.1

1. `type: audio` + `subtype` correctly separates TTS from STT in both backend and web dashboard.
2. Both Hermes model provider and backend filter LLM catalog with `kind=chat&prefix=alias`, and discard explicitly typed non-chat rows.
3. Image size is omitted if the catalog has no explicit pixel sizes (including Ming Image); ratio-only values are not misused as `size`.
4. Image edit count reflects known model family: one for most providers, four for Firefly, eight or sixteen for the relevant Codex variants.
5. xAI image-to-video passes `image`, not `image_url`, while other providers retain `image_url`.
6. Video duration >10 s is allowed when OmniRoute does not advertise a narrower bound; Hermes schema is not artificially capped for unknown models.
7. Video list models now carries model-specific duration/modalities when such metadata is present, and capabilities are derived from the selected model.
8. Sanitized HTTP error-code extraction preserves machine-readable scope/endpoint failures without forwarding upstream prose or secrets.
9. Added regression coverage for catalog filters, audio subtypes, image sizing, xAI reference fields, video durations, dynamic capabilities and safe error handling.

## Tests executed in this environment

- `python3 -m unittest discover -s tests -v`: 52 offline tests, passed (re-run before publishing).
- `python3 -m compileall -q backend model-provider`: passed.
- `node --check backend/dashboard/dist/index.js`: passed.
- YAML manifest and catalog-template structural checks: passed.
- Package ZIP integrity, absence of bytecode and native binary payloads: passed.

These checks do **not** assert that the plugin passes the Hermes admission scanner.

## Remaining external gates — must not be represented as passed

- Execute `hermes plugins validate ./backend --install-deps` and `hermes plugins validate ./model-provider --install-deps` on Hermes v0.23.2 or a compatible newer release, and resolve any warnings/findings. GitHub CI will run official composite validation once the repository is published.
- Test actual Hermes runtime registration and dashboard mounts with real profiles, including multiplexed profile isolation.
- Integration-test OmniRoute with a real API key and configured upstreams: chat+streaming+tools, image generation/editing, video, search/extract, TTS and STT.
- Publish a public repository, obtain an exact 40-character commit SHA and replace placeholder URLs/account names in `catalog/*.yaml.template`.
- Submit the two catalog entries (or obtain approval for an alternate packaging design) and wait for maintainer review.

## References

- https://github.com/cheaper-inference/OmniRoute/tree/v3.8.53
- https://github.com/NousResearch/hermes-agent/tree/v0.23.2
- https://github.com/NousResearch/hermes-agent/blob/main/plugin-catalog/README.md
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/plugins/catalog-submission.md


### Revision 0.3.2-beta.1 validation limits

Adversarial STT multipart and TTS audio format tests were added, as well as a mock FastAPI dashboard showing explicit chat activation and profile segregation. These tests are **not** the actual Hermes security scanner or a live installation. The official composite action is configured but did not execute in this environment (no Hermes runtime and no GitHub network access). The two catalog templates cannot be finalized before public GitHub commit and maintainer review.
