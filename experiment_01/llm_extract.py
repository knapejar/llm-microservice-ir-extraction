#!/usr/bin/env python3
"""LLM-based endpoint extraction using the Appendix A prompt from
"CIMET versus LLM-Style Endpoint IR Extraction" (Mani/Knapek, 2026-08).

One request per source file.  System instruction is the prompt file verbatim;
the user turn carries the repo-relative path and the raw file contents.

API keys: one per line in keys.txt.  Never printed.
Usage:
    python llm_extract.py --model gemini-2.5-flash-lite
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_KEYS = str(HERE / "keys.txt")
DEFAULT_REPO = str(HERE / "clone" / "spring-cloud-movie-recommendation")
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# USD per 1M tokens (list price).
PRICES = {
    "gemini-2.5-flash-lite":  (0.10, 0.40),
    "gemini-3.5-flash-lite":  (0.10, 0.40),
}


def load_keys(path):
    keys = [l.strip() for l in open(path, encoding="utf-8-sig")
            if l.strip() and not l.strip().startswith("#")]
    if not keys:
        sys.exit(f"no keys in {path}")
    return keys


def collect_files(repo, include=None):
    """Main-source Java files only - mirrors what CIMET scans.

    `include` restricts the run to a sub-path of the repository (an evaluation
    frame) while keeping repo-relative paths intact, so service attribution and
    frame matching still work downstream.
    """
    root = Path(repo)
    out = []
    for p in sorted(root.rglob("*.java")):
        s = p.as_posix()
        if "/src/test/" in s or "/target/" in s or "/build/" in s:
            continue
        if "/src/main/" not in s:
            continue
        if include and include not in p.relative_to(root).as_posix():
            continue
        out.append(p)
    return out


def post(url, key, body, timeout=180):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"_err": f"{type(e).__name__}: {e}"}


def strip_fence(text):
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    return m.group(1) if m else t


def call(model, instruction, payload, keys, state, timeout=180):
    """Rotate keys on 429/5xx.  Returns (parsed_or_None, meta)."""
    body = {
        "systemInstruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user", "parts": [{"text": payload}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 8192,
                             "responseMimeType": "application/json"},
    }
    url = API.format(model=model)
    attempts, throttles, t0 = 0, 0, time.time()
    while attempts < len(keys) * 2:
        key = keys[state["i"] % len(keys)]
        attempts += 1
        st, env = post(url, key, body, timeout)
        if st == 200:
            parts = (env.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            u = env.get("usageMetadata") or {}
            meta = {"status": 200, "throttles": throttles, "attempts": attempts,
                    "in_tok": u.get("promptTokenCount", 0),
                    "out_tok": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
                    "ms": int((time.time() - t0) * 1000), "raw_text": text,
                    "finish": (env.get("candidates") or [{}])[0].get("finishReason")}
            try:
                return json.loads(strip_fence(text)), meta
            except Exception as e:
                meta["parse_error"] = f"{type(e).__name__}: {e}"
                return None, meta
        if st in (404, 429, 500, 503, 0):
            throttles += 1
            state["i"] += 1
            time.sleep(min(2 ** min(throttles, 5) * 0.4, 12))
            continue
        return None, {"status": st, "throttles": throttles, "attempts": attempts,
                      "error": json.dumps(env)[:400], "ms": int((time.time() - t0) * 1000)}
    return None, {"status": -1, "throttles": throttles, "attempts": attempts,
                  "error": "key pool exhausted", "ms": int((time.time() - t0) * 1000)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-flash-lite")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--keys", default=os.environ.get("GOOGLE_AI_KEYS_FILE", DEFAULT_KEYS))
    ap.add_argument("--prompt", default=str(HERE / "prompt_appendix_a.txt"))
    ap.add_argument("--system-name", default="spring-cloud-movie-recommendation")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include", default=None,
                    help="only files whose repo-relative path contains this "
                         "(restricts the run to an evaluation frame)")
    a = ap.parse_args()

    out_path = Path(a.out) if a.out else HERE / "out" / f"llm_ir.{a.model}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    instruction = Path(a.prompt).read_text(encoding="utf-8")
    keys = load_keys(a.keys)
    files = collect_files(a.repo, a.include)
    if a.limit:
        files = files[:a.limit]
    repo_root = Path(a.repo)

    print(f"model      : {a.model}")
    print(f"repo       : {a.repo}")
    print(f"key pool   : {len(keys)}")
    print(f"files      : {len(files)}\n")

    state, results, log = {"i": 0}, [], []
    in_tok = out_tok = 0
    t_all = time.time()

    for n, p in enumerate(files, 1):
        rel = "/" + p.relative_to(repo_root).as_posix()
        src = p.read_text(encoding="utf-8", errors="replace")
        payload = f"File path: {rel}\nSystem: {a.system_name}\n\n<source>\n{src}\n</source>"
        parsed, meta = call(a.model, instruction, payload, keys, state)
        in_tok += meta.get("in_tok", 0)
        out_tok += meta.get("out_tok", 0)

        eps = []
        valid = False
        if isinstance(parsed, dict) and isinstance(parsed.get("files"), list):
            valid = True
            for f in parsed["files"]:
                if isinstance(f, dict):
                    for e in (f.get("endpoints") or []):
                        if isinstance(e, dict):
                            e = dict(e)
                            e["_file"] = f.get("path") or rel
                            eps.append(e)
        results.append({"path": rel, "endpoints": eps})
        log.append({"path": rel, "schema_ok": valid, "n_endpoints": len(eps), **{
            k: v for k, v in meta.items() if k != "raw_text"}})

        flag = "ok " if valid else "BAD"
        print(f"[{n:3d}/{len(files)}] {flag} {len(eps):2d} ep  {meta.get('ms',0):5d} ms  "
              f"thr={meta.get('throttles',0)}  {rel}")
        if not valid:
            print(f"          -> {meta.get('parse_error') or meta.get('error') or meta.get('finish')}")

    pin, pout = PRICES.get(a.model, (0.0, 0.0))
    cost = in_tok / 1e6 * pin + out_tok / 1e6 * pout
    doc = {
        "system": a.system_name,
        "files": results,
        "_run": {
            "model": a.model, "provider": "google-ai-studio",
            "prompt_file": Path(a.prompt).name, "temperature": 0,
            "repo": a.repo, "frame": a.include, "n_files": len(files),
            "n_endpoints": sum(len(r["endpoints"]) for r in results),
            "schema_valid_files": sum(1 for l in log if l["schema_ok"]),
            "input_tokens": in_tok, "output_tokens": out_tok,
            "list_price_usd": round(cost, 4),
            "wall_seconds": round(time.time() - t_all, 1),
            "per_file": log,
        },
    }
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    r = doc["_run"]
    print(f"\nfiles ok   : {r['schema_valid_files']}/{r['n_files']}")
    print(f"endpoints  : {r['n_endpoints']}")
    print(f"tokens     : {in_tok} in / {out_tok} out   (list price ${cost:.4f})")
    print(f"wall       : {r['wall_seconds']} s")
    print(f"written    : {out_path}")


if __name__ == "__main__":
    main()
