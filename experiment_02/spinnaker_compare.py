#!/usr/bin/env python3
"""Spinnaker: every inbound endpoint any extractor found, side by side.

Sources are the agent runs of each model on the ten service units (out/pool) and
CIMET's IR if given.  An endpoint is a service, a verb and a normalized route.
Verdicts from the manual review (spinnaker_review.json) are attached by that key.
Writes ../docs/spinnaker/data.json, which ../docs/spinnaker/index.html shows.

    python spinnaker_compare.py [--cimet <CIMET IR of the spinnaker repository>]
"""
import argparse, json
from pathlib import Path

from agent_extract import HERE, norm_route

COMMIT = "d2eaa598c95d0a8e17736f2df61fa1fa9f738b53"
UNITS = {"gate-web": "gate/gate-web", **{s: s for s in ("orca", "clouddriver", "front50", "echo", "fiat",
                                                          "igor", "kayenta", "keel", "rosco")}}
RUNS = {"DeepSeek-V4.1-Flash": "DeepSeek-V4.1-Flash-1017.low",    # source -> run file suffix
        "GLM-5.3-Flash": "GLM-5.3-Flash.default",
        "Opus 5.5": "opus-5.5.cli"}


def service(unit_dir):
    return unit_dir.split("/")[0]


def add(rows, src, svc, verb, path, file, line, evidence):
    verb = "ANY" if verb in (None, "", "ALL") else verb.upper()
    key = f"{svc} {verb} {norm_route(path)}"
    row = rows.setdefault(key, {"key": key, "service": svc, "method": verb, "route": path, "by": {}})
    row["by"].setdefault(src, {"path": path, "file": file, "line": line, "evidence": evidence})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cimet")
    a = ap.parse_args()
    rows, runs = {}, []
    for src, suffix in RUNS.items():
        for unit, d in UNITS.items():
            f = HERE / "out" / "pool" / f"agent_ir.spinnaker-{unit}.{suffix}.json"
            if not f.exists():
                continue
            doc = json.loads(f.read_text(encoding="utf-8"))
            r = doc["_run"]
            n = 0
            for file in doc["files"]:
                for e in file["endpoints"]:
                    add(rows, src, service(d), e["httpMethod"], e["path"], f"{d}{file['path']}", e["line"], e["evidence"])
                    n += 1
            runs.append({"source": src, "service": service(d), "entries": n, "accepted": r.get("accepted"),
                         "steps": r.get("steps"), "price_usd": r.get("list_price_usd")})
    if a.cimet:
        doc = json.loads(Path(a.cimet).read_text(encoding="utf-8"))
        for ms in doc["microservices"]:
            svc, n = service(ms["path"].strip("/")), 0
            for b in ("controllers", "services", "repositories", "entities", "unknowns", "feignClients"):
                for cls in ms.get(b) or []:
                    for m in cls.get("methods") or []:
                        if m.get("type") == "Endpoint":
                            add(rows, "CIMET", svc, m.get("httpMethod"), m.get("url"),
                                cls["path"].lstrip("/"), None, f"{cls['name']}.{m.get('name')}")
                            n += 1
            runs.append({"source": "CIMET", "service": svc, "entries": n})
    review = HERE / "spinnaker_review.json"
    verdicts = json.loads(review.read_text(encoding="utf-8")) if review.exists() else {}
    for k, v in verdicts.items():               # an endpoint no extractor got right is added by the review
        svc, verb, route = k.split(" ", 2)
        rows.setdefault(k, {"key": k, "service": svc, "method": verb, "route": route, "by": {}})["review"] = v
    out = HERE.parent / "docs" / "spinnaker" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"commit": COMMIT, "sources": [s for s in [*RUNS, "CIMET"] if any(r["source"] == s for r in runs)],
                               "runs": runs, "endpoints": sorted(rows.values(), key=lambda r: (r["service"], r["key"].split(" ", 2)[2], r["method"]))},
                              indent=0, ensure_ascii=False), encoding="utf-8")
    print(f"{len(rows)} endpoints -> {out}")
    for s in {r["source"] for r in runs}:
        print(s, sum(s in r["by"] for r in rows.values()))


if __name__ == "__main__":
    main()
