#!/usr/bin/env python3
"""Build out/viewer.html: viewer.template.html with the raw input files bundled
in, so the page works offline as a single file.

All loading, service resolution, frame filtering, matching and classification
happen in the page itself (a port of evaluate.py), so the bundled page and a
page with files loaded by hand run the same code and show the same numbers.
The template also works unbuilt: open it and load the files there.

    python build_viewer.py [--cimet-dir DIR]

Bundled: groundtruth/*.gt.json, the CIMET IRs (baseline/ first, then
--cimet-dir; the xs2a IR is 63 MB and is not committed), every out/llm_ir*.json
and ../experiment_02/out/agent_ir*.json.  CIMET IRs are cut down to the classes
that carry an endpoint or a REST call, which is all the page reads.
"""
import argparse, json, re
from pathlib import Path

import evaluate as ev

HERE = Path(__file__).resolve().parent
EXP2 = HERE.parent / "experiment_02" / "out"
CIMET_NAMES = ["IR-movie.cimet.json", "IR-movie.json", "IR-xs2a.cimet.json", "IR-xs2a.json",
               "IR-geoserver-cloud.cimet.json", "IR-geoserver-cloud.json"]


def slim_cimet(d):
    mss = []
    for ms in d["microservices"]:
        s = {"name": ms["name"]}
        for b in ev.CIMET_BUCKETS:
            classes = []
            for c in ms.get(b) or []:
                meths = []
                for m in c.get("methods") or []:
                    calls = [{k: mc.get(k) for k in ("type", "name", "objectName", "objectType", "url", "httpMethod")}
                             for mc in m.get("methodCalls") or [] if mc.get("type") == "RestCall"]
                    if m.get("type") == "Endpoint" or calls:
                        meths.append({"type": m.get("type"), "name": m.get("name"), "url": m.get("url"),
                                      "httpMethod": m.get("httpMethod"), "methodCalls": calls})
                if meths:
                    classes.append({"name": c["name"], "path": c.get("path"), "methods": meths})
            s[b] = classes
        mss.append(s)
    return {"name": d.get("name"), "version": d.get("version"), "microservices": mss}


def collect(cimet_dirs):
    files = [(HERE / "groundtruth" / n, "gt") for n in ("movie-recommendation.gt.json", "xs2a.gt.json", "geoserver-cloud.gt.json")]
    seen = set()
    for n in CIMET_NAMES:   # one CIMET IR per system: IR-x.cimet.json wins over IR-x.json
        p = next((d / n for d in cimet_dirs if (d / n).exists()), None)
        stem = n.split(".")[0]
        if p and stem not in seen:
            seen.add(stem)
            files.append((p, "cimet"))
    files += [(p, "run") for p in sorted(HERE.glob("out/llm_ir*.json"))]
    files += [(p, "run") for p in sorted(EXP2.glob("agent_ir*.json")) if not p.name.endswith(".messages.json")]
    out = []
    for p, kind in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:   # a run still being written
            print(f"skip {p.name}: {e}")
            continue
        if kind == "cimet":
            d = slim_cimet(d)
        elif kind == "run":
            d = {"system": d.get("system"), "_run": {k: v for k, v in (d.get("_run") or {}).items()
                                                      if k not in ("per_file", "trace", "repo", "provider")},
                 "files": [f for f in d.get("files", []) if f.get("endpoints")]}
        out.append({"name": p.name, "doc": d})
        print(f"  {kind:<5} {p.name}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cimet-dir", action="append", default=[])
    ap.add_argument("--out", default=str(HERE / "out" / "viewer.html"))
    ap.add_argument("--src-root", default=None,
                    help="folder holding the system checkouts (one directory per system name); "
                         "bundles the referenced source files for the preview and sets the "
                         "'Open in VS Code' paths. For a local build only - it writes local paths.")
    a = ap.parse_args()
    data = collect([HERE / "baseline"] + [Path(d) for d in a.cimet_dir])
    tpl = (HERE / "viewer.template.html").read_text(encoding="utf-8")
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    src = {}
    if a.src_root:
        refs = set(re.findall(r'"/?([^"]+\.java)"', js))
        for d in sorted(Path(a.src_root).iterdir()):
            files = {r: (d / r).read_text(encoding="utf-8", errors="replace") for r in refs if (d / r).is_file()}
            if files:
                src[d.name] = {"root": d.resolve().as_posix(), "files": files}
                print(f"source {d.name}: {len(files)} files")
    sj = json.dumps(src, ensure_ascii=False).replace("</", "<\\/")
    Path(a.out).write_text(tpl.replace("__DATA__", js).replace("__SRC__", sj), encoding="utf-8")
    print("->", a.out)


if __name__ == "__main__":
    main()
