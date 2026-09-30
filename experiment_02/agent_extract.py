#!/usr/bin/env python3
"""Agentic endpoint extraction: the model explores the repository itself with
three read-only tools (list_dir, grep, read_file) and finishes by calling
submit with one JSON document.  submit validates it; a rejected document goes
back to the model with the reasons, so it can fix and resubmit.

The output schema is the Appendix A one used in experiment_01, so
experiment_01/evaluate.py scores both workflows the same way.

Tool calls use Spark-X2.5's text format (LM Studio has no parser for it):
    <tool_call>name<arg_key>k</arg_key><arg_value>v</arg_value></tool_call>

    python agent_extract.py --model spark-x2.5-4b --effort none
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP_DIRS = {".git", "target", "build", "node_modules", ".idea", ".mvn", ".gradle"}
MAX_OUT = 6000          # chars of one tool result shown to the model
CTX_CHARS = 150_000     # prompt budget in chars (~40k tokens), below LM Studio's 64k context
KEEP_RECENT = 8         # tool results always kept verbatim; older ones are elided first
VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "ANY"}

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
    {"name": "submit", "description": "Submit the final result. It is validated; "
     "if rejected you get the reasons and must submit again.",
     "parameters": {"type": "object", "properties": {
         "json": {"type": "string", "description": "the whole output document"}},
         "required": ["json"]}},
]

SYSTEM = """You are extracting the architecture of a microservice system from its source code.
The repository is mounted read-only at /. Explore it with the tools, then submit the result.

Task: find every inbound HTTP endpoint the system serves (Spring @RestController/@Controller
mappings, JAX-RS @Path, etc.).
Rules:
- Do not invent endpoints. Use only evidence you have read in the code.
- Separate inbound endpoints from outbound REST/client calls: a @FeignClient interface or a
  RestTemplate/WebClient call is OUTBOUND - do not list it.
- Resolve class-level and method-level route annotations into one full path.
- Routes may be declared on an interface or parent class that the controller implements.
- Prefer grep over reading whole directories. Skip src/test.

## Tools
You have access to the following functions:
<tools>
{tools}
</tools>

Call exactly ONE tool per message, in this format, and then stop:
<tool_call>grep<arg_key>pattern</arg_key><arg_value>@RestController</arg_value></tool_call>

Finish by calling submit with a JSON document of this shape:
{{
  "system": "{system}",
  "files": [
    {{"path": "/user-service/src/main/java/.../UserController.java",
      "endpoints": [
        {{"className": "UserController", "methodName": "getUser", "httpMethod": "GET",
          "path": "/user/{{userId}}", "framework": "Spring",
          "evidence": "@GetMapping(\\"/{{userId}}\\")", "confidence": "high"}}]}}]
}}
httpMethod is one of GET, POST, PUT, DELETE, PATCH, ANY. confidence is high, medium or low."""

CALL_RE = re.compile(r"<tool_call>(.*?)(?:</tool_call>|$)", re.S)
ARG_RE = re.compile(r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)(?:</arg_value>|$)", re.S)


# --------------------------------------------------------------------- tools --
class Repo:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def resolve(self, rel):
        p = (self.root / (rel or "/").replace("\\", "/").lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError("path outside the repository")
        return p

    def rel(self, p):
        return "/" + p.relative_to(self.root).as_posix()

    def list_dir(self, path="/"):
        d = self.resolve(path)
        if not d.is_dir():
            return f"[ERROR] not a directory: {path}"
        return "\n".join(c.name + ("/" if c.is_dir() else "")
                         for c in sorted(d.iterdir()) if c.name not in SKIP_DIRS) or "(empty)"

    def grep(self, pattern, path="/"):
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"[ERROR] bad regex: {e}"
        hits = []
        for dirpath, dirs, files in os.walk(self.resolve(path)):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for f in sorted(files):
                p = Path(dirpath) / f
                if p.stat().st_size > 1_000_000:
                    continue
                try:
                    lines = p.read_text(encoding="utf-8", errors="strict").splitlines()
                except (UnicodeDecodeError, OSError):
                    continue
                for i, line in enumerate(lines, 1):
                    if rx.search(line):
                        hits.append(f"{self.rel(p)}:{i}: {line.strip()[:200]}")
                        if len(hits) >= 60:
                            return "\n".join(hits) + "\n[... more hits, narrow the pattern or path]"
        return "\n".join(hits) or "(no matches)"

    def read_file(self, path, start=1):
        p = self.resolve(path)
        if not p.is_file():
            return f"[ERROR] not a file: {path}"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        s = max(int(start or 1), 1)
        body = "\n".join(f"{i}: {l}" for i, l in enumerate(lines[s - 1:s + 299], s))
        if s + 299 < len(lines):
            body += f"\n[... {len(lines)} lines total, read again with start={s + 300}]"
        return body


def validate(text, repo):
    """Return (doc, errors).  Structural schema check plus evidence checks:
    every file must exist and name the class it is attributed to."""
    try:
        doc = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
    except Exception as e:
        return None, [f"not valid JSON: {e}"]
    errs = []
    if not isinstance(doc, dict) or not isinstance(doc.get("files"), list):
        return None, ['top level must be an object with a "files" list']
    for fi, f in enumerate(doc["files"]):
        where = f"files[{fi}]"
        if not isinstance(f, dict) or not isinstance(f.get("endpoints"), list):
            errs.append(f'{where}: needs "path" and an "endpoints" list')
            continue
        try:
            p = repo.resolve(f.get("path") or "")
            src = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
        except ValueError:
            src = None
        if src is None:
            errs.append(f"{where}: file does not exist: {f.get('path')}")
        for ei, e in enumerate(f["endpoints"]):
            w = f"{where}.endpoints[{ei}]"
            if not isinstance(e, dict):
                errs.append(f"{w}: must be an object")
                continue
            for k in ("className", "methodName", "httpMethod", "path"):
                if not isinstance(e.get(k), str) or not e.get(k):
                    errs.append(f"{w}: missing {k}")
            if e.get("httpMethod") and str(e["httpMethod"]).upper() not in VERBS:
                errs.append(f"{w}: httpMethod must be one of {sorted(VERBS)}")
            if src and e.get("className") and e["className"] not in src:
                errs.append(f"{w}: class {e['className']} does not appear in {f.get('path')}")
            if src and e.get("methodName") and e["methodName"] not in src:
                errs.append(f"{w}: method {e['methodName']} does not appear in {f.get('path')}")
    return doc, errs[:20]


# ----------------------------------------------------------------------- llm --
class LLMError(Exception):
    pass


def fit(messages, budget):
    """Keep the prompt inside the context window: replace the oldest tool results
    (never the system prompt, the task or the last KEEP_RECENT results) with a
    stub until the whole conversation fits.  Returns how many were elided."""
    size = lambda: sum(len(m["content"]) for m in messages)
    tool_idx = [i for i, m in enumerate(messages)
                if m["role"] == "user" and m["content"].startswith("<tool_response>")]
    n = 0
    for i in tool_idx[:-KEEP_RECENT] + tool_idx[-KEEP_RECENT:]:
        if size() <= budget:
            break
        if "[elided" not in messages[i]["content"]:
            messages[i]["content"] = ("<tool_response>[elided to save context - "
                                      "call the tool again if you still need it]</tool_response>")
            n += 1
    return n


def chat(base_url, model, messages, effort, api_key=None, timeout=900, tries=5):
    """One completion.  Retries transient errors; on a 400 (typically context
    overflow) it halves the prompt budget and retries.  Raises LLMError only
    when every attempt failed, so the caller can still write its output."""
    budget = CTX_CHARS
    for attempt in range(1, tries + 1):
        fit(messages, budget)
        try:
            return _chat(base_url, model, messages, effort, api_key, timeout)
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


def _chat(base_url, model, messages, effort, api_key, timeout):
    body = {"model": model, "messages": messages, "temperature": 0,
            "max_tokens": 8192, "stop": ["</tool_call>"]}
    if effort != "default":
        body["reasoning_effort"] = effort      # LM Studio honours only this one
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        env = json.loads(r.read().decode())
    msg = env["choices"][0]["message"]
    text = msg.get("content") or ""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip(), env.get("usage") or {}


def parse_call(text):
    m = CALL_RE.search(text)
    if not m:
        return None
    body = m.group(1)
    name = re.split(r"[<\s]", body.strip(), 1)[0]
    return name, {k.strip(): v for k, v in ARG_RE.findall(body)}


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
LOOP_STRIKES = 3        # warnings before the model is made to submit; one more and the run stops


def suggestion(repo, visited):
    """Point a looping model at something it has not looked at yet."""
    top = [c.name for c in sorted(repo.root.iterdir()) if c.is_dir() and c.name not in SKIP_DIRS
           and not c.name.startswith(".")]
    fresh = [d for d in top if d not in visited]
    if fresh:
        return ("directories you have not opened yet: " + ", ".join("/" + d for d in fresh[:8])
                + f". Try e.g. list_dir /{fresh[0]}")
    return ("grep a different pattern over / (e.g. Mapping|@Path|RouterFunction), "
            "or read a file you have not read yet")


# ---------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--system-name", required=True)
    ap.add_argument("--model", default="spark-x2.5-4b")
    ap.add_argument("--base-url", default="http://localhost:1234/v1")
    ap.add_argument("--effort", default="none", help="none|low|medium|high|default")
    ap.add_argument("--max-steps", type=int, default=60)
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
    print(f"agent {a.model} effort={a.effort} system={a.system_name} max_steps={a.max_steps}")
    tools = "\n".join(json.dumps(t, separators=(",", ":")) for t in TOOLS)
    messages = [{"role": "system", "content": SYSTEM.format(tools=tools, system=a.system_name)},
                {"role": "user", "content": f"Extract the inbound endpoints of {a.system_name}. Start with list_dir or grep."}]
    trace, doc, error = [], None, None
    in_tok = out_tok = rejected = no_call = 0
    best = None     # last submitted document that parsed, kept if nothing is accepted
    seen, visited, strikes, stopped = Counter(), set(), 0, None

    for step in range(1, a.max_steps + 1):
        if step == a.max_steps - 4:
            messages.append({"role": "user", "content": "Only 4 steps left. Call submit NOW with "
                             "every endpoint you have evidence for; do not explore further."})
        try:
            text, usage = chat(a.base_url, a.model, messages, a.effort, os.environ.get("LLM_API_KEY"))
        except LLMError as e:
            error = str(e)
            print(f"[{step:2d}] aborted: {error}")
            break
        in_tok += usage.get("prompt_tokens", 0)
        out_tok += usage.get("completion_tokens", 0)
        call = parse_call(text)
        messages.append({"role": "assistant", "content": text + ("</tool_call>" if call else "")})
        if not call:
            no_call += 1
            result = ("[ERROR] No <tool_call> in your reply. Call exactly one tool, "
                      "e.g. <tool_call>grep<arg_key>pattern</arg_key><arg_value>Mapping</arg_value></tool_call>. "
                      "When done, call submit.")
            name, args = None, {}
        else:
            name, args = call
            sig = name + json.dumps(args, sort_keys=True)
            seen[sig] += name != "submit"
        if call and seen[sig] >= LOOP_REPEATS:
            # Loop guard: the call is not executed again - its result cannot change.
            strikes += 1
            if strikes > LOOP_STRIKES:
                stopped = f"stopped at step {step}: kept repeating identical tool calls"
                print(f"[{step:2d}] {stopped}")
                break
            if strikes == LOOP_STRIKES:
                result = (f"[LOOP] {name} with these exact arguments, {seen[sig]} times. Exploration "
                          "is over: call submit NOW with every endpoint you have evidence for. "
                          "Any other call ends the run without your result.")
            else:
                result = (f"[LOOP] You already called {name} with exactly these arguments "
                          f"{seen[sig] - 1} times; the result will not change and was not re-run. "
                          f"Do something different - {suggestion(repo, visited)}. "
                          f"Warning {strikes}/{LOOP_STRIKES}.")
            print(f"[{step:2d}] LOOP warning {strikes}/{LOOP_STRIKES}: {name} x{seen[sig]}")
        elif call:
            if strikes >= LOOP_STRIKES and name != "submit":
                stopped = f"stopped at step {step}: ignored the order to submit"
                print(f"[{step:2d}] {stopped}")
                break
            seg = [x for x in str(args.get("path", "/")).replace("\\", "/").split("/") if x]
            if seg:
                visited.add(seg[0])
            try:
                if name == "submit":
                    doc, errs = validate(args.get("json", ""), repo)
                    if not errs:
                        trace.append({"step": step, "tool": name, "ok": True})
                        print(f"[{step:2d}] submit  ACCEPTED")
                        break
                    rejected += 1
                    if doc is not None:
                        best = doc
                    doc = None
                    result = "[REJECTED] Fix these and submit again:\n- " + "\n- ".join(errs)
                elif name == "list_dir":
                    result = repo.list_dir(args.get("path", "/"))
                elif name == "grep":
                    result = repo.grep(args.get("pattern", ""), args.get("path", "/"))
                elif name == "read_file":
                    result = repo.read_file(args.get("path", ""), args.get("start") or 1)
                else:
                    result = f"[ERROR] unknown tool {name!r}. Tools: list_dir, grep, read_file, submit."
            except Exception as e:
                result = f"[ERROR] {type(e).__name__}: {e}"
        if len(result) > MAX_OUT:
            result = result[:MAX_OUT] + "\n[... truncated]"
        messages.append({"role": "user", "content": f"<tool_response>{result}</tool_response>"})
        shown = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in args.items() if k != "json")
        print(f"[{step:2d}] {name or '-':9s} {shown}  -> {result.splitlines()[0][:80] if result else ''}")
        trace.append({"step": step, "tool": name, "args": {k: str(v)[:200] for k, v in args.items()},
                      "result_head": result[:300]})

    accepted = doc is not None
    doc = doc or best or {"system": a.system_name, "files": []}
    doc["_run"] = {"model": a.model, "provider": a.base_url, "workflow": "agent",
                   "effort": a.effort, "temperature": 0, "repo": Path(a.repo).name,
                   "accepted": accepted, "fallback": None if accepted else
                   ("last rejected submit" if best else "nothing submitted"), "error": error, "stopped": stopped, "loop_warnings": strikes,
                   "elided_results": sum(1 for m in messages if "[elided" in m["content"]),
                   "steps": len(trace), "rejected_submits": rejected, "no_call_replies": no_call,
                   "input_tokens": in_tok, "output_tokens": out_tok,
                   "wall_seconds": round(time.time() - t0, 1), "trace": trace}
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    (out.with_suffix(".messages.json")).write_text(
        json.dumps(messages, indent=1, ensure_ascii=False), encoding="utf-8")
    r = doc["_run"]
    print(f"\naccepted {r['accepted']}  steps {r['steps']}  rejected {rejected}  "
          f"tokens {in_tok}/{out_tok}  wall {r['wall_seconds']} s\nwritten {out}")


if __name__ == "__main__":
    main()
