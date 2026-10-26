#!/usr/bin/env python3
"""Merge the pool runs of all models into one baseline per system.

Every endpoint (method + normalized route) gets the models that found it.  Runs of
one model are unioned first - its efforts, reruns and the units a big system was
split into - so a vote means "this model found it in some run".  An endpoint found
by every model that ran on the system is a baseline candidate; the rest is the
list to check by hand.

    python merge_runs.py [out/pool]   -> out/pool/baseline/<system>.json + summary
"""
import json, sys
from collections import defaultdict
from pathlib import Path

from agent_extract import norm_route

SPLIT = ("camunda", "inlong", "kapua")        # modules of one system: merged into it
SERVICES = ("spinnaker-", "openlmis-")         # one unit per service: kept apart, the same
RENAME = {"spinnaker-gate-web": "spinnaker-gate"}   # route in two services is two endpoints


def group_of(unit, path):
    """The baseline an endpoint belongs to: its service for Spinnaker and OpenLMIS,
    else its system."""
    if unit == "openlmis":              # whole-system run: the repos are mounted side by side
        return path.split("/")[1]
    unit = RENAME.get(unit, unit)
    if unit.startswith(SERVICES):
        return unit
    return next((p for p in SPLIT if unit == p or unit.startswith(p + "-")), unit)


def main():
    pool = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "out" / "pool")
    found = defaultdict(lambda: defaultdict(dict))     # system -> key -> model -> endpoint
    for f in sorted(pool.glob("agent_ir.*.json")):
        if f.name.endswith(".messages.json"):
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        model = doc["_run"]["model"]
        for file in doc["files"]:
            system = group_of(doc["system"], file["path"])
            for e in file["endpoints"]:
                key = f"{e['httpMethod']} {norm_route(e['path'])}"
                found[system][key].setdefault(model, {"path": e["path"], "file": file["path"],
                                                      "line": e["line"], "evidence": e["evidence"]})
    out = pool / "baseline"
    out.mkdir(exist_ok=True)
    print("| system | endpoints | " + " | ".join(["models", "all agree", "one model only"]) + " |")
    print("|---|---:|---|---:|---:|")
    for system, keys in sorted(found.items()):
        models = sorted({m for v in keys.values() for m in v})
        rows = [{"key": k, "models": sorted(v), "agreed": len(v) == len(models), **next(iter(v.values()))}
                for k, v in sorted(keys.items())]
        (out / f"{system}.json").write_text(json.dumps({"system": system, "models": models, "endpoints": rows},
                                                       indent=1, ensure_ascii=False), encoding="utf-8")
        agreed = sum(r["agreed"] for r in rows)
        print(f"| {system} | {len(rows)} | {', '.join(m.split('-')[0] for m in models)} | {agreed} | {len(rows) - agreed} |")


if __name__ == "__main__":
    main()
