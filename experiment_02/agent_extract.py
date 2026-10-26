#!/usr/bin/env python3
"""Agentic extraction: the model explores the repository itself with read-only
tools (list_dir, find, grep, read_file), records services and inbound endpoints
as it finds them (record) and ends with submit.  Every recorded entry is
validated against the source; accepted entries are kept, rejected ones go back
to the model with the reason, so a long result never has to fit into one reply.

The output extends the Appendix A schema of experiment_01 with services, so
experiment_01/evaluate.py scores both workflows the same way.

Tool calls use Spark-X2.5's text format (LM Studio has no parser for it):
    <tool_call>name<arg_key>k</arg_key><arg_value>v</arg_value></tool_call>
or, with --native-tools, the OpenAI tools API.

    python agent_extract.py --repo <checkout> --system-name movie --effort none
"""
import argparse, fnmatch, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Without git, every directory below is skipped; in a git checkout the tracked
# files decide, and only vendored dependencies are dropped from them.
VENDORED = {"node_modules", "vendor"}
SKIP_DIRS = VENDORED | {".git", "target", "build", "dist", "bin", "obj", ".idea", ".vscode",
                        ".mvn", ".gradle", "__pycache__", ".venv", "venv", ".tox", ".next"}
MAX_OUT = 6000          # chars of one tool result shown to the model
MAX_GREP_BYTES = 1_000_000
CTX_CHARS = 150_000     # default prompt budget in chars (~40k tokens), below LM Studio's 64k context
FIT_TARGET = 0.6        # once over budget, elide down to this share of it, so the prefix stays cacheable
KEEP_RECENT = 8         # tool results always kept verbatim; older ones are elided first
LONG_CALL = 2000        # chars of an earlier call (a record payload) above which fit() shortens it
SLACK = 3               # evidence may sit this many lines around the cited line
VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "ANY"}
INLINE = {"(inline)", "(anonymous)"}
PRICES = {              # USD per 1M tokens (input, output, cached input or None), list price
    "gemini-2.5-flash-lite": (0.10, 0.40, None),
    "gemini-3.5-flash-lite": (0.10, 0.40, None),
    "openai/gpt-oss-120b":   (0.15, 0.60, None),   # Groq
    "GLM-5.3-Flash":         (0.15, 0.50, 0.03),   # Wafer
    "GLM-5.3":               (0.60, 2.00, None),   # Wafer
    "DeepSeek-V4.1-Flash-1017": (0.15, 0.60, 0.003),   # Wafer
}


def list_price(model, in_tok, out_tok, cached=0):
    """List-price cost of a run, or None for a local model with no price.  Cached
    input is billed at the cache rate where we know it, else at the full rate."""
    if model not in PRICES:
        return None
    pin, pout, pcache = PRICES[model]
    pcache = pin if pcache is None else pcache
    return round((in_tok - cached) / 1e6 * pin + cached / 1e6 * pcache + out_tok / 1e6 * pout, 4)


TOOLS = [
    {"name": "list_dir", "description": "List a directory of the repository. "
     "Directories end with /.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "repo-relative, e.g. / or /user-service/src"}},
         "required": ["path"]}},
    {"name": "grep", "description": "Search file contents with a Python regex. "
     "Returns path:line: text, at most 60 hits.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"},
         "path": {"type": "string", "description": "directory to search, default /"}},
         "required": ["pattern"]}},
    {"name": "read_file", "description": "Read a file with line numbers, at most 300 lines.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"},
         "start": {"type": "integer", "description": "first line, default 1"}},
         "required": ["path"]}},
    {"name": "find", "description": "Find files by name with a glob, e.g. *Controller.java, "
     "*.go or Dockerfile. Returns repo-relative paths, at most 100.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"},
         "path": {"type": "string", "description": "directory to search, default /"}},
         "required": ["pattern"]}},
    {"name": "record", "description": "Record services and/or endpoints you have evidence for. "
     "Each entry is checked against the source; accepted ones are kept, rejected ones come "
     "back with the reason.",
     "parameters": {"type": "object", "properties": {
         "json": {"type": "string", "description": "a JSON document with services and/or files"}},
         "required": ["json"]}},
    {"name": "submit", "description": "Finish. Optionally records a last JSON document first.",
     "parameters": {"type": "object", "properties": {
         "json": {"type": "string", "description": "optional last JSON document"}}}},
]

TASK = """You are extracting the architecture of a microservice system from its source code.
{mount} Explore it with the tools, record what you find as you go, then call submit.

Find:
1. Every service: a separately deployable application with its own entry point (a main class
   or main package, a server start file, a Dockerfile, a deployable module of the build).
   A library module is not a service: put its directory into the dirs of the service(s) that ship it.
2. Every inbound HTTP endpoint the services serve, in any language or framework (e.g. Spring or
   JAX-RS annotations, Express/Fastify/NestJS routes, Flask/FastAPI/Django views,
   Gin/Echo/net/http handlers, ASP.NET controllers and minimal APIs).

Rules:
- Do not invent anything. Use only evidence you have read in the code.
- Outbound calls to other services (Feign clients, RestTemplate/WebClient, axios/fetch,
  requests/httpx, http.Client, HttpClient) are NOT endpoints - do not record them.
- Give the full route: join every prefix (class-level mapping, router mount, global prefix)
  with the route itself.
- A route declared on an interface or base class: cite the file that declares it and add
  "implementedBy" with the class that implements it.
- Skip tests (src/test, test/, tests/, *_test.go, *.spec.ts, ...).
- Prefer grep and find over listing directories.
- Record as you go - after each service or a few files - not one big document at the end.
  Accepted entries are kept; fix rejected ones and record them again. Then call submit.

record takes a JSON document; both parts are optional:
{
  "services": [{"name": "user-service", "dirs": ["/user-service"]}],
  "files": [
    {"path": "/user-service/src/main/java/com/example/UserController.java",
     "service": "user-service",
     "endpoints": [
       {"className": "UserController", "methodName": "getUser", "httpMethod": "GET",
        "path": "/user/{userId}", "line": 27, "evidence": "@GetMapping(\\"/{userId}\\")",
        "framework": "Spring", "confidence": "high"}]}]
}
- Every file belongs to a recorded service and lies under one of its dirs.
- line: the line of the route declaration. evidence: that declaration copied verbatim.
- className is empty for a plain function; methodName is the handler, or "(inline)".
- httpMethod is one of GET, POST, PUT, DELETE, PATCH, ANY. confidence is high, medium or low."""

TEXT_PROTOCOL = """

## Tools
You have access to the following functions:
<tools>
{tools}
</tools>

Call exactly ONE tool per message, in this format, and then stop:
<tool_call>grep<arg_key>pattern</arg_key><arg_value>@RestController</arg_value></tool_call>"""

CALL_RE = re.compile(r"<tool_call>(.*?)(?:</tool_call>|$)", re.S)
ARG_RE = re.compile(r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)(?:</arg_value>|$)", re.S)
SHORT_ARG_RE = re.compile(r"<arg_(?!key>|value>)(\w+)>(.*?)</arg_\1>", re.S)


# --------------------------------------------------------------------- tools --
def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          check=True).stdout.decode("utf-8")


def source_files(root):
    """Repo-relative paths of the files the model may see."""
    try:
        files = [f for f in git(root, "ls-files", "-z").split("\0") if f]
        skip = VENDORED
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        files, skip = [], SKIP_DIRS
        for d, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            files += [(Path(d) / f).relative_to(root).as_posix() for f in fs]
    return [f for f in files if not skip.intersection(f.split("/")[:-1]) and (root / f).is_file()]


def checkout_state(root):
    """Commit and dirty flag of a checkout, or None without git."""
    try:
        return {"commit": git(root, "rev-parse", "HEAD").strip(),
                "dirty": bool(git(root, "status", "--porcelain").strip())}
    except (OSError, subprocess.CalledProcessError):
        return None


def text_of(data):
    """Decode a source file; None for binary.  Non-UTF-8 text (cp1250, latin-1)
    is decoded with replacement, so its ASCII code stays searchable."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8-sig", errors="replace")


class Repo:
    """One checkout, or several mounted side by side at /<name>.  Paths shown to
    the model are virtual: /dir/file in one checkout, /<name>/dir/file in several."""
    def __init__(self, roots):
        self.roots = {}
        for r in roots:
            r = Path(r).resolve()
            if r.name in self.roots:
                sys.exit(f"two repositories named {r.name}")
            self.roots[r.name] = r
        self.multi = len(self.roots) > 1
        self.paths = sorted((f"/{name}" if self.multi else "") + "/" + f
                            for name, r in self.roots.items() for f in source_files(r))

    @staticmethod
    def vnorm(path):
        """'/a/b' for a directory or file path, '' for the root."""
        segs = [s for s in str(path or "/").replace("\\", "/").split("/") if s and s != "."]
        return "/" + "/".join(segs) if segs else ""

    def resolve(self, vpath):
        segs = [s for s in self.vnorm(vpath).split("/") if s]
        if self.multi:
            if not segs or segs[0] not in self.roots:
                raise ValueError(f"no repository {segs[0] if segs else '/'}; "
                                 f"the repositories are {', '.join('/' + n for n in self.roots)}")
            root, segs = self.roots[segs[0]], segs[1:]
        else:
            root = next(iter(self.roots.values()))
        p = root.joinpath(*segs).resolve()
        if p != root and root not in p.parents:
            raise ValueError("path outside the repository")
        return p

    def under(self, path):
        d = self.vnorm(path)
        return [p for p in self.paths if not d or p == d or p.startswith(d + "/")]

    def is_dir(self, path):
        d = self.vnorm(path)
        return not d or any(p.startswith(d + "/") for p in self.paths)

    def source(self, vpath):
        """Text of a source file, or None."""
        try:
            p = self.resolve(vpath)
            return text_of(p.read_bytes()) if p.is_file() else None
        except (ValueError, OSError):
            return None

    def list_dir(self, path="/"):
        d = self.vnorm(path)
        kids = set()
        for p in self.under(d):
            rest = p[len(d) + 1:]
            if rest:
                kids.add(rest.split("/")[0] + ("/" if "/" in rest else ""))
        if not kids:
            return f"[ERROR] not a directory with source files: {path}"
        return "\n".join(sorted(kids))

    def grep(self, pattern, path="/"):
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"[ERROR] bad regex: {e}"
        hits, big = [], []
        for vp in self.under(path):
            try:
                p = self.resolve(vp)
                if p.stat().st_size > MAX_GREP_BYTES:
                    big.append(vp)
                    continue
                text = text_of(p.read_bytes())
            except (ValueError, OSError):
                continue
            for i, line in enumerate((text or "").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{vp}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 60:
                        return "\n".join(hits) + "\n[... more hits, narrow the pattern or path]"
        out = "\n".join(hits) or "(no matches)"
        if big:
            out += (f"\n[not searched: {len(big)} files over {MAX_GREP_BYTES // 1_000_000} MB: "
                    + ", ".join(big[:5]) + (" ..." if len(big) > 5 else "")
                    + " - read_file them if they matter]")
        return out

    def find(self, pattern, path="/"):
        """Glob on the file name, or on the path below `path` when the pattern has a '/'."""
        d = self.vnorm(path)
        hits = [p for p in self.under(d) if fnmatch.fnmatch(p.rsplit("/", 1)[-1], pattern)
                or fnmatch.fnmatch(p[len(d) + 1:], pattern.lstrip("/"))]
        if len(hits) > 100:
            return "\n".join(hits[:100]) + "\n[... more files, narrow the pattern or path]"
        return "\n".join(hits) or "(no files)"

    def read_file(self, path, start=1):
        text = self.source(path)
        if text is None:
            return f"[ERROR] not a readable text file: {path}"
        lines = text.splitlines()
        s = max(int(start or 1), 1)
        body = "\n".join(f"{i}: {l}" for i, l in enumerate(lines[s - 1:s + 299], s))
        if s + 299 < len(lines):
            body += f"\n[... {len(lines)} lines total, read again with start={s + 300}]"
        return body


# ---------------------------------------------------------------- validation --
VERB_RE = re.compile(r"@(get|post|put|delete|patch)mapping\b|requestmethod\.(get|post|put|delete|patch)\b"
                     r"|@(get|post|put|delete|patch)\b|\[http(get|post|put|delete|patch)\b"
                     r"|\bmap(get|post|put|delete|patch)\b|\.(get|post|put|delete|patch)\s*\(", re.I)
LIT_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|`([^`]*)`')


def squash(s):
    return re.sub(r"\s+", " ", s).strip()


def norm_route(p):
    """A route reduced for comparing suffixes: placeholders to {}, no query,
    no trailing slash, lowercase."""
    p = re.sub(r"\s+", "", p)                             # evidence is compared without spaces too
    p = re.sub(r"\$\{[^}:]*:([^}]*)\}", r"\1", p)        # ${prop:default} -> default
    p = re.sub(r"\$?\{[^}]*\}|<[^>]*>", "{}", p)          # {id}, ${id}, <int:id>
    p = re.sub(r"(?<=/):[^/]+", "{}", p.split("?")[0])    # :id
    return re.sub(r"/+", "/", p).rstrip("/").lower()


def verbs_in(evidence):
    return {next(g for g in m.groups() if g).upper() for m in VERB_RE.finditer(evidence)}


def route_literals(evidence):
    """Normalized string literals of the evidence that look like a route."""
    out = set()
    for m in LIT_RE.finditer(evidence):
        s = next(g for g in m.groups() if g is not None)
        s = re.sub(r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+", "", s)   # Go 1.22 "GET /x"
        if s.startswith(("/", "{")) and norm_route(s):
            out.add(norm_route(s))
    return out


def check_endpoint(e, src):
    """None if the endpoint is backed by the source, else the reason it is not."""
    if not isinstance(e, dict):
        return "must be an object"
    for k in ("methodName", "httpMethod", "path", "evidence"):
        if not isinstance(e.get(k), str) or not e[k].strip():
            return f"missing {k}"
    verb = e["httpMethod"].upper()
    if verb not in VERBS:
        return f"httpMethod must be one of {sorted(VERBS)}"
    if not e["path"].startswith("/"):
        return "path must be the full route, starting with /"
    cls = e.get("className") or ""
    if not isinstance(cls, str) or (cls and cls not in src):
        return f"class {cls} does not appear in this file"
    if e["methodName"] not in INLINE and e["methodName"] not in src:
        return f"method {e['methodName']} does not appear in this file"
    lines = src.splitlines()
    try:
        line = int(e.get("line"))
    except (TypeError, ValueError):
        return "missing line (the line number of the route declaration)"
    if not 1 <= line <= len(lines):
        return f"line {line} is outside the file ({len(lines)} lines)"
    lo, hi = max(line - 1 - SLACK, 0), min(line + SLACK, len(lines))
    window = squash(" ".join(lines[lo:hi]))
    evidence = re.sub(r"(?m)^\s*\d+: ", "", e["evidence"])     # line numbers copied from read_file
    pieces = [squash(p) for p in re.split(r"\.\.\.|…", evidence) if squash(p)]
    flat = lambda s: re.sub(r"\s+", "", s)       # value="/x" and value = "/x" are the same code
    if not pieces or any(flat(p) not in flat(window) for p in pieces):
        return (f"evidence is not at line {line}; copy the route declaration verbatim. "
                f"Lines {lo + 1}-{hi} read: {window[:300]}")
    found = verbs_in(evidence)
    if found and verb != "ANY" and verb not in found:
        return f"httpMethod is {verb} but the evidence declares {'/'.join(sorted(found))}"
    lits = route_literals(evidence)
    if lits and not any(norm_route(e["path"]).endswith(l) for l in lits):
        return (f"path {e['path']} does not end with the route in the evidence "
                f"({', '.join(sorted(lits))}); join the prefixes with it")
    return None


def load_payload(payload):
    if isinstance(payload, dict):
        return payload, None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(payload or "").strip())
    try:
        doc = json.loads(text)
    except Exception as e:
        # say what belongs there: small models echo the previous tool result instead
        return None, (f"not valid JSON ({e}). The json argument must be the document itself, "
                      '{"services": [...]} and/or {"files": [...]} as in the task, not a summary '
                      f"or a tool result. You sent: {text[:80]!r}")
    if isinstance(doc, list) and doc and all(isinstance(f, dict) and "path" in f for f in doc):
        doc = {"files": doc}            # a bare list of files is unambiguous
    if not isinstance(doc, dict):
        return None, 'must be a JSON object with "services" and/or "files"'
    return doc, None


def prefix_variant(a, b):
    """b is endpoint a again with a prefix added or dropped: same verb and declaration,
    and one path ends with the other.  A declaration that lists several routes may
    give several endpoints."""
    if a["httpMethod"] != b["httpMethod"] or abs(a["line"] - b["line"]) > SLACK             or len(route_literals(b["evidence"])) > 1:
        return False
    pa, pb = norm_route(a["path"]), norm_route(b["path"])
    return pa != pb and (pa.endswith(pb) and pb[:1] in ("/", "") or pb.endswith(pa) and pa[:1] in ("/", ""))


class Recorded:
    """The result so far.  record() keeps every entry the source backs."""
    def __init__(self, repo, system):
        self.repo, self.system = repo, system
        self.services, self.files, self.keys = {}, {}, set()

    def doc(self):
        return {"system": self.system, "services": list(self.services.values()),
                "files": list(self.files.values())}

    def n_endpoints(self):
        return sum(len(f["endpoints"]) for f in self.files.values())

    def add_service(self, s):
        if not isinstance(s, dict) or not isinstance(s.get("name"), str) or not s["name"].strip():
            return 'needs a "name"'
        dirs = s.get("dirs") or s.get("dir") or []
        dirs = [dirs] if isinstance(dirs, str) else dirs
        if not dirs or not all(isinstance(d, str) for d in dirs):
            return 'needs "dirs", a list of directories'
        bad = [d for d in dirs if not self.repo.is_dir(d)]
        if bad:
            return f"not a directory with source files: {', '.join(bad)}"
        old = self.services.setdefault(s["name"], {"name": s["name"], "dirs": []})
        old["dirs"] += [Repo.vnorm(d) or "/" for d in dirs if (Repo.vnorm(d) or "/") not in old["dirs"]]
        return None

    def add_file(self, f, errs, added, where):
        if not isinstance(f, dict) or not isinstance(f.get("endpoints"), list):
            errs.append(f'{where}: needs "path", "service" and an "endpoints" list')
            return
        path = Repo.vnorm(f.get("path"))
        src = self.repo.source(path)
        svc = self.services.get(f.get("service"))
        why = None
        if src is None:
            why = f"not a readable file: {f.get('path')}"
        elif svc is None:
            why = (f"service {f.get('service')!r} is not recorded; record it first "
                   f"(recorded: {', '.join(self.services) or 'none'})")
        elif not any(d == "/" or path.startswith(d + "/") for d in svc["dirs"]):
            why = (f"{path} is not under the dirs of {svc['name']} ({', '.join(svc['dirs'])}); "
                   "add its module dir to the service or pick another")
        if why:
            errs.append(f"{where}: {why}")
            return
        entry = self.files.setdefault(path, {"path": path, "service": svc["name"], "endpoints": []})
        for i, e in enumerate(f["endpoints"]):
            why = check_endpoint(e, src)
            label = f"{where}.endpoints[{i}]"
            if isinstance(e, dict):
                label += f" {e.get('httpMethod')} {e.get('path')} ({e.get('className')}.{e.get('methodName')})"
            if why:
                errs.append(f"{label}: {why}")
                continue
            key = (path, e["httpMethod"].upper(), norm_route(e["path"]))   # not the handler: a model
            # recording from memory renames it, and one verb + route in one file is one endpoint
            if key in self.keys:
                continue
            self.keys.add(key)
            new = {**e, "httpMethod": e["httpMethod"].upper(), "line": int(e["line"])}
            old = next((x for x in entry["endpoints"] if prefix_variant(x, new)), None)
            if old:     # the same declaration with another prefix: one declaration is one endpoint
                entry["endpoints"][entry["endpoints"].index(old)] = new
                added.append(f"{new['httpMethod']} {new['path']} (replaces {old['path']})")
            else:
                entry["endpoints"].append(new)
                added.append(f"{new['httpMethod']} {new['path']}")
        if not entry["endpoints"]:
            del self.files[path]

    def record(self, payload):
        """Validate a fragment and keep what passes.  Returns (message, n_errors)."""
        doc, err = load_payload(payload)
        if err:
            return f"[REJECTED] {err}", 1
        errs, added = [], []
        for i, s in enumerate(doc.get("services") or []):
            why = self.add_service(s)
            if why:
                errs.append(f"services[{i}]: {why}")
            else:
                added.append(f"service {s['name']}")
        for i, f in enumerate(doc.get("files") or []):
            self.add_file(f, errs, added, f"files[{i}]")
        msg = (f"Recorded {len(added)} new: {', '.join(added[:40]) or 'nothing'}"
               + (" ..." if len(added) > 40 else "")
               + f"\nTotal: {len(self.services)} services, {self.n_endpoints()} endpoints "
               f"in {len(self.files)} files.")
        if not added and not errs:
            msg += "\nEverything you sent was already recorded; do not resend it."
        todo = [s for s in self.services if s not in {f["service"] for f in self.files.values()}]
        if todo:
            msg += f"\nServices with no endpoints recorded yet: {', '.join(todo)}."
        if errs:
            msg += (f"\n[REJECTED {len(errs)}] Fix these and record them again "
                    "(accepted entries are kept, do not resend them):\n- " + "\n- ".join(errs[:20]))
        return msg, len(errs)


# ----------------------------------------------------------------------- llm --
class LLMError(Exception):
    pass


def msg_size(m):
    return len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or ""))


def is_tool_result(m):
    return m["role"] == "tool" or (m["role"] == "user" and m["content"].startswith("<tool_response>"))


def fit(messages, budget):
    """Keep the prompt inside the context window: replace the oldest tool results
    (never the system prompt, the task or the last KEEP_RECENT results) with a
    stub.  Once over budget it elides down to FIT_TARGET of it in one go, so the
    prompt prefix stays the same for many steps and a prompt cache can reuse it.
    Returns how many were elided."""
    size = lambda: sum(msg_size(m) for m in messages)
    if size() <= budget:
        return 0
    stub = "[elided to save context - call the tool again if you still need it]"
    tool_idx = [i for i, m in enumerate(messages) if is_tool_result(m)]
    # Record payloads weigh as much as the results; Recorded keeps what they added. Left in
    # place they fill the budget, and every new result is elided as soon as it arrives.
    long_calls = [i for i, m in enumerate(messages) if m["role"] == "assistant" and msg_size(m) > LONG_CALL]
    n = 0
    for i in tool_idx[:-KEEP_RECENT] + long_calls + tool_idx[-KEEP_RECENT:]:
        if size() <= budget * FIT_TARGET:
            break
        m = messages[i]
        if m["role"] == "assistant":
            for c in m.get("tool_calls") or []:
                args = json.loads(c["function"]["arguments"])
                c["function"]["arguments"] = json.dumps({k: v if len(str(v)) <= 200 else "[elided]"
                                                         for k, v in args.items()}, ensure_ascii=False)
            if len(m.get("content") or "") > LONG_CALL:
                m["content"] = m["content"][:200] + " [elided]"
            n += 1
        elif "[elided" not in m["content"]:
            m["content"] = stub if m["role"] == "tool" else f"<tool_response>{stub}</tool_response>"
            n += 1
    return n


def chat(base_url, model, messages, effort, api_key=None, timeout=900, tries=5, tools=None,
         max_tokens=8192, effort_in_template=False, budget=CTX_CHARS):
    """One completion -> (text, tool_calls, usage).  Retries transient errors; on
    a 400 (typically context overflow) it halves the prompt budget and retries.
    Raises LLMError only when every attempt failed, so the caller can still
    write its output."""
    for attempt in range(1, tries + 1):
        fit(messages, budget)
        try:
            return _chat(base_url, model, messages, effort, api_key, timeout, tools, max_tokens,
                         effort_in_template)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            print(f"     HTTP {e.code} (attempt {attempt}/{tries}): {detail}")
            if e.code == 400:
                budget //= 2
            elif e.code not in (429, 500, 502, 503):
                raise LLMError(f"HTTP {e.code}: {detail}")
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
            print(f"     {detail} (attempt {attempt}/{tries})")
        time.sleep(min(2 ** attempt, 30))
    raise LLMError(f"gave up after {tries} attempts: {detail}")


QWEN_EFFORT = {"low": "low", "medium": "medium", "high": "xhigh", "xhigh": "xhigh"}


def build_body(model, messages, effort, tools, max_tokens, effort_in_template=False):
    """The /chat/completions request body. `effort` of 'none' turns thinking off:
    on a vLLM chat-template model (Qwen3.8) that is `chat_template_kwargs.enable_thinking=False`
    (vLLM validates top-level reasoning_effort against OpenAI's values), otherwise the
    top-level reasoning_effort LM Studio honours."""
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if tools:
        # Native tool calling: models tuned for it (GLM, Qwen on Wafer) ignore the
        # text <tool_call> protocol and answer with structured tool_calls. The server
        # ends the call itself, so no stop sequence.
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    else:
        body["stop"] = ["</tool_call>"]
    if effort_in_template:
        if effort == "none":
            body["chat_template_kwargs"] = {"enable_thinking": False}
        elif effort in QWEN_EFFORT:
            body["chat_template_kwargs"] = {"reasoning_effort": QWEN_EFFORT[effort]}
    elif effort != "default":
        body["reasoning_effort"] = effort      # LM Studio honours only this one
        if effort == "none":
            body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def _chat(base_url, model, messages, effort, api_key, timeout, tools=None, max_tokens=8192,
          effort_in_template=False):
    body = build_body(model, messages, effort, tools, max_tokens, effort_in_template)
    # Groq sits behind Cloudflare, which rejects urllib's default User-Agent (error 1010).
    headers = {"content-type": "application/json", "user-agent": "llm-ir-extraction/1.0"}
    if "wafer.ai" in base_url:
        headers["Wafer-ZDR"] = "required"      # Wafer refuses without it unless retention is allowed
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        env = json.loads(r.read().decode())
    msg = env["choices"][0]["message"]
    text = msg.get("content") or ""
    if "</think>" in text:                     # some backends inline reasoning in content
        text = text.rsplit("</think>", 1)[1]
    return text.strip(), msg.get("tool_calls") or [], env.get("usage") or {}


def parse_tool_calls(tool_calls, step):
    """Structured OpenAI tool_calls -> [(id, name, args)], every call, ids filled in."""
    calls = []
    for i, call in enumerate(tool_calls):
        fn = call.get("function") or call
        name = (fn.get("name") or "").strip()
        raw = fn.get("arguments")
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (ValueError, TypeError):
            args = {}
        calls.append((call.get("id") or f"call_{step}_{i}", name, args if isinstance(args, dict) else {}))
    return calls


def parse_call(text):
    m = CALL_RE.search(text)
    if not m:
        return None
    body = m.group(1)
    name = re.match(r"\s*(\w*)", body).group(1)
    args = {k.strip(): v for k, v in ARG_RE.findall(body)}
    for k, v in SHORT_ARG_RE.findall(body):   # Gemini writes <arg_path>v</arg_path>
        args.setdefault(k, v)
    return name, args


class Tee:
    """stdout copy into the run's own log file.  The run writes its log itself,
    so a shell redirect shared by two processes cannot interleave it."""
    def __init__(self, path, t0):
        self.f, self.out, self.t0, self.bol = open(path, "w", encoding="utf-8"), sys.stdout, t0, True

    def write(self, s):
        for part in s.splitlines(keepends=True):
            if self.bol and part.strip():
                part = f"{time.time() - self.t0:7.1f}s  " + part
            self.f.write(part)
            self.out.write(part)
            self.bol = part.endswith(chr(10))
        self.f.flush()

    def flush(self):
        self.f.flush()
        self.out.flush()


LOOP_REPEATS = 3        # the same call this many times = a loop
LOOP_STRIKES = 3        # warnings before exploration is closed: only record and submit run after that
MAX_BLOCKED = 5         # exploring calls refused after that before the run stops
NUDGE_STEPS = 15        # steps without a new endpoint before the model is told to record what it has


def suggestion(repo, visited):
    """Point a looping model at something it has not looked at yet."""
    top = [c.rstrip("/") for c in repo.list_dir("/").splitlines() if c.endswith("/")]
    fresh = [d for d in top if d not in visited]
    if fresh:
        return ("directories you have not opened yet: " + ", ".join("/" + d for d in fresh[:8])
                + f". Try e.g. list_dir /{fresh[0]}")
    return ("grep a different pattern over / (e.g. Mapping|@Path|router\\.|HandleFunc), "
            "or read a file you have not read yet")


# ---------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, nargs="+",
                    help="checkout(s); several are mounted side by side as one system")
    ap.add_argument("--system-name", required=True)
    ap.add_argument("--model", default="spark-x2.5-4b")
    ap.add_argument("--base-url", default="http://localhost:1234/v1")
    ap.add_argument("--effort", default="none", help="none|low|medium|high|default")
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--native-tools", action="store_true",
                    help="send tools as a native OpenAI tools array (for models that ignore the text protocol, e.g. GLM/Qwen on Wafer)")
    ap.add_argument("--max-tokens", type=int, default=8192,
                    help="output token cap per reply; raise for reasoning models that truncate")
    ap.add_argument("--ctx-chars", type=int, default=CTX_CHARS,
                    help="prompt budget in chars; lower it for a server with a small context")
    ap.add_argument("--effort-in-template", action="store_true",
                    help="pass effort via chat_template_kwargs, not top-level reasoning_effort (vLLM chat-template models, e.g. Qwen3.8); --effort none then sets enable_thinking=False")
    ap.add_argument("--out", default=None)
    ap.add_argument("--log", default=None, help="default: <out>.log")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

    repo = Repo(a.repo)
    out = Path(a.out) if a.out else HERE / "out" / f"agent_ir.{a.system_name}.{a.model}.{a.effort}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = out.with_suffix(".lock")
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        sys.exit(f"{lock} exists: another run writes {out.name}. Delete the lock if that run is dead.")
    try:
        run(a, repo, out)
    finally:
        lock.unlink(missing_ok=True)


def run(a, repo, out):
    t0 = time.time()
    sys.stdout = Tee(Path(a.log) if a.log else out.with_suffix(".log"), t0)
    print(f"agent {a.model} effort={a.effort} system={a.system_name} max_steps={a.max_steps} "
          f"files={len(repo.paths)}")
    mount = ("The repository is mounted read-only at /." if not repo.multi else
             "The system's repositories are mounted read-only side by side: "
             + ", ".join("/" + n for n in repo.roots) + ".")
    system = TASK.replace("{mount}", mount)
    if not a.native_tools:
        system += TEXT_PROTOCOL.replace("{tools}", "\n".join(json.dumps(t, separators=(",", ":")) for t in TOOLS))
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"Extract the services and inbound endpoints of {a.system_name}. "
                                            "Start with list_dir or find."}]
    rec = Recorded(repo, a.system_name)
    trace, error, finished, stopped = [], None, False, None
    in_tok = out_tok = cached_tok = rejected = no_call = 0
    seen, visited, strikes, blocked = Counter(), set(), 0, 0
    last = {}       # call signature -> the message holding its latest result
    n_seen = quiet = nudges = 0

    def reply(cid, result):
        if cid is None:
            messages.append({"role": "user", "content": f"<tool_response>{result}</tool_response>"})
        else:
            messages.append({"role": "tool", "tool_call_id": cid, "content": result})

    def execute(name, args):
        """Run one tool call -> (result, finished)."""
        nonlocal rejected
        payload = args.get("json", args if ("services" in args or "files" in args) else None)
        if name == "record":
            msg, n_err = rec.record(payload)
            rejected += n_err
            return msg, False
        if name == "submit":
            msg, n_err = rec.record(payload) if payload else ("", 0)
            rejected += n_err
            if n_err:
                return msg + "\n[NOT FINISHED] fix the rejected entries, then submit again.", False
            if not rec.services:
                return (msg + "\n[NOT FINISHED] no service is recorded yet. Record the services "
                        "and their endpoints, then submit.").strip(), False
            return (msg + f"\n[ACCEPTED] {len(rec.services)} services, {rec.n_endpoints()} endpoints.").strip(), True
        if name == "list_dir":
            return repo.list_dir(args.get("path", "/")), False
        if name == "find":
            return repo.find(args.get("pattern", "*"), args.get("path", "/")), False
        if name == "grep":
            return repo.grep(args.get("pattern", ""), args.get("path", "/")), False
        if name == "read_file":
            return repo.read_file(args.get("path", ""), args.get("start") or 1), False
        return f"[ERROR] unknown tool {name!r}. Tools: list_dir, find, grep, read_file, record, submit.", False

    step = 0
    for step in range(1, a.max_steps + 1):
        if step == a.max_steps - 4:
            messages.append({"role": "user", "content": "Only 4 steps left. Record everything you "
                             "still have evidence for and call submit; do not explore further."})
        elif quiet >= NUDGE_STEPS:
            # Models that explore first lose their findings once fit() elides old results.
            messages.append({"role": "user", "content": f"{quiet} steps without a new endpoint recorded. "
                             "Record the endpoints you have found so far now, before older tool results "
                             "drop out of your context; then continue."})
            quiet, nudges = 0, nudges + 1
        try:
            text, tool_calls, usage = chat(a.base_url, a.model, messages, a.effort, os.environ.get("LLM_API_KEY"),
                                           tools=TOOLS if a.native_tools else None, max_tokens=a.max_tokens,
                                           effort_in_template=a.effort_in_template, budget=a.ctx_chars)
        except LLMError as e:
            error = str(e)
            print(f"[{step:2d}] aborted: {error}")
            break
        in_tok += usage.get("prompt_tokens", 0)
        out_tok += usage.get("completion_tokens", 0)
        cached_tok += (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0

        calls = parse_tool_calls(tool_calls, step)
        if calls:
            msg = {"role": "assistant", "content": text,
                   "tool_calls": [{"id": cid, "type": "function",
                                   "function": {"name": n, "arguments": json.dumps(args, ensure_ascii=False)}}
                                  for cid, n, args in calls]}
        else:   # text protocol, or a native model that wrote the markup into content
            call = parse_call(text)
            calls = [(None, *call)] if call else []
            msg = {"role": "assistant", "content": text + ("</tool_call>" if call else "")}
        messages.append(msg)

        if not calls:
            no_call += 1
            reply(None, "[ERROR] No tool call in your reply. Call exactly one tool, "
                        "e.g. <tool_call>grep<arg_key>pattern</arg_key><arg_value>Mapping</arg_value></tool_call>. "
                        "When done, call submit.")
            print(f"[{step:2d}] -         (no tool call)")
            trace.append({"step": step, "tool": None})
            continue

        for cid, name, args in calls:
            sig = name + json.dumps(args, sort_keys=True)
            if sig in last and "[elided" in last[sig]["content"]:
                seen[sig] = 0       # fit() dropped its result and told the model to call again
            seen[sig] += name != "submit"
            if strikes >= LOOP_STRIKES and name not in ("record", "submit"):
                # Exploration is closed, but the run goes on until the model records what
                # it has seen: stopping here would throw away everything not yet recorded.
                blocked += 1
                if blocked > MAX_BLOCKED:
                    stopped = f"stopped at step {step}: ignored the order to submit"
                    print(f"[{step:2d}] {stopped}")
                    break
                result = ("[BLOCKED] Exploration is over, only record and submit work now. Record "
                          "every endpoint you have evidence for in the results above, then call submit.")
                print(f"[{step:2d}] BLOCKED {blocked}/{MAX_BLOCKED}: {name}")
            elif seen[sig] >= LOOP_REPEATS:
                # Loop guard: the call is not executed again - its result cannot change.
                strikes += 1
                if strikes > LOOP_STRIKES:
                    stopped = f"stopped at step {step}: kept repeating identical tool calls"
                    print(f"[{step:2d}] {stopped}")
                    break
                if strikes == LOOP_STRIKES:
                    result = (f"[LOOP] {name} with these exact arguments, {seen[sig]} times. Exploration "
                              "is over: from now on only record and submit work. Record what you have "
                              "evidence for and call submit.")
                else:
                    result = (f"[LOOP] You already called {name} with exactly these arguments "
                              f"{seen[sig] - 1} times; the result will not change and was not re-run. "
                              f"Do something different - {suggestion(repo, visited)}. "
                              f"Warning {strikes}/{LOOP_STRIKES}.")
                print(f"[{step:2d}] LOOP warning {strikes}/{LOOP_STRIKES}: {name} x{seen[sig]}")
            else:
                seg = [x for x in str(args.get("path", "/")).replace("\\", "/").split("/") if x]
                if seg:
                    visited.add(seg[0])
                try:
                    result, finished = execute(name, args)
                except Exception as e:
                    result = f"[ERROR] {type(e).__name__}: {e}"
            if len(result) > MAX_OUT:
                result = result[:MAX_OUT] + "\n[... truncated]"
            reply(cid, result)
            last[sig] = messages[-1]
            shown = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in args.items() if k != "json")
            print(f"[{step:2d}] {name or '-':9s} {shown}  -> {result.splitlines()[0][:100] if result else ''}")
            trace.append({"step": step, "tool": name, "args": {k: str(v)[:200] for k, v in args.items()},
                          "result_head": result[:1000]})
            if finished:
                break
        if rec.n_endpoints() > n_seen:
            n_seen, quiet = rec.n_endpoints(), 0
        else:
            quiet += 1
        if finished or stopped:
            break

    doc = rec.doc()
    states = {name: checkout_state(r) for name, r in repo.roots.items()}
    single = None if repo.multi else next(iter(states.values())) or {}
    doc["_run"] = {"model": a.model, "provider": a.base_url, "workflow": "agent",
                   "effort": a.effort, "temperature": 0, "native_tools": a.native_tools,
                   "repo": ", ".join(repo.roots),
                   **({"commit": single.get("commit"), "dirty": single.get("dirty")} if single is not None
                      else {"repos": states}),
                   "accepted": finished, "fallback": None if finished else
                   ("recorded so far" if rec.n_endpoints() or rec.services else "nothing recorded"),
                   "error": error, "stopped": stopped, "loop_warnings": strikes, "blocked_calls": blocked,
                   "record_nudges": nudges,
                   "elided_results": sum(1 for m in messages if "[elided" in (m.get("content") or "")),
                   "steps": step, "tool_calls": len(trace), "rejected_entries": rejected,
                   "no_call_replies": no_call,
                   "input_tokens": in_tok, "cached_input_tokens": cached_tok, "output_tokens": out_tok,
                   "list_price_usd": list_price(a.model, in_tok, out_tok, cached_tok),
                   "wall_seconds": round(time.time() - t0, 1), "trace": trace}
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    (out.with_suffix(".messages.json")).write_text(
        json.dumps(messages, indent=1, ensure_ascii=False), encoding="utf-8")
    r = doc["_run"]
    print(f"\naccepted {r['accepted']}  services {len(rec.services)}  endpoints {rec.n_endpoints()}  "
          f"steps {r['steps']}  rejected {rejected}  tokens {in_tok} ({cached_tok} cached)/{out_tok}  "
          f"wall {r['wall_seconds']} s\nwritten {out}")


if __name__ == "__main__":
    main()
