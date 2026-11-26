# OmniRoute for Hermes — community integration

[Leia em Português (Brasil)](README.pt-BR.md)

**Release candidate:** `0.4.0-beta.5` (not yet submitted or accepted by the official Hermes Marketplace).

An original, self-hosted integration connecting the [Hermes Agent](https://github.com/NousResearch/hermes-agent) to any configured [OmniRoute](https://github.com/cheaper-inference/OmniRoute) OpenAI-compatible routing instance.

> Not affiliated with or endorsed by Hermes, Nous Research or OmniRoute. 

## Capabilities

| Surface | Component | Endpoint | Notes |
| --- | --- | --- | --- |
| LLM chat, tool calling, streaming and vision-capable models | `model-provider/` | `POST /chat/completions` | Native Hermes transport, uses Hermes `model.provider=omniroute`; not a custom chat transport |
| Live LLM model discovery | `model-provider/` | `GET /models?prefix=alias&limit=200` | Excludes typed media/embeddings; no hardcoded fallback IDs |
| Image generation | `backend/` | `POST /images/generations` | Send size only if advertised in pixels (never inject a default); permits models requiring no size |
| Image editing and references | `backend/` | `POST /images/edits` | Model-specific limits: usually 1, Firefly up to 4, Codex 8 or 16; Hermes safe URL downloads |
| Video generation | `backend/` | `GET/POST /videos/generations` | Live specialty catalog and per-model metadata; no fixed 10-second dispatch limit; xAI image field corrected |
| Web search | `backend/` | `POST /search` | Optional fixed search provider; otherwise OmniRoute routes |
| Web extraction | `backend/` | `POST /web/fetch` | Each URL processed separately; per-URL failure preserved |
| Text-to-speech | `backend/` | `POST /audio/speech` | MP3/Opus and models discovered via type=audio/subtype=speech |
| Speech-to-text | `backend/` | `POST /audio/transcriptions` | Multipart; models discovered via type=audio/subtype=transcription |
| Dashboard | `backend/` | Hermes extension API | Private settings, safe model browsing, selection |

All paths are relative to an **explicit user-configured API root**, such as `https://router.example/api/v1` or `http://127.0.0.1:3000/api/v1`. No real HomeLab host or password is embedded.

## Why there are two plugin manifests

Hermes's `kind: model-provider` is discovered and loaded by its provider registry, while media/web/voice adapters use `kind: backend` and the regular `PluginContext.register_*` registration lifecycle. To avoid patching Hermes core, the repository contains **two deployable catalog components** under distinct subdirectories. One-command local installation installs both; the official Marketplace would show two listings unless Nous approves a different combined packaging mechanism. Do **not** claim native one-click Marketplace installation of both components. A standalone developer installer can install both only after explicit user invocation.

## Install from GitHub

Minimum target: **Hermes v0.23.2**, whose released source declares the five required provider registries, `save_url_image`, the provider-profile extension hook and the dashboard plugin loader. Actual loading and end-to-end operation must still be validated in a real installation.

### Install directly from Hermes Desktop (GUI)

You can install the two packages **without cloning the repository or using a terminal**:

1. Open **Hermes Desktop** and navigate to **Capabilities → Plugins** (the section may be translated as **Capacidades → Plugins**).
2. Click **Install from Git** (or **Instalar a partir do Git**).
3. Paste this URL to install the **model provider** package:

   ```text
   https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git#model-provider
   ```

4. Repeat **Install from Git** and paste the URL of the **media/backend** package:

   ```text
   https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git#backend
   ```

5. Check both `omniroute-model` and `omniroute-media` in **Capabilities → Plugins**, enable them where required and rescan if necessary. For the UI extension, open **Settings → Plugins → OmniRoute** after it is detected and enabled.

These are **two separate installs**, not a single combined Marketplace entry. The `#model-provider` and `#backend` suffixes select different subdirectories of the same public Git repository. The URLs above follow the default `main` branch; pin a supported commit/ref if you need a reproducible version.

**Where the UI lives:** Hermes Desktop (native app) loads its Desktop plugins on the computer running the application. The browser-hosted **Hermes Webapp** loads Desktop plugins on the machine serving the Webapp. Installing agent-side Python packages on a remote host does not by itself install Desktop JavaScript onto a different native Desktop computer.

### Install with the developer script (alternative)

Clone the intended development branch (v0.4.0-beta.5) on the Hermes machine and invoke the installer:

```bash
git clone https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git
cd Hermes-OmniRoute-Integration
python3 scripts/install_local.py
```

The installer validates both manifests, resolves the exact commit checked out, and installs the two components from `https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git#model-provider` and `#backend` pinned with `--ref <full-commit-SHA>`. It does **not** use bare directory paths or temporary `file://` Git repositories. A Git checkout is required; running it from an extracted ZIP without `.git` fails with an actionable error. The installer does not automatically install the Desktop JavaScript portion on Windows.

Open the **OmniRoute** tab in the authenticated Hermes web dashboard. You can configure the URL, API key, the five model categories, provider-specific TTS voice, optional search/extract provider overrides, and explicitly activate OmniRoute for Hermes chat. Credentials are optional at installation; the tab remains available before you configure them. You can alternatively configure your Hermes profile's environment using Hermes's supported credential editor (not shell history):

- `OMNIROUTE_BASE_URL`: complete OpenAI-compatible API root, including `/v1` or `/api/v1`.
- `OMNIROUTE_API_KEY`: token authorized for that OmniRoute instance.

For chat, ensure Hermes's native model configuration is set to your active routing endpoint and model:

```bash
hermes config set model.provider omniroute
hermes config set model.base_url https://router.example/api/v1
hermes config set model.default your-model-id
```

**Important:** selecting a chat model does not change your current Hermes provider. Press **Activate OmniRoute as Hermes chat provider** on the same dashboard tab to explicitly set `model.provider`, `model.base_url`, and `model.default`. If OmniRoute is already the active provider, saving its chat model or endpoint updates the corresponding native keys. A Hermes reload may be necessary. Other model selectors save values to `OMNIROUTE_{IMAGE,VIDEO,TTS,STT}_MODEL`.

Example of backend selection in `~/.hermes/config.yaml` (choose only what your router supports):

```yaml
image_gen:
  provider: omniroute
video_gen:
  provider: omniroute
web:
  search_backend: omniroute
  extract_backend: omniroute
tts:
  provider: omniroute
stt:
  provider: omniroute
```

Optional environment variables, all editable in the Hermes dashboard: `OMNIROUTE_IMAGE_MODEL`, `OMNIROUTE_VIDEO_MODEL`, `OMNIROUTE_TTS_MODEL`, `OMNIROUTE_STT_MODEL`, `OMNIROUTE_TTS_VOICE`, `OMNIROUTE_SEARCH_PROVIDER`, `OMNIROUTE_FETCH_PROVIDER`, `OMNIROUTE_CHAT_MODEL` (dashboard preset only unless native provider active). No default model IDs are fabricated.


## Hermes Desktop settings (introduced in 0.4.0-beta.1)

The release now includes `backend/desktop/plugin.js`, a **native Desktop Settings → Plugins page** for `omniroute-media`. It uses the existing profile-scoped `backend/dashboard/plugin_api.py` through the official `ctx.rest` SDK; **no second credential store**, no direct OmniRoute HTTP calls from the desktop app, and no change to the working chat/media providers. It provides connection configuration, masked API key replacement, live discovery and saving of chat/image/video/TTS/STT models, TTS voice, search/extract overrides and explicit chat activation.

**For a native Hermes Desktop app connected to a remote server:** install the Desktop half on the computer running Hermes Desktop. Installing the backend on the remote Hermes server alone does not copy JavaScript to a separate Windows client. Use **Capabilities → Plugins → Install from Git** with the two URLs above, or run `scripts/install_desktop_local.ps1` on the Desktop computer if installing the JavaScript locally. On Windows the installer defaults to `%LOCALAPPDATA%\hermes\desktop-plugins`, not `%USERPROFILE%\.hermes`. For a different location, open the plugin folder from Hermes Desktop and pass its parent directory with `-HermesHome`. **For the browser-hosted Hermes Webapp**, the UI plugin is loaded from the Webapp server's installed plugins instead. Enable/rescan the Desktop plugin in **Capabilities → Plugins**, then open **Settings → Plugins → OmniRoute**.

Full directions, safety boundaries, prerequisites, diagnostics and rollback: [docs/DESKTOP.md](docs/DESKTOP.md). **Not yet runtime-tested on your actual Windows Desktop.**

## Compatibility with OmniRoute 3.8.53

The v0.4.0-beta.5 adapter is aligned against **OmniRoute tag v3.8.53**. In particular:

- Chat models are discovered from the complete API-key-authorized unified catalog using `GET /v1/models?prefix=alias&limit=200` and subsequent `after` cursors. Local classification preserves valid chat subtypes and combos and excludes specialized models. The dashboard no longer truncates at 1,000 entries. The client reduces the page size on oversized responses and fails explicitly on incomplete pagination; per-page and aggregate safety budgets remain. The native provider registers Hermes's `picker_catalog` hook and its base URL environment variable without storing profile credentials globally.
- Hermes Desktop initially displays 50 model families per provider; search and model visibility settings are Hermes-owned and are not changed by this plugin. Use the Hermes **Refresh models** action after a catalog change. The plugin's media catalog cache uses a 60-second successful-result TTL, isolated by endpoint and key fingerprint; failed results are not cached.
- Audio models use `type: audio` together with `subtype: speech` (TTS) or `subtype: transcription` (STT). This is shared with the dashboard selector.
- Image generation omits `size` when no pixel dimensions are advertised for that model, since some models reject any explicit size. An explicit caller-provided pixel `size` remains possible.
- Image editing uses JSON `images` with base64 data URLs, and enforces known provider-specific reference limits before forwarding. OmniRoute makes the final decision for combos and provider capabilities.
- Image-to-video for xAI uses `image`; other video routes use `image_url`. Video duration is only limited locally by validated model metadata (or a broad operational sanity bound), never a universal ten-second limit. The Hermes dynamic tool schema receives per-model metadata when published by OmniRoute.
- Key-scoped API rejections remain enforced by OmniRoute. The client preserves status and safe machine-readable error codes, without echoing upstream messages or credentials.

These are **source-contract and offline-test** validations, not a claim of live interoperability with every configured upstream model. Runtime behavior can depend on the OmniRoute instance's keys, providers, flags, and model availability.

## Compatibility caveats

An OmniRoute deployment may support only a subset of these endpoints, and availability depends on its configured upstream providers and credentials. Chat streaming, tool calls and model-dependent vision are delegated to the **native Hermes OpenAI-compatible chat implementation**, not independently reimplemented. OmniRoute supports multimodal requests where the selected upstream model supports them. OmniRoute 3.8.53 exposes `GET /v1/videos/generations` for video model discovery. Older deployments or unconfigured providers may still return an empty list; setting an explicit model ID is supported. Some video capabilities, sizes and durations are per-model and may not be supported by your router; first test with a small request. OmniRoute enforces model/endpoint permission and API-key connection scopes; typed error codes (when safe) and HTTP status are retained. Image editing on OmniRoute 3.8.53 accepts JSON `images: [{image_url: "data:image/...;base64,..."}]` and multipart input. The plugin uses JSON data URLs; model-specific reference limits apply (commonly one, up to sixteen for certain Codex GPT Image models). Live compatibility remains unverified.

The dashboard uses Hermes's extension API and profile-scoped `get_secret_str` plus its native config and credential persistence mechanisms. TTS does not pretend every upstream supports OpenAI stock voices: configure the voice required by your model in the dashboard, if needed. Generated TTS files use the actual MIME/magic format rather than falsely using the requested extension. STT multipart fields and filenames are validated against CR/LF and other control characters. An authenticated dashboard is required. Plain HTTP is accepted only for local or private-network IPs and selected local hostname suffixes (`.home.arpa`, `.local`, `.internal`, localhost). Public endpoints must use HTTPS. HTTP provides no transport confidentiality even on a private LAN.

## Security disclosures (Marketplace policy)

- Makes outbound requests to **only the configured OmniRoute API base** for inference, model catalogs and media/search operations. An operator can point to a third-party HTTPS domain and send data to it; do not use a provider you do not trust.
- Sends prompts, text to be synthesized, audio recordings, source URLs and optionally image bytes to the configured server. The server may forward those inputs to its own upstream providers.
- For video reference inputs, only public HTTPS URLs without embedded credentials are accepted (subject to the OmniRoute server's own outbound URL policy). For image editing, it can read explicitly provided local image files (up to 20 MiB), or request a URL through Hermes’s safe image download helper, and send the bytes to OmniRoute. For STT, reads explicitly provided audio files (up to 25 MiB). No general filesystem indexing.
- Generated media can be stored in Hermes's normal media cache; TTS outputs are written to the requested output path.
- API key and endpoint are saved through Hermes's own credential/configuration APIs; the dashboard never reveals the key to browser code.
- On outbound API calls, redirects are refused, preventing a bearer token from being forwarded to a different host via a 30x response. Basic credentials embedded in API URL are rejected.
- A standalone **developer-initiated** installer runs the `hermes plugins install` subprocess twice. The installed catalog plugins themselves spawn no shell processes and contain no updater.
- No analytics, telemetry, background daemon, browser scraping, or automatic approval bypasses.

## Development and publication

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q backend model-provider
node --check backend/dashboard/dist/index.js
hermes plugins validate ./model-provider --install-deps
hermes plugins validate ./backend --install-deps
```

The first three checks can be run offline. GitHub Actions also invokes the official `NousResearch/hermes-agent/.github/actions/plugin-validate@v0.23.2` composite action for both components; the actual hosted CI result is pending publication. The **last two must run in a real, compatible Hermes installation**, and real OmniRoute integration needs configured credentials and available models. None of these have yet been certified as official or submitted to the catalog.

For publication, create a **public GitHub repository**, replace the placeholders in `catalog/*.yaml.template` with its URL, maintainer name and exact 40-character commit SHA, then submit two files under `NousResearch/hermes-agent/plugin-catalog/` as a PR. Exact SHA pinning and human review are mandatory. The official catalog may request a different packaging arrangement. This candidate declares `requires_hermes: ">=0.23.2"`, a conservative API-level floor checked against the v0.23.2 released source. **Release compatibility remains provisional until the official validator and runtime tests pass**; adjust the floor if those tests find a higher requirement.

See [official submission rules](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/plugins/catalog-submission.md).

## License and credit

MIT license. Original code created from public API contracts and official Hermes plugin extension points. 

### Catalog maintenance and diagnostics

`backend/catalog_discovery.py` is the sole maintained source of catalog pagination, classification, deduplication and telemetry. The independent `model-provider/` package contains a generated, byte-identical copy, because Hermes installs each subdirectory separately. Do not edit the generated copy; run `python scripts/sync_catalog.py` and commit the result. CI verifies the copy.

The plugin's `GET /models?kind=chat` dashboard API includes an additive `diagnostics` object, and the Desktop/Dashboard Discover action displays the metrics. Native chat and backend media also emit structured INFO logs (WARNING on discovery failure). Fields: `source` (api/cache), `status`, `received`, `classified` by modality, `combos`, `other`, `duplicates_removed`, `delivered`, `pages`, `requests`, `duration_ms`, and sanitized `error`. Counts describe the queried endpoint, not the entire OmniRoute deployment; classifications can overlap, and a combo can also count as chat. Duplicate counts apply to the selected modality. Delivered means IDs emitted by the plugin, not the number Hermes chooses to display. Cache hits show zero network pages/requests; native Hermes's separate cache remains manually refreshable. No keys, base URLs, model IDs or raw upstream messages are logged in these metrics.

Before committing release changes, stage all new source files and run `python scripts/release_checksums.py` in an LF checkout. Verify with `python scripts/release_checksums.py --check`. The SHA-256 manifest covers every tracked file except itself; CI checks it.

### Route identity in model pickers

On Desktop versions exporting `MODEL_MENU_ROW_AREA`, the plugin adds the OmniRoute routing prefix as a badge to native picker rows, leaving inference IDs and other providers unchanged. Bare IDs are marked `Sem prefixo` rather than guessing their owner. The plugin settings pickers use `route_label` (the full routing ID, or a display-only owner prefix for bare IDs); `/models` also returns `owned_by` and `root` when available. No network call is made by the native row decorator.
