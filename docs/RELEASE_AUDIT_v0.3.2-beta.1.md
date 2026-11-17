# OmniRoute for Hermes — release audit (v0.3.2-beta.1)

Date: 2026-11-16. Candidate code compared with public OmniRoute **v3.8.53** and Hermes **v0.23.2** APIs and Marketplace rules. This is an independent, source-and-mock audit, **not** a Hermes maintainer certification.

## What changed since v0.3.1-beta.1

- **STT multipart:** model/language CRLF and control characters are rejected; filenames are sanitized so file metadata cannot inject additional multipart headers.
- **TTS media:** returns the actual `.mp3`, `.opus` or `.wav` extension based on response bytes/MIME, rather than falsely keeping the requested format; JSON/text is rejected.
- **TTS voices:** no longer advertises six generic OpenAI voices as globally valid; a provider-specific voice is editable directly in Hermes.
- **Hermes dashboard:** direct configuration of URL/key, chat/image/video/TTS/STT model selectors, TTS voice, optional search/extract provider, and an **explicit** Activate OmniRoute chat button. API key is resolved through `agent.secret_scope.get_secret_str` and is never returned to the browser.
- **Manifest:** `OMNIROUTE_API_KEY` is an optional, masked secret; first-time setup happens in the Hermes interface rather than an installation prompt. Declared required env capabilities are empty in both catalog templates.
- **CI:** fixed official `hermes-ref: v0.23.2` in both validation steps and added Python 3.14 to the offline test matrix.
- **Model claims:** unknown image and video models no longer advertise all edit/image-input capabilities; xAI/Runway image-to-video paths remain available. Video input requires public HTTPS URLs.
- **Security regression tests:** HTTP dashboard profile simulation, multipart, MIME sniffing, voice configuration, model capabilities and manifest agreement.

## What was checked locally

- All supplied Python source files parsed; JavaScript plugin entry passed `node --check`.
- YAML/JSON manifests parsed and entrypoints existed.
- Automated `unittest` suite was executed **twice**, with no network and no Hermes executable. Full run logs are included in this release folder only when packaging from the build environment.
- Archive contains source only; no `.pyc`, binary executable or compiled native components.
- User-authored dashboard API mock tested distinct Hermes profile stores. This is **not** proof of genuine auth or multiplexing in a running Hermes installation.

## Official validation — not completed

The build environment has no `hermes` CLI (`hermes: command not found`) and cannot resolve GitHub to clone a Hermes checkout. Consequently it **cannot execute the official** `hermes plugins validate ... --install-deps` command, the original `tools.plugin_guard` security scanner, isolation audit, or integration with live OmniRoute. The workflow `.github/workflows/tests.yml` schedules the official **NousResearch/hermes-agent/.github/actions/plugin-validate@v0.23.2** action for both components with `hermes-ref: v0.23.2`; its result is pending code publication. A manually runnable `scripts/validate_official.sh` is also included.

Before catalog submission, run:

```bash
bash scripts/validate_official.sh
# or explicitly:
hermes plugins validate ./backend --install-deps
hermes plugins validate ./model-provider --install-deps
```

Review every caution warning and fix any failures. Repeat runtime tests in an authenticated Hermes v0.23.2+ installation connected to OmniRoute 3.8.53: chat streaming/tool calling, image generation/edit, video, web search/extract, TTS, STT, dashboard saving/activation, and isolation between two actual profiles.

## Marketplace admission: 20 rules

| # | Rule | Current assessment |
|---|---|---|
| 1 | Human-merged gate | **Pending:** must be reviewed by Hermes maintainers |
| 2 | Exact SHA | **Pending:** requires published public repo and actual 40-digit commit SHA |
| 3 | No self-updating | **Static review: pass**; installed plugin has no updater |
| 4 | SHA bumps through PR | Process requirement for future releases |
| 5 | Owner/major-contributor submission | **Pending:** owner must submit or maintainer curate |
| 6 | Declared capabilities | **Local source/mock check: pass**; official probe pending |
| 7 | Official scanner | **Pending:** official validator not executed |
| 8 | Desktop SDK surface | Not applicable (web dashboard only, no Desktop renderer extension) |
| 9 | No core overrides | **Static review: pass**; no core rebinding; official check pending |
| 10 | Dependency security | No third-party Python dependencies added; official resolver pending |
| 11 | Credentials via Hermes | **Static review: pass** after dashboard secret-scoped lookup and masking |
| 12 | Approvals/unattended runs | **Static review: pass**; no approvals disabled or auto-executed shell |
| 13 | Risk disclosure | README documents network, sensitive media, file reads, credential storage and installer; PR description/screenshot still needed |
| 14 | Compatibility metadata | `>=0.23.2` declared in both components and templates; runtime proof pending |
| 15 | No forks of bundled plugins | Independent adapter, no bundled plugin modifications |
| 16 | One listing per lineage | **Pending:** Hermes maintainers must accept two distinct entry kinds for one integration or request packaging revision |
| 17 | No unscannable binary payload | **Local package pass**, official scanner pending |
| 18 | Password manager vendor | Not applicable |
| 19 | No infringing-content plugin | Not applicable |
| 20 | No token/coin promotion | Not applicable |

No guarantee of complete admission is possible until requirements 1, 2, 5, 7, 14 and 16 (and real integration tests) are resolved. The ZIP is **beta, not published or approved**.

## Sources used

- [Hermes v0.23.2](https://github.com/NousResearch/hermes-agent/tree/v0.23.2): `hermes_cli/plugins_context.py`, `plugins_discovery.py`, `plugins_loader.py`, `plugin_validate.py`, `plugins_manifest.py`, `web_server_dashboard.py`, `agent/secret_scope.py`, provider ABCs and `providers/base.py`.
- [Hermes catalog policy](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/plugin-catalog/README.md) and [official submission guide](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/website/docs/developer-guide/plugins/catalog-submission.md).
- [OmniRoute v3.8.53](https://github.com/cheaper-inference/OmniRoute/tree/v3.8.53): `/v1/models`, specialized image/video catalogs, audio speech/transcriptions, images edits/generations, video generations, web/search and model capability metadata.
