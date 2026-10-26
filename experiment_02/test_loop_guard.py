"""Self-check for the loop guard: a model that repeats one call is warned, then
only record and submit run, then it is stopped - and the run still writes its
output.  A call whose result was elided from the context is not a repeat.
A model that records nothing for NUDGE_STEPS steps is told to record.

    python test_loop_guard.py <path to spring-cloud-movie-recommendation>
"""
import json, sys, tempfile
from pathlib import Path

import agent_extract as ag

repo = sys.argv[1]
GREP = ("<tool_call>grep<arg_key>pattern</arg_key><arg_value>@Nothing</arg_value>", [], {})


def run(name, chat, steps=15):
    ag.chat = chat
    out = Path(tempfile.mkdtemp()) / f"{name}.json"
    sys.argv = ["x", "--repo", repo, "--system-name", "movie", "--max-steps", str(steps), "--out", str(out)]
    ag.main()
    sys.stdout = sys.__stdout__
    assert not out.with_suffix(".lock").exists()
    return json.loads(out.read_text(encoding="utf-8"))["_run"]


r = run("loop", lambda *a, **k: GREP)
assert "ignored the order" in r["stopped"], r
assert r["loop_warnings"] == ag.LOOP_STRIKES and r["blocked_calls"] == ag.MAX_BLOCKED + 1, r


def elide_all(base_url, model, messages, *a, **k):
    ag.fit(messages, 1)         # every earlier result is dropped, as on a full context
    return GREP


r = run("elided", elide_all, steps=ag.NUDGE_STEPS + 5)
assert not r["stopped"] and r["loop_warnings"] == 0 and r["steps"] == ag.NUDGE_STEPS + 5, r
assert r["record_nudges"] == 1, r
print("loop guard OK")
