#!/usr/bin/env python3
"""Cross-extractor summary: every prediction file scored against the same
ground truth, in one table per matching level.

    python summarize.py
    python summarize.py --pred baseline/IR-movie.cimet.json out/llm_ir.*.json
"""
import argparse, sys
from pathlib import Path

from evaluate import (LEVELS, dup_rate, frame_filter, load_any, load_gt,
                      num, score, service_resolver)

HERE = Path(__file__).resolve().parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_PREDS = [
    "baseline/IR-movie.cimet.json",
    "out/llm_ir.gemini-2.5-flash-lite.json",
    "out/llm_ir.gemini-3.5-flash-lite.json",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default=str(HERE / "groundtruth" / "movie-recommendation.gt.json"))
    ap.add_argument("--pred", nargs="*", default=DEFAULT_PREDS)
    ap.add_argument("--out", default=str(HERE / "out" / "eval.summary.md"))
    a = ap.parse_args()

    gt_in, gt_out, gt_doc = load_gt(a.gt)
    resolve = service_resolver(gt_doc)
    in_frame, frame_def = frame_filter(gt_doc)
    arms = []
    for p in a.pred:
        path = HERE / p if not Path(p).is_absolute() else Path(p)
        if not path.exists():
            print(f"[skip] {p}")
            continue
        p_in, p_out, meta = load_any(path)
        # same two corrections evaluate.py applies: an LLM has no service field,
        # so resolve it from the file path; and a framed ground truth cannot
        # judge predictions that fall outside its frame.
        if resolve and meta.get("extractor", "").startswith("LLM"):
            for r in p_in + p_out:
                r["service"] = resolve(r.get("file"))
        outside = 0
        if in_frame:
            outside = sum(1 for r in p_in + p_out if not in_frame(r.get("file")))
            p_in = [r for r in p_in if in_frame(r.get("file"))]
            p_out = [r for r in p_out if in_frame(r.get("file"))]
        arms.append({"name": meta.get("extractor", path.stem), "meta": meta,
                     "in": p_in, "out": p_out, "file": path.name, "outside": outside})

    L, w = [], None
    L = []
    w = L.append
    m = gt_doc["meta"]
    w("# Extractor comparison against manual ground truth\n")
    w(f"System `{m['system']}` @ `{m['commit'][:8]}`. Ground truth: "
      f"**{len(gt_in)} inbound endpoints**, **{len(gt_out)} outbound calls**, "
      f"labeled manually by {m['labeled_by']} on {m['labeled_on']}"
      + (f" ({m['files_read']}/{m['files_in_scope']} files read in full)."
         if m.get("files_read") else ".") + "\n")
    w("Matching levels are defined in `groundtruth/README.md` section 5. "
      "M2 is the operative level; M1 measures notation compatibility, not detection.\n")

    w("## Inbound endpoints — F1 per matching level\n")
    w("| extractor | found | M1 exact | M2 normalized | M3 path only | M4 code |")
    w("|---|---:|---:|---:|---:|---:|")
    for arm in arms:
        cells = []
        for lvl, kf in LEVELS.items():
            s = score(gt_in, arm["in"], kf)
            cells.append(num(s["f1"]))
        w(f"| {arm['name']} | {len(arm['in'])} | " + " | ".join(cells) + " |")
    w("")

    w("## Inbound endpoints — precision / recall at M2\n")
    w("| extractor | tp | fp | fn | precision | recall | F1 |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for arm in arms:
        s = score(gt_in, arm["in"], LEVELS["M2 normalized"])
        w(f"| {arm['name']} | {s['tp']} | {s['fp']} | {s['fn']} | "
          f"{num(s['precision'])} | {num(s['recall'])} | {num(s['f1'])} |")
    w("")

    w("## Error decomposition\n")
    k2, k4 = LEVELS["M2 normalized"], LEVELS["M4 code"]
    g_in2, g_in4 = {k2(r) for r in gt_in}, {k4(r) for r in gt_in}
    g_out2, g_out4 = {k2(r) for r in gt_out}, {k4(r) for r in gt_out}
    w("| extractor | missed | role-separation errors | hallucinations | duplicates |")
    w("|---|---:|---:|---:|---:|")
    for arm in arms:
        s = score(gt_in, arm["in"], k2)
        surplus = [r for r in arm["in"] if k4(r) not in g_in4 and k2(r) not in g_in2]
        role = [r for r in surplus if k4(r) in g_out4 or k2(r) in g_out2]
        hal = [r for r in surplus if r not in role]
        dn, _ = dup_rate(arm["in"], k2)
        w(f"| {arm['name']} | {s['fn']} | {len(role)} | {len(hal)} | {dn} |")
    w("")

    w("## Outbound calls\n")
    w("| extractor | emits outbound? | M2 F1 |")
    w("|---|---|---:|")
    for arm in arms:
        if arm["out"]:
            s = score(gt_out, arm["out"], LEVELS["M2 normalized"])
            w(f"| {arm['name']} | yes ({len(arm['out'])}) | {num(s['f1'])} |")
        else:
            w(f"| {arm['name']} | no | — |")
    w("")

    w("## Cost and runtime\n")
    w("| extractor | schema valid | wall | list-price cost |")
    w("|---|---|---:|---:|")
    for arm in arms:
        mt = arm["meta"]
        if "schema_valid_files" in mt:
            w(f"| {arm['name']} | {mt['schema_valid_files']}/{mt['n_files']} | "
              f"{mt.get('wall_seconds')} s | ${mt.get('list_price_usd')} |")
        else:
            w(f"| {arm['name']} | n/a (deterministic) | not measured | $0 |")
    w("")

    txt = "\n".join(L)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)
    print(f"\n[written] {a.out}")


if __name__ == "__main__":
    main()
