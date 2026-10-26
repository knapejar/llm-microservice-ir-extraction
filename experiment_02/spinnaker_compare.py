#!/usr/bin/env python3
"""Spinnaker: every inbound endpoint any extractor found, side by side.

Sources are the agent runs of each model on the ten service units (out/pool) and
CIMET's IR if given.  An endpoint is a service, a verb and a normalized route.
Verdicts from the manual review (spinnaker_review.json) are attached by that key.

Writes
  ../docs/spinnaker/data.json                 the table of ../docs/spinnaker/index.html
  ../experiment_01/groundtruth/spinnaker.gt.json   draft ground truth: endpoints every
      finished run found, plus the review's verdicts on the rest
  out/agent_ir.spinnaker.<model>.json         the ten units of a model as one run
  ../experiment_01/baseline/IR-spinnaker.cimet.json   CIMET's endpoints, named "spinnaker"
so that ../experiment_01/build_viewer.py scores them all like the other systems.

    python spinnaker_compare.py [--cimet <CIMET IR of the spinnaker repository>]
"""
import argparse, json, sys
from collections import Counter
from pathlib import Path

from agent_extract import HERE, norm_route

sys.path.insert(0, str(HERE.parent / "experiment_01" / "groundtruth"))
from validate import norm_path

COMMIT = "d2eaa598c95d0a8e17736f2df61fa1fa9f738b53"
CIMET_VERSION = "main d8fbbe4"
UNITS = {"gate-web": "gate/gate-web", **{s: s for s in ("orca", "clouddriver", "front50", "echo", "fiat",
                                                          "igor", "kayenta", "keel", "rosco")}}
RUNS = {"DeepSeek-V4.1-Flash": "DeepSeek-V4.1-Flash-1017.low",    # source -> run file suffix
        "GLM-5.3-Flash": "GLM-5.3-Flash.default",
        "Opus 5.5": "opus-5.5.cli"}
EXP1 = HERE.parent / "experiment_01"


def service(unit_dir):
    return unit_dir.split("/")[0]


def add(rows, src, svc, verb, path, file, line, evidence, cls, method):
    verb = "ANY" if verb in (None, "", "ALL") else verb.upper()
    key = f"{svc} {verb} {norm_route(path)}"
    row = rows.setdefault(key, {"key": key, "service": svc, "method": verb, "route": path, "by": {}})
    row["by"].setdefault(src, {"path": path, "file": file, "line": line, "evidence": evidence,
                               "class": cls, "handler": method})


def ground_truth(endpoints, rows, runs, sources):
    """Draft ground truth: an endpoint every finished run on its service found, or one the
    review confirms.  A run that was not accepted stopped early and has no say."""
    finished = {(r["source"], r["service"]) for r in runs if r.get("accepted") is not False}
    eps, excluded = [], []
    for e in endpoints:
        voters = [s for s in sources if (s, e["service"]) in finished]
        rv = e.get("review")
        if rv and rv["ok"] is not True:
            excluded.append({"id": f"X-{len(excluded) + 1:02d}", "kind": "not_an_endpoint" if rv["ok"] is False else "debatable",
                             "what": f"{e['service']} {e['method']} {e['route'] or '/'} (found by {', '.join(e['by']) or 'none'})",
                             "reason": rv["note"], "revisit_if": "the review of this entry changes"})
            continue
        if not rv and not (e["by"] and all(s in e["by"] for s in voters)):
            raise SystemExit(f"no verdict for the disagreement {e['key']!r}: add it to spinnaker_review.json")
        src = e["by"] or rows[rv["like"]]["by"]
        v = next(src[s] for s in ["Opus 5.5", "DeepSeek-V4.1-Flash", "GLM-5.3-Flash", "CIMET"] if s in src)
        eps.append({"id": f"ep-{len(eps) + 1:03d}", "service": e["service"], "http_method": e["method"],
                    "path_declared": (rv or {}).get("path") or e["route"] or "/", "class": v["class"], "method": v["handler"],
                    "file": v["file"], "line_method_annotation": v["line"], "evidence": v["evidence"],
                    "found_by": sorted(e["by"]), "notes": rv["note"] if rv else "every finished run found it"})
        eps[-1]["path_normalized"] = norm_path(eps[-1]["path_declared"])
    per_svc = Counter(e["service"] for e in eps)
    return {"schema_version": "1.0",
            "meta": {"system": "spinnaker", "repository": "https://github.com/spinnaker/spinnaker", "commit": COMMIT,
                     "language": "Java, Groovy, Kotlin", "frameworks": ["Spring MVC", "Servlet"],
                     "labeled_by": "draft: agreement of the finished runs, disagreements checked by hand",
                     "labeled_on": "2026-10-26", "draft": True,
                     "scope": "inbound endpoints of ten services; for gate only the gate-web module",
                     "frame": {"kind": "whole_system", "definition": "src/main of the ten service directories"}},
            "counts": {"inbound_endpoints": len(eps), "outbound_calls": 0, "excluded": len(excluded)},
            "services": [{"name": service(d), "module_dir": service(d), "inbound_endpoints": per_svc[service(d)]}
                         for d in UNITS.values()],
            "inbound_endpoints": eps, "outbound_calls": [], "excluded": excluded}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cimet")
    a = ap.parse_args()
    rows, runs = {}, []
    for src, suffix in RUNS.items():
        merged = {"system": "spinnaker", "files": [], "_run": {}}
        for unit, d in UNITS.items():
            f = HERE / "out" / "pool" / f"agent_ir.spinnaker-{unit}.{suffix}.json"
            if not f.exists():
                continue
            doc = json.loads(f.read_text(encoding="utf-8"))
            r = doc["_run"]
            n = 0
            for file in doc["files"]:
                for e in file["endpoints"]:
                    add(rows, src, service(d), e["httpMethod"], e["path"], f"{d}{file['path']}", e["line"], e["evidence"],
                        e.get("className"), e.get("methodName"))
                    n += 1
                merged["files"].append({**file, "path": f"{d}{file['path']}"})
            runs.append({"source": src, "service": service(d), "entries": n, "accepted": r.get("accepted"),
                         "steps": r.get("steps"), "price_usd": r.get("list_price_usd")})
            m = merged["_run"]
            m.update({k: r[k] for k in ("model", "workflow", "effort", "temperature") if k in r})
            for k in ("steps", "input_tokens", "output_tokens", "wall_seconds", "list_price_usd"):
                if r.get(k) is not None:
                    m[k] = round(m.get(k, 0) + r[k], 4)
            m["units"] = m.get("units", 0) + 1
            m["accepted_units"] = m.get("accepted_units", 0) + bool(r.get("accepted"))
        if merged["files"]:
            (HERE / "out" / f"agent_ir.spinnaker.{suffix}.json").write_text(
                json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.cimet:
        doc = json.loads(Path(a.cimet).read_text(encoding="utf-8"))
        slim = []
        for ms in doc["microservices"]:
            svc, classes = service(ms["path"].strip("/")), []
            for b in ("controllers", "services", "repositories", "entities", "unknowns", "feignClients"):
                for cls in ms.get(b) or []:
                    eps = [{k: m.get(k) for k in ("type", "name", "url", "httpMethod")}
                           for m in cls.get("methods") or [] if m.get("type") == "Endpoint"]
                    for m in eps:
                        add(rows, "CIMET", svc, m["httpMethod"], m["url"], cls["path"].lstrip("/"), None,
                            f"{cls['name']}.{m['name']}", cls["name"], m["name"])
                    if eps:
                        classes.append({"name": cls["name"], "path": cls["path"], "methods": eps})
            runs.append({"source": "CIMET", "service": svc, "entries": sum(len(c["methods"]) for c in classes)})
            slim.append({"name": ms["name"], "path": ms["path"], "controllers": classes})
        (EXP1 / "baseline" / "IR-spinnaker.cimet.json").write_text(json.dumps(
            {"name": "spinnaker", "version": CIMET_VERSION, "microservices": slim}, indent=1), encoding="utf-8")
    review = HERE / "spinnaker_review.json"
    verdicts = json.loads(review.read_text(encoding="utf-8")) if review.exists() else {}
    for k, v in verdicts.items():               # an endpoint no extractor got right is added by the review
        svc, verb, route = k.split(" ", 2)
        rows.setdefault(k, {"key": k, "service": svc, "method": verb, "route": v.get("path", route), "by": {}})["review"] = v
    endpoints = sorted(rows.values(), key=lambda r: (r["service"], r["key"].split(" ", 2)[2], r["method"]))
    sources = [s for s in [*RUNS, "CIMET"] if any(r["source"] == s for r in runs)]
    out = HERE.parent / "docs" / "spinnaker" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"commit": COMMIT, "sources": sources, "runs": runs, "endpoints": endpoints},
                              indent=0, ensure_ascii=False), encoding="utf-8")
    gt = ground_truth(endpoints, rows, runs, sources)
    (EXP1 / "groundtruth" / "spinnaker.gt.json").write_text(json.dumps(gt, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(rows)} endpoints -> {out}; draft ground truth {len(gt['inbound_endpoints'])}, excluded {len(gt['excluded'])}")
    for s in sources:
        print(s, sum(s in r["by"] for r in rows.values()))


if __name__ == "__main__":
    main()
