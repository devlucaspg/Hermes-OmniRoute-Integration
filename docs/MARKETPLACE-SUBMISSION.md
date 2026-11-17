# Hermes Marketplace submission checklist

- [ ] Public GitHub repo created, LICENSE/README available and maintainer account matches submitter.
- [ ] Verify license/third-party attribution; no code incorporated from CVlad97.
- [ ] Run `hermes plugins validate ./backend --install-deps` and `hermes plugins validate ./model-provider --install-deps` against current Hermes release.
- [ ] Run real live tests with chat streaming/tools, one representative image generation/edit, one video generation, search/extract, TTS/STT, with configured upstream credentials.
- [ ] Verify real model/provider selection in the Hermes dashboard, authentication, reload, and multiplexed profile isolation (only simulated offline here).
- [ ] The conservative floor is >=0.23.2 (public extension APIs confirmed in the release sources). Verify actual runtime loading and version semantics before release; raise the floor if necessary.
- [ ] Resolve any dashboard build/SDK incompatibility before submitting.
- [ ] Check security scan output, fix dangerous findings and document caution findings.
- [ ] Commit tested source to GitHub, record full 40-digit commit SHA.
- [ ] Replace template placeholders, add two files to NousResearch/hermes-agent/plugin-catalog/.
- [ ] Include third-party calls, local file reads, key persistence, network scope, shell installer disclosure and UI screenshot in PR.
- [ ] Confirm whether two listings are acceptable or ask maintainers for one combined catalog entry; do not promise native one-click installation of both without official support.
- [ ] Await maintainer approval and green catalog CI.

Potential review considerations:
1. Prove `model.base_url` is supplied by the Hermes native model config when a user picks this provider.
2. Ensure dashboard plugin API is mounted in the current Hermes version and correctly scoped to the selected profile.
3. Catalog metadata must reflect exactly the hooks/providers registered; verify `capabilities` semantics.
4. The 3.8.53 model list exposes `type: audio` plus `subtype: speech|transcription`, and dedicated image/video GET catalogs; empty catalogs can still occur with unavailable upstreams.

## Source contract verified

- OmniRoute tag `v3.8.53`: `src/app/api/v1/images/edits/route.ts` accepts multipart and JSON data URL images. `src/lib/images/imageRouteModel.ts` expects `images: [{image_url: "data:..."}]` (not `reference_images`).
- OmniRoute tag `v3.8.53`: `GET /v1/videos/generations` and `GET /v1/images/generations` filter unified model catalog by modality.
- `POST /v1/videos/generations` supports additional optional request controls, subject to upstream-specific behavior.
- Hermes `v0.23.2` includes required provider registration APIs and `build_client_kwargs_extras`; this is not proof that all runtime paths work.
- CI uses the pinned official `plugin-validate@v0.23.2` composite action for both components.

## Mandatory validation remains outstanding

The development environment used for 0.3.2-beta.1 has no `hermes` binary and cannot reach GitHub by `git`; **the official validator, its dependency resolver, scanner, core-override/private-import checks, and live Hermes runtime were not executed**. Both official composite-action invocations are configured in `.github/workflows/tests.yml` with `hermes-ref: v0.23.2`. Run the workflow after publishing the repository, inspect **every** warning, and fix all official failures before submitting. The catalog templates intentionally retain placeholders because a real public repository and immutable full SHA are not yet available. Community publication and accepting two related entries are human-review questions, not automatic technical certifications.
