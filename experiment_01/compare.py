#!/usr/bin/env python3
"""Compare an LLM endpoint extraction against the CIMET IR baseline.

Neither side is manually validated ground truth.  CIMET is used as the
reference set, so "precision/recall" here mean agreement with CIMET, not
correctness.  Reported at two granularities because a route-level and a
code-level identity key answer different questions.

Usage:
    python compare.py --llm out/llm_ir.gemini-2.5-flash-lite.json
"""
import argparse, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:                                     # Windows console defaults to cp1252
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------- canonical --
def canon_path(p):
    """{movieId} and {?} both collapse to {} ; case and trailing slash folded."""
    if not p:
        return ""
    # braces first: CIMET writes its placeholder as {?}, so splitting on the
    # query separator before this would truncate the path at the '?'.
    p = re.sub(r"\{[^}]*\}", "{}", p.strip())
    p = p.split("?")[0]
    p = re.sub(r":[^/]+", "", p)          # /user/:id style
    p = re.sub(r"/+", "/", p)
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1:
        p = p.rstrip("/")
    return p.lower()


def canon_verb(v):
    v = (v or "").strip().upper()
    return {"ANY": "ALL", "": "ALL"}.get(v, v)


def service_from_path(p):
    """First path segment == module dir == service name in this repo layout."""
    segs = [s for s in (p or "").replace("\\", "/").split("/") if s]
    return segs[0] if segs else "?"


# ---------------------------------------------------------------- loaders ----
def load_cimet(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for ms in d["microservices"]:
        for bucket in ("controllers", "services", "repositories",
                       "entities", "unknowns", "feignClients"):
            for cls in ms.get(bucket) or []:
                for m in cls.get("methods") or []:
                    if m.get("type") == "Endpoint":
                        rows.append({
                            "service": ms["name"],
                            "verb": canon_verb(m.get("httpMethod")),
                            "path": canon_path(m.get("url")),
                            "raw_path": m.get("url"),
                            "cls": cls["name"].replace(".java", ""),
                            "method": m.get("name"),
                            "file": cls.get("path"),
                        })
    return rows


def load_cimet_restcalls(path):
    """CIMET's outbound side - the prompt told the model to keep these separate."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for ms in d["microservices"]:
        for bucket in ("controllers", "services", "repositories",
                       "entities", "unknowns", "feignClients"):
            for cls in ms.get(bucket) or []:
                for m in cls.get("methods") or []:
                    for mc in m.get("methodCalls") or []:
                        if mc.get("type") == "RestCall":
                            rows.append({
                                "service": ms["name"],
                                "verb": canon_verb(mc.get("httpMethod")),
                                "path": canon_path(mc.get("url")),
                                "raw_path": mc.get("url"),
                                "cls": cls["name"].replace(".java", ""),
                                "method": m.get("name"),
                            })
    return rows


def load_llm(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for f in d.get("files", []):
        for e in f.get("endpoints", []):
            fp = e.get("_file") or f.get("path") or ""
            rows.append({
                "service": service_from_path(fp),
                "verb": canon_verb(e.get("httpMethod")),
                "path": canon_path(e.get("path")),
                "raw_path": e.get("path"),
                "cls": (e.get("className") or "").split(".")[-1],
                "method": e.get("methodName"),
                "file": fp,
                "framework": e.get("framework"),
                "confidence": e.get("confidence"),
            })
    return rows, d.get("_run", {})


# ---------------------------------------------------------------- metrics ----
def key_route(r):
    return (r["service"], r["verb"], r["path"])


def key_code(r):
    return (r["service"], r["cls"], r["method"])


def prf(ref, hyp):
    """ref = CIMET set, hyp = LLM set."""
    tp = len(hyp & ref)
    p = tp / len(hyp) if hyp else 0.0
    r = tp / len(ref) if ref else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"tp": tp, "fp": len(hyp - ref), "fn": len(ref - hyp),
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4),
            "jaccard": round(len(hyp & ref) / len(hyp | ref), 4) if (hyp | ref) else 0.0}


def dup_rate(rows, keyfn):
    c = Counter(keyfn(r) for r in rows)
    dups = sum(v - 1 for v in c.values() if v > 1)
    return round(dups / len(rows), 4) if rows else 0.0, dups


# ---------------------------------------------------------------- report -----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", required=True)
    ap.add_argument("--cimet", default=str(HERE / "baseline" / "IR-movie.cimet.json"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    cim = load_cimet(a.cimet)
    llm, run = load_llm(a.llm)

    L = []
    w = L.append
    model = run.get("model", "?")
    w(f"# CIMET vs. LLM — endpoint extraction agreement\n")
    w(f"- model: `{model}`, temperature 0, prompt: `{run.get('prompt_file')}`")
    w(f"- system: `{run.get('repo','?')}`")
    w(f"- files sent: {run.get('n_files')}, schema-valid responses: "
      f"{run.get('schema_valid_files')}/{run.get('n_files')}")
    w(f"- tokens: {run.get('input_tokens')} in / {run.get('output_tokens')} out "
      f"— list price ${run.get('list_price_usd')}, wall {run.get('wall_seconds')} s")
    w(f"- CIMET endpoints: **{len(cim)}**, LLM endpoints: **{len(llm)}**, "
      f"ratio {len(llm)/len(cim):.2f}\n")

    for name, keyfn in (("route-level  (service + verb + canonical path)", key_route),
                        ("code-level   (service + class + method)", key_code)):
        ref, hyp = {keyfn(r) for r in cim}, {keyfn(r) for r in llm}
        m = prf(ref, hyp)
        w(f"## {name}\n")
        w(f"| tp | fp | fn | precision | recall | F1 | Jaccard |")
        w(f"|---:|---:|---:|---:|---:|---:|---:|")
        w(f"| {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']} | "
          f"{m['recall']} | {m['f1']} | {m['jaccard']} |\n")
        if hyp - ref:
            w(f"**LLM only ({len(hyp-ref)}):**\n")
            for k in sorted(hyp - ref):
                w(f"- `{' '.join(str(x) for x in k)}`")
            w("")
        if ref - hyp:
            w(f"**CIMET only ({len(ref-hyp)}):**\n")
            for k in sorted(ref - hyp):
                w(f"- `{' '.join(str(x) for x in k)}`")
            w("")

    # --- where do the LLM's surplus endpoints actually belong? ---------------
    rest = load_cimet_restcalls(a.cimet)
    rest_code = {key_code(r) for r in rest}
    rest_route = {(r["service"], r["verb"], r["path"]) for r in rest}
    surplus = [r for r in llm if key_code(r) not in {key_code(c) for c in cim}]
    as_outbound = [r for r in surplus if key_code(r) in rest_code
                   or key_route(r) in rest_route]
    unexplained = [r for r in surplus if r not in as_outbound]
    w("## Where the LLM's surplus endpoints belong\n")
    w(f"CIMET outbound calls (`RestCall`): {len(rest)}\n")
    w(f"| category | count |")
    w(f"|---|---:|")
    w(f"| surplus endpoints over CIMET | {len(surplus)} |")
    w(f"| of which match a CIMET `RestCall` (= outbound, misclassified) | {len(as_outbound)} |")
    w(f"| of which unexplained (hallucination candidates) | {len(unexplained)} |")
    w(f"| **hallucination rate** | **{len(unexplained)/len(llm):.1%}** |")
    w(f"| **role-separation error rate** | **{len(as_outbound)/len(llm):.1%}** |\n")
    if unexplained:
        w("Unexplained:\n")
        for r in unexplained:
            w(f"- `{r['service']} {r['verb']} {r['raw_path']}` "
              f"({r['cls']}.{r['method']})")
        w("")

    dr, dn = dup_rate(llm, key_route)
    dc, dcn = dup_rate(cim, key_route)
    w("## Other metrics\n")
    w(f"| metric | CIMET | LLM |")
    w(f"|---|---:|---:|")
    w(f"| duplicate endpoints (route key) | {dcn} ({dc:.1%}) | {dn} ({dr:.1%}) |")
    w(f"| schema validity | n/a (deterministic) | "
      f"{run.get('schema_valid_files',0)}/{run.get('n_files',0)}"
      f" = {run.get('schema_valid_files',0)/max(run.get('n_files',1),1):.1%} |")
    conf = Counter(r.get("confidence") for r in llm)
    fw = Counter(r.get("framework") for r in llm)
    w(f"| confidence high/medium/low | n/a | "
      f"{conf.get('high',0)}/{conf.get('medium',0)}/{conf.get('low',0)} |")
    w(f"| framework labels | n/a | {dict(fw)} |\n")

    w("## Per service\n")
    w("| service | CIMET | LLM | match (route) |")
    w("|---|---:|---:|---:|")
    svcs = sorted({r["service"] for r in cim} | {r["service"] for r in llm})
    for s in svcs:
        c = {key_route(r) for r in cim if r["service"] == s}
        l = {key_route(r) for r in llm if r["service"] == s}
        w(f"| {s} | {len(c)} | {len(l)} | {len(c & l)} |")
    w("")

    w("## All LLM endpoints\n")
    w("| service | verb | path (raw) | class.method | conf |")
    w("|---|---|---|---|---|")
    for r in sorted(llm, key=lambda x: (x["service"], x["path"], x["verb"])):
        w(f"| {r['service']} | {r['verb']} | `{r['raw_path']}` | "
          f"{r['cls']}.{r['method']} | {r.get('confidence')} |")
    w("")

    txt = "\n".join(L)
    out = Path(a.out) if a.out else Path(a.llm).with_suffix(".report.md")
    out.write_text(txt, encoding="utf-8")
    print(txt)
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
