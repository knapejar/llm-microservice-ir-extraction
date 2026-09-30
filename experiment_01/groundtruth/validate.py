#!/usr/bin/env python3
"""Self-checks for a ground-truth file, a cross-check against the source it
describes, and an optional diff against a CIMET IR.

The point is that the ground truth must be checkable, not just asserted.
Two independent layers:

  structural  -- internal consistency (counts, ids, normalization, references)
  source      -- every entry is re-read at the file and line it names, and its
                 verb, path and handler name must actually be there

The source layer is a *check*, not a generator: it verifies a hand-written
claim against the file. It never produces an entry.

    python groundtruth/validate.py                       # movie
    python groundtruth/validate.py --gt groundtruth/xs2a.gt.json --repo clone/xs2a
    python groundtruth/validate.py --all
"""
import argparse, json, re, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os

# Checkouts and the CIMET IRs too large to commit live outside the repo:
# $CLONE_DIR (default ../clone) and $CIMET_DIR (default ../baseline).
CLONE = Path(os.environ.get("CLONE_DIR", HERE.parent / "clone"))
CIMET = Path(os.environ.get("CIMET_DIR", HERE.parent / "baseline"))

# gt file -> (repo dir, cimet IR) for --all
SUITE = {
    "movie-recommendation.gt.json": (CLONE / "spring-cloud-movie-recommendation",
                                     HERE.parent / "baseline" / "IR-movie.cimet.json"),
    "geoserver-cloud.gt.json":      (CLONE / "geoserver-cloud",
                                     HERE.parent / "baseline" / "IR-geoserver-cloud.cimet.json"),
    "xs2a.gt.json":                 (CLONE / "xs2a", CIMET / "IR-xs2a.json"),
}

VERB_ANNOTATION = {"GET": "GetMapping", "POST": "PostMapping", "PUT": "PutMapping",
                   "DELETE": "DeleteMapping", "PATCH": "PatchMapping"}


def norm_path(p):
    """README.md section 4. Property placeholders resolve to their default
    (rule 4.0) before anything else; braces collapse before the query split."""
    p = (p or "").strip()
    p = re.sub(r"\$\{[^}:]*:([^}]*)\}", r"\1", p)   # ${prop:default} -> default
    p = re.sub(r"\$\{[^}]*\}", "", p)               # ${prop} with no default -> ""
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


def load_cimet(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    eps, rcs = [], []
    for ms in d["microservices"]:
        for bucket in ("controllers", "services", "repositories",
                       "entities", "unknowns", "feignClients"):
            for cls in ms.get(bucket) or []:
                for m in cls.get("methods") or []:
                    if m.get("type") == "Endpoint":
                        eps.append((ms["name"], (m.get("httpMethod") or "").upper(),
                                    norm_path(m.get("url"))))
                    for mc in m.get("methodCalls") or []:
                        if mc.get("type") == "RestCall":
                            rcs.append((ms["name"], (mc.get("httpMethod") or "").upper(),
                                        norm_path(mc.get("url"))))
    return Counter(eps), Counter(rcs)


# ------------------------------------------------------------- structural ----
def structural(gt, check):
    ep = gt["inbound_endpoints"]
    oc = gt["outbound_calls"]
    ex = gt["excluded"]

    c = gt["counts"]
    check("declared counts match the arrays",
          (c["inbound_endpoints"], c["outbound_calls"], c["excluded"])
          == (len(ep), len(oc), len(ex)), (len(ep), len(oc), len(ex)))

    bad = [(e["id"], e["path_normalized"], norm_path(e["path_declared"]))
           for e in ep + oc if e["path_normalized"] != norm_path(e["path_declared"])]
    check("path_normalized follows the normalization rule", not bad, bad)

    bad = [(e["id"], e["path_class_level"] + e["path_method_level"], e["path_declared"])
           for e in ep if "path_class_level" in e
           and e["path_class_level"] + e["path_method_level"] != e["path_declared"]]
    check("class-level + method-level compose to path_declared", not bad, bad)

    ids = [x["id"] for x in ep + oc + ex]
    check("ids are unique", len(ids) == len(set(ids)),
          [k for k, v in Counter(ids).items() if v > 1])

    per_svc = Counter(e["service"] for e in ep)
    bad = [s["name"] for s in gt["services"]
           if s["inbound_endpoints"] != per_svc.get(s["name"], 0)]
    check("per-service counts match the endpoint list", not bad, bad)

    unknown = sorted(set(per_svc) - {s["name"] for s in gt["services"]})
    check("every endpoint's service is declared", not unknown, unknown)

    epids = {e["id"] for e in ep}
    bad = [o["id"] for o in oc
           if o.get("resolves_to_endpoint") and o["resolves_to_endpoint"] not in epids]
    check("resolves_to_endpoint references exist", not bad, bad)

    bad = []
    for o in oc:
        t = o.get("resolves_to_endpoint")
        if not t:
            continue
        e = next(x for x in ep if x["id"] == t)
        if (e["path_normalized"], e["service"], e["http_method"]) != \
           (o["path_normalized"], o["target_service"], o["http_method"]):
            bad.append((o["id"], t))
    check("each resolved call really hits its endpoint's route", not bad, bad)

    bad = [e["id"] for e in ep + oc if not e.get("evidence")]
    check("every entry carries evidence", not bad, bad)

    bad = [e["id"] for e in ex if not e.get("reason") or not e.get("revisit_if")]
    check("every exclusion carries a reason and a revisit condition", not bad, bad)


# ------------------------------------------------------------ source check ---
def source_check(gt, repo, check):
    """Re-read every entry at the file and line it claims, and verify it."""
    repo = Path(repo)
    if not repo.exists():
        print(f"[skip] source cross-check: {repo} not found")
        return

    missing_files, bad_path, bad_verb, bad_handler = [], [], [], []
    for e in gt["inbound_endpoints"] + gt["outbound_calls"]:
        f = repo / e["file"]
        if not f.exists():
            missing_files.append((e["id"], e["file"]))
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        ln = e.get("line_method_annotation")
        if not ln or ln > len(lines):
            continue
        window = "\n".join(lines[ln - 1: ln + 12])
        # a method-level annotation with no value inherits the class-level path,
        # so the evidence for it sits at the class annotation instead
        cl = e.get("line_class_annotation")
        if cl and cl <= len(lines):
            window += "\n" + "\n".join(lines[cl - 1: cl + 3])

        # The declared route must be at one of those lines. A URL built by
        # concatenation only contains its literal prefix, so compare that much.
        needle = e.get("path_method_level") or e.get("path_class_level") or e["path_declared"]
        needle = re.sub(r"^https?://", "", needle).split("{")[0]
        if needle and needle not in window:
            alt = re.sub(r"^https?://", "", e["path_declared"]).split("{")[0]
            if alt not in window:
                bad_path.append((e["id"], needle, lines[ln - 1].strip()[:90]))

        # the verb: @XMapping, RequestMethod.X (annotations) or HttpMethod.X
        # (a RestTemplate/WebClient call site)
        verb = e["http_method"]
        if e.get("http_method_inferred"):
            continue          # verb is not in the source; the entry says so
        ann = VERB_ANNOTATION.get(verb, "")
        if (f"RequestMethod.{verb}" not in window
                and f"HttpMethod.{verb}" not in window
                and (not ann or ann not in window)):
            bad_verb.append((e["id"], verb, lines[ln - 1].strip()[:90]))

        # the handler name must be at the line the entry points to
        hl = e.get("line_handler")
        if hl and hl <= len(lines) and e["method"] not in lines[hl - 1]:
            bad_handler.append((e["id"], e["method"], lines[hl - 1].strip()[:90]))

    check("every referenced source file exists", not missing_files, missing_files)
    check("declared path is present at the stated line", not bad_path, bad_path)
    check("HTTP method is evidenced at the stated line", not bad_verb, bad_verb)
    check("handler name is at the stated line", not bad_handler, bad_handler)

    # frame exhaustiveness: no mapping annotation outside the labeled files
    frame = (gt["meta"].get("frame") or {}).get("definition")
    if frame and gt["meta"]["frame"].get("exhaustive"):
        root = repo / frame.split("/**")[0].rstrip("/") if "**" in frame else repo
        labeled = {(repo / e["file"]).resolve()
                   for e in gt["inbound_endpoints"] + gt["outbound_calls"]}
        pat = re.compile(r"@(RequestMapping|GetMapping|PostMapping|PutMapping|"
                         r"DeleteMapping|PatchMapping)\b")
        stray = []
        for p in root.rglob("*.java"):
            s = p.as_posix()
            if "/src/test/" in s or "/target/" in s or "/build/" in s:
                continue
            if "/src/main/" not in s:
                continue
            if p.resolve() in labeled:
                continue
            if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                stray.append(p.relative_to(repo).as_posix())
        check("no mapping annotation outside the labeled files (frame is exhaustive)",
              not stray, stray[:10])


# -------------------------------------------------------------- cimet diff ---
def cimet_diff(gt, cimet_path):
    if not Path(cimet_path).exists():
        print(f"\n[skip] no CIMET IR at {cimet_path}")
        return
    C_ep, C_rc = load_cimet(cimet_path)
    G_ep = Counter((e["service"], e["http_method"], e["path_normalized"])
                   for e in gt["inbound_endpoints"])
    G_rc = Counter((o["caller_service"], o["http_method"], o["path_normalized"])
                   for o in gt["outbound_calls"])
    print(f"\n--- diff vs CIMET ({Path(cimet_path).name}) ---")
    frame = gt["meta"].get("frame", {})
    if frame.get("kind") not in (None, "whole_system"):
        print(f"    frame: {frame.get('definition')} — CIMET rows outside it are "
              f"listed but are not errors")
    print(f"inbound   GT {sum(G_ep.values())}  CIMET {sum(C_ep.values())}")
    miss = sorted((G_ep - C_ep).elements())
    extra = sorted((C_ep - G_ep).elements())
    print(f"  missed by CIMET ({len(miss)}):")
    for k in miss[:60]:
        print(f"    {k[0]:14s} {k[1]:7s} {k[2]}")
    if len(miss) > 60:
        print(f"    ... and {len(miss)-60} more")
    print(f"  in CIMET, not in GT ({len(extra)}):")
    for k in extra[:20]:
        print(f"    {k[0]:14s} {k[1]:7s} {k[2]}")
    if gt["outbound_calls"] or sum(C_rc.values()):
        print(f"outbound  GT {sum(G_rc.values())}  CIMET {sum(C_rc.values())}   "
              f"missed: {sorted((G_rc - C_rc).elements()) or 'none'}   "
              f"extra: {sorted((C_rc - G_rc).elements()) or 'none'}")


def run_one(gt_path, repo, cimet):
    gt = json.loads(Path(gt_path).read_text(encoding="utf-8"))
    fails = []

    def check(name, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {name}"
              f"{('  -> ' + str(detail)) if not ok else ''}")
        if not ok:
            fails.append(name)

    m = gt["meta"]
    print(f"\n{'='*74}\nground truth : {Path(gt_path).name}")
    print(f"system       : {m['system']} @ {m['commit'][:8]}")
    print(f"labeled      : {m['labeled_by']}, {m['labeled_on']}")
    fr = m.get("frame", {})
    if fr:
        print(f"frame        : {fr.get('definition')}  "
              f"(exhaustive={fr.get('exhaustive')})")
    print()
    structural(gt, check)
    if repo:
        source_check(gt, repo, check)
    if cimet:
        cimet_diff(gt, cimet)
    print(f"\n{len(fails)} failed check(s)" if fails else "\nall checks passed")
    return len(fails)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default=str(HERE / "movie-recommendation.gt.json"))
    ap.add_argument("--repo", default=None)
    ap.add_argument("--cimet", default=None)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    if a.all:
        total = 0
        for name, (repo, cimet) in SUITE.items():
            total += run_one(HERE / name, repo, cimet)
        print(f"\n{'='*74}\nsuite: {total} failed check(s)" if total
              else f"\n{'='*74}\nsuite: all checks passed")
        return 1 if total else 0

    repo, cimet = SUITE.get(Path(a.gt).name, (None, None))
    return 1 if run_one(a.gt, a.repo or repo, a.cimet or cimet) else 0


if __name__ == "__main__":
    sys.exit(main())
