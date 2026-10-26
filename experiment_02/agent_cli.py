#!/usr/bin/env python3
"""The agent's tools as a command line, for a model that drives the loop itself
(an interactive coding assistant) instead of being called over an API.  Same
task prompt, same tools, same validation of recorded entries and the same output
file as agent_extract.py; only context trimming and the loop guard do not apply.

    python agent_cli.py <state.json> init --repo <checkout>... --system-name X --model M
    python agent_cli.py <state.json> <tool> '<json args>'      # or @file with the JSON

Tools: list_dir, find, grep, read_file, record, submit (see init's output).
Every call is appended to the state file.  record and submit replay the payloads
recorded so far, so the result is the one agent_extract.py builds from the same
calls.  An accepted submit writes out/pool/agent_ir.<system>.<model>.cli.json.
"""
import argparse, json, sys, time
from pathlib import Path

from agent_extract import HERE, MAX_OUT, TASK, TOOLS, Recorded, Repo, checkout_state


def init(state_path, argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, nargs="+")
    ap.add_argument("--system-name", required=True)
    ap.add_argument("--model", required=True)
    a = ap.parse_args(argv)
    repo = Repo(a.repo)
    state = {"repo": [str(Path(r).resolve()) for r in a.repo], "system": a.system_name, "model": a.model,
             "t0": time.time(), "records": [], "rejected": 0, "trace": []}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    mount = ("The repository is mounted read-only at /." if not repo.multi else
             "The system's repositories are mounted read-only side by side: "
             + ", ".join("/" + n for n in repo.roots) + ".")
    print(TASK.replace("{mount}", mount))
    print("\n## Tools (call: python agent_cli.py <state> <tool> '<json args>')")
    print("\n".join(json.dumps(t, separators=(",", ":")) for t in TOOLS))
    print(f"\nExtract the services and inbound endpoints of {a.system_name}. Start with list_dir or find.")


def call(state_path, name, raw):
    state = json.loads(state_path.read_text(encoding="utf-8"))
    args = json.loads(Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw or "{}")
    repo = Repo(state["repo"])
    rec = Recorded(repo, state["system"])
    for p in state["records"]:
        rec.record(p)
    payload = args.get("json", args if ("services" in args or "files" in args) else None)
    finished = False
    if name in ("record", "submit") and payload:
        result, n_err = rec.record(payload)
        state["records"].append(payload)
        state["rejected"] += n_err
    else:
        result, n_err = "", 0
    if name == "submit":
        if n_err:
            result += "\n[NOT FINISHED] fix the rejected entries, then submit again."
        elif not rec.services:
            result = (result + "\n[NOT FINISHED] no service is recorded yet. Record the services "
                      "and their endpoints, then submit.").strip()
        else:
            result = (result + f"\n[ACCEPTED] {len(rec.services)} services, {rec.n_endpoints()} endpoints.").strip()
            finished = True
    elif name == "list_dir":
        result = repo.list_dir(args.get("path", "/"))
    elif name == "find":
        result = repo.find(args.get("pattern", "*"), args.get("path", "/"))
    elif name == "grep":
        result = repo.grep(args.get("pattern", ""), args.get("path", "/"))
    elif name == "read_file":
        result = repo.read_file(args.get("path", ""), args.get("start") or 1)
    elif name != "record":
        result = f"[ERROR] unknown tool {name!r}. Tools: list_dir, find, grep, read_file, record, submit."
    if len(result) > MAX_OUT:
        result = result[:MAX_OUT] + "\n[... truncated]"
    state["trace"].append({"step": len(state["trace"]) + 1, "tool": name,
                           "args": {k: str(v)[:200] for k, v in args.items()}, "result_head": result[:1000]})
    state_path.write_text(json.dumps(state), encoding="utf-8")
    print(result)
    if finished:
        doc = rec.doc()
        single = None if repo.multi else checkout_state(next(iter(repo.roots.values()))) or {}
        doc["_run"] = {"model": state["model"], "provider": "cli", "workflow": "agent-cli",
                       "effort": "cli", "temperature": None, "native_tools": None,
                       "repo": ", ".join(repo.roots),
                       **({"commit": single.get("commit"), "dirty": single.get("dirty")} if single is not None
                          else {"repos": {n: checkout_state(r) for n, r in repo.roots.items()}}),
                       "accepted": True, "steps": len(state["trace"]), "tool_calls": len(state["trace"]),
                       "rejected_entries": state["rejected"],
                       "wall_seconds": round(time.time() - state["t0"], 1), "trace": state["trace"]}
        out = HERE / "out" / "pool" / f"agent_ir.{state['system']}.{state['model']}.cli.json"
        out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written {out}")


if __name__ == "__main__":
    st, cmd = Path(sys.argv[1]), sys.argv[2]
    init(st, sys.argv[3:]) if cmd == "init" else call(st, cmd, sys.argv[3] if len(sys.argv) > 3 else "{}")
