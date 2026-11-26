"""Public provider catalogs. No inference, private keys, account data or external redirects."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib import request, parse
import json
import os
import tempfile
import time

SOURCES = ("nvidia", "openrouter", "xkiro", "llm7")
ACCESS = ("free", "free_quota", "free_credits", "trial_credits", "free_preview",
          "subscription", "paid", "local", "unknown_pricing")
FREE = frozenset(ACCESS[:5])
MODALITIES = ("text", "image", "audio", "video", "document", "embedding", "rerank")
LIFECYCLE = ("stable", "preview", "experimental", "deprecated", "legacy")
PRIVACY = ("open_weights", "open_source", "prompt_training", "no_prompt_training",
           "commercial_use", "development_only")
EXTRA_CAPS = ("parallel_tool_calling", "streaming", "coding", "fim")
MAX_BYTES = 12 * 1024 * 1024

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def public_json(url):
    parsed = parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc not in {
        "api.ngc.nvidia.com", "openrouter.ai", "api.xkiro.com", "api.llm7.io"
    }:
        raise ValueError("Untrusted public source")
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    req = request.Request(url, headers={"Accept": "application/json",
                           "User-Agent": "Hermes-OmniRoute-Integration/0.5"})
    with opener.open(req, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Catalog too large")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid catalog")
    return data

def record(x):
    return x if isinstance(x, dict) else {}

def array(x):
    return x if isinstance(x, list) else []

def safe_id(x):
    return isinstance(x, str) and 0 < len(x) <= 256 and not any(ord(c) < 33 or ord(c) == 127 for c in x)

def positive_int(x):
    return x if type(x) is int and 0 < x <= 10**14 else None

def modalities(values):
    aliases = {"text":"text", "image":"image", "audio":"audio", "video":"video",
               "document":"document", "file":"document", "pdf":"document",
               "embedding":"embedding", "rerank":"rerank"}
    return sorted({aliases[v.lower()] for v in array(values)
                   if isinstance(v, str) and v.lower() in aliases})

def price(p, k):
    try:
        v = Decimal(str(p[k]))
        return v if v.is_finite() and v >= 0 else None
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return None

def _ref(spec, obj):
    for _ in range(8):
        if not isinstance(obj, dict) or "$ref" not in obj:
            return record(obj)
        ref = obj["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return {}
        obj = spec
        for part in ref[2:].split("/"):
            obj = record(obj).get(part.replace("~1", "/").replace("~0", "~"))
    return {}

def nvidia_ids(spec):
    ids = set()
    for ops in record(spec.get("paths")).values():
        body = _ref(spec, record(record(ops).get("post")).get("requestBody"))
        for media in record(body.get("content")).values():
            schema = _ref(spec, record(media).get("schema"))
            model = _ref(spec, record(schema.get("properties")).get("model"))
            vals = [model.get("default"), model.get("const")] + array(model.get("enum"))
            ids.update(v for v in vals if safe_id(v))
    # Unique declared request ID only: no titles, basename matching or suffix stripping.
    return ids if len(ids) == 1 else set()

def _nvidia_detail(row):
    name = row.get("name")
    if not safe_id(name) or "/" in name or name in {".", ".."}:
        raise ValueError("Invalid artifact")
    url = "https://api.ngc.nvidia.com/v2/endpoints/qc69jvmznzxy/" + parse.quote(name, safe="") + "/spec"
    data = public_json(url)
    spec, attrs = data.get("openAPISpec"), data.get("attributes")
    spec = json.loads(spec) if isinstance(spec, str) else spec
    attrs = json.loads(attrs) if isinstance(attrs, str) else attrs
    # Several public NGC resources deliberately have no OpenAPI spec. They
    # are unresolved, not a transport failure. Never guess a model ID.
    if spec is None:
        return []
    if not isinstance(spec, dict):
        raise ValueError("Invalid OpenAPI specification")
    attrs = record(attrs)
    props, caps = record(attrs.get("specifications")), record(attrs.get("modelCapability"))
    kind = {"/v1/chat/completions":"chat", "/v1/embeddings":"embedding",
            "/v1/reranking":"rerank", "/v1/images/generations":"image"}.get(data.get("nvcfInferencePath"))
    return [{"model_id":m,"access":["free_preview"],"lifecycle":"preview","kind":kind,
             "context_length":positive_int(props.get("contextLength")),
             "parameter_count":positive_int(props.get("parameters")),
             "input":modalities(props.get("inputModalities")), "output":modalities(props.get("outputModalities")),
             "capabilities":[k for a,k in (("functionCalling","tool_calling"),
               ("structuredOutput","structured_output"),("reasoning","reasoning")) if caps.get(a) is True],
             "source":url} for m in nvidia_ids(spec)]

def nvidia():
    rows = {}
    seen_resources = set()
    expected = None
    for page in range(10):
        q = parse.urlencode({"q":json.dumps({"query":"","page":page,"pageSize":100})})
        data = public_json("https://api.ngc.nvidia.com/v2/search/catalog/resources/ENDPOINT?" + q)
        total = data.get("resultPageTotal")
        if type(total) is not int or not 1 <= total <= 10 or (expected is not None and total != expected):
            raise ValueError("Invalid NVIDIA pagination")
        expected = total
        if not isinstance(data.get("results"), list):
            raise ValueError("Invalid NVIDIA results")
        for group in data["results"]:
            if not isinstance(record(group).get("resources"), list):
                raise ValueError("Invalid NVIDIA group")
            for row in group["resources"]:
                row = record(row)
                if safe_id(row.get("resourceId")):
                    seen_resources.add(row["resourceId"])
                if row.get("orgName") == "qc69jvmznzxy" and row.get("isPublic") is True and safe_id(row.get("resourceId")) and any(
                    "nim_type_preview" in array(record(l).get("unresolvedValues")) for l in array(row.get("labels"))):
                    rows[row["resourceId"]] = row
        if page + 1 >= total:
            break
    # Search responses can include repeated scored/grouped resources.
    if type(data.get("resultTotal")) is not int or len(seen_resources) < data["resultTotal"]:
        raise ValueError("Incomplete NVIDIA catalog")
    if not rows or len(rows) > 120:
        raise ValueError("Empty or excessive NVIDIA offers")
    # AVAILABLE is deliberately not interpreted as account health.
    def detail(row):
        try:
            return _nvidia_detail(row), False
        except Exception:
            return [], True
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(detail, rows.values()))
    entries = [entry for group, failed in results for entry in group]
    failures = sum(failed for group, failed in results)
    unresolved = sum(not group and not failed for group, failed in results)
    if not entries:
        raise ValueError("No NVIDIA IDs resolved")
    return entries, failures, unresolved

def _rows(url):
    data = public_json(url)
    rows = data.get("data")
    if not isinstance(rows, list) or not rows or len(rows) > 10000:
        raise ValueError("Invalid public catalog")
    return [r for r in rows if isinstance(r, dict) and safe_id(r.get("id"))]

def openrouter():
    url = "https://openrouter.ai/api/v1/models"
    result = []
    for r in _rows(url):
        m, p = r["id"], record(r.get("pricing"))
        a, b = price(p,"prompt"), price(p,"completion")
        access = ["free_quota"] if m.endswith(":free") and a == 0 and b == 0 else []
        if not access and any(v is not None and v > 0 for v in (a,b)):
            access = ["paid"]
        arch, params = record(r.get("architecture")), array(r.get("supported_parameters"))
        result.append({"model_id":m,"access":access,"source":url,
            "context_length":positive_int(r.get("context_length")),
            "input":modalities(arch.get("input_modalities")),"output":modalities(arch.get("output_modalities")),
            "capabilities":[k for a,k in (("tools","tool_calling"),("reasoning","reasoning"),
                ("structured_outputs","structured_output")) if a in params],
            "pricing":{"input":str(a) if a is not None else None,"output":str(b) if b is not None else None,
                       "currency":"USD","unit":"token"}})
    return result, 0, 0

def xkiro():
    url = "https://api.xkiro.com/v1/models?modality=all"
    result = []
    for r in _rows(url):
        tier = r.get("access_tier")
        # Paid and premium require a plan or funded balance; neither proves
        # that a subscription actually includes the route for this account.
        access = {"free":["free_quota"],"paid":["paid"],"premium":["paid"]}.get(tier,[])
        caps = record(r.get("capabilities"))
        kind = {"chat":"chat","image":"image","audio":"audio","embedding":"embedding",
                "video":"video"}.get(r.get("modality"))
        inputs = ["text"] if kind == "chat" else []
        if caps.get("vision") is True and kind == "chat": inputs.append("image")
        result.append({"model_id":r["id"],"access":access,"source":url,"kind":kind,
                       "input":inputs,"output":["text"] if kind=="chat" else [],
                       "capabilities":[k for a,k in (("vision","vision"),("tools","tool_calling"),("reasoning","reasoning")) if caps.get(a) is True],
                       "context_length":positive_int(r.get("context_length"))})
    return result, 0, 0

def llm7():
    url = "https://api.llm7.io/v1/models"
    result = []
    for r in _rows(url):
        # The turbo tier is a limited offer, not a universal zero-price guarantee.
        access = ["free_quota"] if r.get("tier") == "turbo" and r.get("usage_based_only") is False else (
            ["paid"] if r.get("usage_based_only") is True else [])
        caps = [k for field,k in (("reasoning","reasoning"),("tools_calling","tool_calling"),
                 ("stream","streaming")) if r.get(field) is True]
        mod = record(r.get("modalities"))
        kind = {"chat":"chat","image":"image","audio_to_text":"audio"}.get(r.get("model_type"))
        context = r.get("context_window")
        result.append({"model_id":r["id"],"access":access,"source":url,"kind":kind,
                       "context_length":positive_int(record(context).get("tokens") if isinstance(context,dict) else context),
                       "input":modalities(mod.get("input")),"output":modalities(mod.get("output")),"capabilities":caps})
    return result, 0, 0

ADAPTERS = {"nvidia":nvidia,"openrouter":openrouter,"xkiro":xkiro,"llm7":llm7}

def _cached(home, source, ttl):
    path = Path(home) / "plugin-data" / "omniroute-media" / "discovery" / (source+".json")
    now = time.time()
    try:
        with path.open("rb") as f:
            payload = f.read(MAX_BYTES+1)
        if len(payload) > MAX_BYTES:
            raise ValueError("Cache too large")
        data = json.loads(payload)
        if (data.get("schema") == 1 and data.get("source") == source and
                0 <= now - data["fetched_at"] < ttl and isinstance(data.get("entries"),list)):
            return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    entries, failures, unresolved = ADAPTERS[source]()
    data = {"schema":1,"source":source,"fetched_at":now,"entries":entries,
            "failures":failures,"unresolved":unresolved}
    # Partial snapshots are not cached; do not extend stale positive free claims.
    if not failures:
        payload = json.dumps(data,allow_nan=False,separators=(",",":")).encode()
        if len(payload) > MAX_BYTES:
            raise ValueError("Cache too large")
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp = tempfile.mkstemp(dir=path.parent,prefix=".catalog-")
        try:
            with os.fdopen(fd,"wb") as f:
                f.write(payload); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return data

def collect(home, sources, owners, ttl):
    selected = [s for s in SOURCES if s in sources and s in owners]
    def load(source):
        try:
            d = _cached(home,source,ttl)
            return source,d
        except Exception:
            return source,None
    index, states = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for source,d in pool.map(load,selected):
            if not d:
                states[source] = {"status":"unavailable"}
                continue
            entries = d["entries"]
            states[source] = {"status":"partial" if d["failures"] else "ok",
                "fetched_at":d["fetched_at"],"count":len(entries),"unresolved":d["unresolved"],
                "failures":d["failures"]}
            for entry in entries:
                m = record(entry).get("model_id")
                if safe_id(m):
                    k = (source,m)
                    if k in index and index[k] != dict(entry,fetched_at=d["fetched_at"]):
                        # Conflicting duplicate identities cannot be positively classified.
                        index[k] = {}
                    else:
                        index[k] = dict(entry,fetched_at=d["fetched_at"])
    return index,states

NATIVE_ACCESS = {"recurring-daily":"free_quota","recurring-monthly":"free_quota",
                 "recurring-uncapped":"free","recurring-credit":"free_credits",
                 "one-time-initial":"trial_credits","keyless":"free"}

def quota_status(provider, access, accounts):
    # Only windows whose documented names refer to this specific free tier.
    if "local" in access:
        return "not_applicable"
    windows = {"openrouter":("free_daily","free_rpm"),"xkiro":("free_daily",)}.get(provider)
    if not windows or "free_quota" not in access:
        return "unknown"
    entries = [e for e in array(accounts) if record(e).get("provider") == provider]
    outcomes = []
    for e in entries:
        if e.get("stale") or e.get("available") is False:
            outcomes.append("unknown"); continue
        from datetime import datetime, timezone
        try:
            age = (datetime.now(timezone.utc)-datetime.fromisoformat(e["fetchedAt"].replace("Z","+00:00"))).total_seconds()
            if not 0 <= age <= 300:
                raise ValueError
        except (KeyError, ValueError, TypeError, AttributeError):
            outcomes.append("unknown"); continue
        values = [record(record(e.get("quotas")).get(w)).get("remainingPercentage") for w in windows]
        if any(type(v) in (float,int) and v == 0 for v in values):
            outcomes.append("exhausted")
        elif all(type(v) in (float,int) and 0 < v <= 100 for v in values):
            outcomes.append("confirmed")
        else:
            outcomes.append("unknown")
    if "confirmed" in outcomes:
        return "confirmed"
    return "exhausted" if outcomes and all(x=="exhausted" for x in outcomes) else "unknown"
