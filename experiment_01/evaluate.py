#!/usr/bin/env python3
"""Score an extractor against the manual ground truth.

Unlike compare.py, which uses CIMET as the reference set and therefore measures
*agreement*, this scores against `groundtruth/*.gt.json` and therefore measures
*correctness*.  Both CIMET IR and the LLM IR format are accepted as input.

Four matching levels are reported separately (see groundtruth/README.md S5):

    M1 exact       service + verb + path as declared
    M2 normalized  service + verb + normalized path        <- the operative level
    M3 path only   service + normalized path               (verb ignored)
    M4 code        service + class + method name

A hit at M4 but not M2 is a normalization or composition error; a miss at M4 is
a detection error.  Matching is multiset-aware, so a duplicated prediction costs
a false positive instead of being silently absorbed.

    python evaluate.py --pred baseline/IR-movie.cimet.json
    python evaluate.py --pred out/llm_ir.gemini-2.5-flash-lite.json
"""
import argparse, json, re, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CIMET_BUCKETS = ("controllers", "services", "repositories",
                 "entities", "unknowns", "feignClients")


# ------------------------------------------------------------ normalization --
def norm_path(p):
    """groundtruth/README.md S4.  Property placeholders resolve to their default
    first; braces collapse before the query split."""
    p = (p or "").strip()
    p = re.sub(r"\$\{[^}:]*:([^}]*)\}", r"\1", p)   # ${prop:default} -> default
    p = re.sub(r"\$\{[^}]*\}", "", p)               # ${prop} -> ""
    p = re.sub(r"\{[^}]*\}", "{}", p)
    p = p.split("?")[0]
    p = re.sub(r"^https?://[^/]+", "", p)
    p = re.sub(r":[^/]+", "", p)
    p = re.sub(r"/+", "/", p)
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1:
        p = p.rstrip("/")
    return p.lower()


def norm_verb(v):
    v = (v or "").strip().upper()
    return "ALL" if v in ("", "ANY") else v


def rec(service, verb, declared, cls, method, origin, extra=None):
    return {"service": service, "verb": norm_verb(verb),
            "declared": declared or "", "path": norm_path(declared),
            "cls": (cls or "").replace(".java", "").split(".")[-1],
            "method": method or "", "origin": origin, **(extra or {})}


def frame_filter(gt_doc):
    """A ground truth may cover only part of a system.  A prediction outside
    that part is neither right nor wrong here — it is simply unjudgeable, and
    counting it as a false positive would misreport the extractor."""
    fr = (gt_doc.get("meta") or {}).get("frame") or {}
    if not fr or fr.get("kind") in (None, "whole_system"):
        return None, None
    prefix = fr.get("definition", "").split("**")[0].strip("/")
    if not prefix:
        return None, None
    return (lambda p: (p or "").replace("\\", "/").lstrip("/").startswith(prefix),
            fr.get("definition"))


def service_resolver(gt_doc):
    """The Appendix A schema has no service field, so an LLM prediction's service
    is always reconstructed after the fact.  The old rule -- first path segment --
    only worked on a repo with one directory per service.  Resolve against the
    module directories the ground truth declares instead, longest prefix wins,
    and fall back to the first segment when nothing matches."""
    pairs = []
    for svc in gt_doc.get("services", []):
        for d in [svc.get("module_dir")] + list(svc.get("serves_modules") or []):
            if d:
                pairs.append((d.replace("\\", "/").strip("/"), svc["name"]))
    pairs.sort(key=lambda x: -len(x[0]))
    if not pairs:
        return None

    def resolve(path):
        p = (path or "").replace("\\", "/").lstrip("/")
        for prefix, name in pairs:
            if p == prefix or p.startswith(prefix + "/"):
                return name
        segs = [x for x in p.split("/") if x]
        return segs[0] if segs else "?"
    return resolve


# ------------------------------------------------------------------ loaders --
def load_gt(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    inb = [rec(e["service"], e["http_method"], e["path_declared"],
               e["class"], e["method"], e["id"]) for e in d["inbound_endpoints"]]
    out = [rec(o["caller_service"], o["http_method"], o["path_declared"],
               o["class"], o["method"], o["id"],
               {"mechanism": o["mechanism"]}) for o in d["outbound_calls"]]
    return inb, out, d


def load_cimet(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    inb, out = [], []
    for ms in d["microservices"]:
        for b in CIMET_BUCKETS:
            for cls in ms.get(b) or []:
                for m in cls.get("methods") or []:
                    if m.get("type") == "Endpoint":
                        inb.append(rec(ms["name"], m.get("httpMethod"), m.get("url"),
                                       cls["name"], m.get("name"), f"cimet:{b}",
                                       {"file": cls.get("path") or ""}))
                    for mc in m.get("methodCalls") or []:
                        if mc.get("type") == "RestCall":
                            out.append(rec(ms["name"], mc.get("httpMethod"), mc.get("url"),
                                           cls["name"], m.get("name"), f"cimet:{b}",
                                           {"file": cls.get("path") or ""}))
    meta = {"extractor": "CIMET", "version": d.get("version") or "1.2.1"}
    return inb, out, meta


def load_llm(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    inb = []
    for f in d.get("files", []):
        for e in f.get("endpoints", []):
            fp = e.get("_file") or f.get("path") or ""
            segs = [s for s in fp.replace("\\", "/").split("/") if s]
            inb.append(rec(segs[0] if segs else "?", e.get("httpMethod"), e.get("path"),
                           e.get("className"), e.get("methodName"), "llm",
                           {"confidence": e.get("confidence"), "file": fp}))
    run = d.get("_run", {})
    name = run.get("model", "?").split("/")[-1]
    name += " agent" if run.get("workflow") == "agent" else " per-file"
    if run.get("effort") not in (None, "default"):
        name += f" (effort {run['effort']})"
    return inb, [], {"extractor": f"LLM {name}", **run}


def load_any(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if "microservices" in raw:
        return load_cimet(path)
    if "files" in raw:
        return load_llm(path)
    sys.exit(f"unrecognised format: {path}")


# ------------------------------------------------------------------ matching --
LEVELS = {
    "M1 exact":      lambda r: (r["service"], r["verb"], r["declared"]),
    "M2 normalized": lambda r: (r["service"], r["verb"], r["path"]),
    "M3 path only":  lambda r: (r["service"], r["path"]),
    # Leading underscores are stripped on both sides: the xs2a generated
    # interfaces annotate _getAccountList and the controller overrides
    # getAccountList, and an extractor may legitimately report either name.
    "M4 code":       lambda r: (r["service"], r["cls"], (r["method"] or "").lstrip("_")),
}


def score(ref, pred, keyfn):
    """Multiset-aware: a duplicated prediction is a false positive."""
    cr, cp = Counter(keyfn(r) for r in ref), Counter(keyfn(r) for r in pred)
    tp = sum((cr & cp).values())
    fp, fn = sum(cp.values()) - tp, sum(cr.values()) - tp
    # With no predictions precision is undefined, not zero - and so is F1.
    # Reporting 0.0 there would read as "everything it said was wrong" when in
    # fact it said nothing.
    p = tp / len(pred) if pred else None
    r = tp / len(ref) if ref else None
    f = (2 * p * r / (p + r) if (p + r) else 0.0) if (p is not None and r is not None) else None
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": p, "recall": r, "f1": f,
            "only_pred": sorted((cp - cr).elements()),
            "only_ref": sorted((cr - cp).elements())}


def num(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def dup_rate(rows, keyfn):
    c = Counter(keyfn(r) for r in rows)
    n = sum(v - 1 for v in c.values() if v > 1)
    return n, (n / len(rows) if rows else 0.0)


# -------------------------------------------------------------------- report --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True, help="CIMET IR or LLM IR json")
    ap.add_argument("--gt", default=str(HERE / "groundtruth" / "movie-recommendation.gt.json"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    gt_in, gt_out, gt_doc = load_gt(a.gt)
    p_in, p_out, meta = load_any(a.pred)

    resolve = service_resolver(gt_doc)
    if resolve and meta.get("extractor", "").startswith("LLM"):
        for r in p_in + p_out:
            r["service"] = resolve(r.get("file"))

    in_frame, frame_def = frame_filter(gt_doc)
    if in_frame:
        p_in_all, p_out_all = p_in, p_out
        p_in = [r for r in p_in_all if in_frame(r.get("file"))]
        p_out = [r for r in p_out_all if in_frame(r.get("file"))]
        outside_in = [r for r in p_in_all if not in_frame(r.get("file"))]
        outside_out = [r for r in p_out_all if not in_frame(r.get("file"))]
    else:
        outside_in, outside_out = [], []

    L, w = [], None
    L = []
    w = L.append
    name = meta.get("extractor", "?")
    w(f"# {name} vs. ground truth\n")
    w(f"- ground truth: `{Path(a.gt).name}` — "
      f"{gt_doc['meta']['system']} @ `{gt_doc['meta']['commit'][:8]}`, "
      f"labeled {gt_doc['meta']['labeled_on']}")
    w(f"- prediction: `{Path(a.pred).name}`")
    if "model" in meta:
        w(f"- model `{meta['model']}`, temperature {meta.get('temperature')}, "
          f"prompt `{meta.get('prompt_file')}`")
        w(f"- {meta.get('input_tokens')} in / {meta.get('output_tokens')} out tokens, "
          f"list price ${meta.get('list_price_usd')}, wall {meta.get('wall_seconds')} s, "
          f"schema-valid {meta.get('schema_valid_files')}/{meta.get('n_files')}")
    w(f"- ground truth: {len(gt_in)} inbound endpoints, {len(gt_out)} outbound calls")
    w(f"- prediction: {len(p_in)} inbound endpoints, {len(p_out)} outbound calls\n")

    # ---- inbound, four levels ---------------------------------------------
    w("## Inbound endpoints\n")
    w("| level | tp | fp | fn | precision | recall | F1 |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    results = {}
    for lvl, kf in LEVELS.items():
        m = results[lvl] = score(gt_in, p_in, kf)
        w(f"| {lvl} | {m['tp']} | {m['fp']} | {m['fn']} | "
          f"{num(m['precision'])} | {num(m['recall'])} | {num(m['f1'])} |")
    w("")

    for lvl in LEVELS:
        m = results[lvl]
        if not (m["only_pred"] or m["only_ref"]):
            continue
        w(f"### {lvl} — disagreements\n")
        for k in m["only_ref"]:
            w(f"- **missed** `{' '.join(str(x) for x in k)}`")
        for k in m["only_pred"]:
            w(f"- **extra**  `{' '.join(str(x) for x in k)}`")
        w("")

    # ---- what are the extra inbound predictions, really? -------------------
    k2 = LEVELS["M2 normalized"]
    k4 = LEVELS["M4 code"]
    gt_in_k2, gt_in_k4 = {k2(r) for r in gt_in}, {k4(r) for r in gt_in}
    gt_out_k2, gt_out_k4 = {k2(r) for r in gt_out}, {k4(r) for r in gt_out}
    surplus = [r for r in p_in if k4(r) not in gt_in_k4 and k2(r) not in gt_in_k2]
    role_err = [r for r in surplus if k4(r) in gt_out_k4 or k2(r) in gt_out_k2]
    halluc = [r for r in surplus if r not in role_err]

    w("## Where the surplus inbound predictions belong\n")
    w("| category | n | rate |")
    w("|---|---:|---:|")
    w(f"| surplus over ground truth | {len(surplus)} | "
      f"{len(surplus)/len(p_in) if p_in else 0:.1%} |")
    w(f"| of which are ground-truth **outbound** calls (role-separation error) | "
      f"{len(role_err)} | {len(role_err)/len(p_in) if p_in else 0:.1%} |")
    w(f"| of which match nothing anywhere (**hallucination**) | "
      f"{len(halluc)} | {len(halluc)/len(p_in) if p_in else 0:.1%} |\n")
    for r in role_err:
        w(f"- role-separation: `{r['service']} {r['verb']} {r['declared']}` "
          f"({r['cls']}.{r['method']})")
    for r in halluc:
        w(f"- hallucination: `{r['service']} {r['verb']} {r['declared']}` "
          f"({r['cls']}.{r['method']})")
    if role_err or halluc:
        w("")

    if outside_in or outside_out:
        w("## Predictions outside the frame (not scored)\n")
        w(f"| service | verb | path | class.method |")
        w(f"|---|---|---|---|")
        for r in sorted(outside_in + outside_out,
                        key=lambda x: (x["service"], x["path"], x["verb"])):
            w(f"| {r['service']} | {r['verb']} | `{r['declared']}` | "
              f"{r['cls']}.{r['method']} |")
        w("")

    # ---- outbound, if the extractor emits it -------------------------------
    if p_out:
        w("## Outbound calls\n")
        w("| level | tp | fp | fn | precision | recall | F1 |")
        w("|---|---:|---:|---:|---:|---:|---:|")
        out_res = {}
        for lvl, kf in LEVELS.items():
            m = out_res[lvl] = score(gt_out, p_out, kf)
            w(f"| {lvl} | {m['tp']} | {m['fp']} | {m['fn']} | "
              f"{num(m['precision'])} | {num(m['recall'])} | {num(m['f1'])} |")
        w("")
        for lvl in LEVELS:
            m = out_res[lvl]
            if not (m["only_pred"] or m["only_ref"]):
                continue
            w(f"### {lvl} — disagreements\n")
            for k in m["only_ref"]:
                w(f"- **missed** `{' '.join(str(x) for x in k)}`")
            for k in m["only_pred"]:
                w(f"- **extra**  `{' '.join(str(x) for x in k)}`")
            w("")
    else:
        w("## Outbound calls\n")
        w(f"This extractor emits no outbound calls; the ground truth has "
          f"{len(gt_out)}. Not scored.\n")

    # ---- other metrics -----------------------------------------------------
    dn2, dr2 = dup_rate(p_in, k2)
    dn4, dr4 = dup_rate(p_in, k4)
    w("## Other metrics\n")
    w("| metric | value |")
    w("|---|---:|")
    w(f"| duplicate inbound predictions (M2 key) | {dn2} ({dr2:.1%}) |")
    w(f"| duplicate inbound predictions (M4 key) | {dn4} ({dr4:.1%}) |")
    if "schema_valid_files" in meta:
        w(f"| schema validity | {meta['schema_valid_files']}/{meta['n_files']} = "
          f"{meta['schema_valid_files']/max(meta['n_files'],1):.1%} |")
        w(f"| wall time | {meta.get('wall_seconds')} s |")
        w(f"| list-price cost | ${meta.get('list_price_usd')} |")
    else:
        w("| schema validity | n/a (deterministic) |")
    conf = Counter(r.get("confidence") for r in p_in if r.get("confidence"))
    if conf:
        w(f"| confidence high/medium/low | {conf.get('high',0)}/"
          f"{conf.get('medium',0)}/{conf.get('low',0)} |")
    w("")

    # ---- per service -------------------------------------------------------
    w("## Per service (inbound, M2)\n")
    w("| service | ground truth | predicted | matched |")
    w("|---|---:|---:|---:|")
    for s in sorted({r["service"] for r in gt_in} | {r["service"] for r in p_in}):
        g = Counter(k2(r) for r in gt_in if r["service"] == s)
        p = Counter(k2(r) for r in p_in if r["service"] == s)
        w(f"| {s} | {sum(g.values())} | {sum(p.values())} | {sum((g & p).values())} |")
    w("")

    txt = "\n".join(L)
    out = Path(a.out) if a.out else HERE / "out" / f"eval.{Path(a.pred).stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt, encoding="utf-8")
    print(txt)
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
