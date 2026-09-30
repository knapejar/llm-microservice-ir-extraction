"""Self-check for the loop guard: a model that repeats one call is warned,
ordered to submit, then stopped - and the run still writes its output.

    python test_loop_guard.py <path to spring-cloud-movie-recommendation>
"""
import json, sys, tempfile
from pathlib import Path

import agent_extract as ag

repo = sys.argv[1]
ag.chat = lambda *a, **k: ("<tool_call>grep<arg_key>pattern</arg_key><arg_value>@Nothing</arg_value>", {})
out = Path(tempfile.mkdtemp()) / "loop.json"
sys.argv = ["x", "--repo", repo, "--system-name", "movie", "--max-steps", "15", "--out", str(out)]
ag.main()
sys.stdout = sys.__stdout__
r = json.loads(out.read_text(encoding="utf-8"))["_run"]
assert r["stopped"] and r["loop_warnings"] == ag.LOOP_STRIKES + 1, r
assert not out.with_suffix(".lock").exists()
print("loop guard OK:", r["stopped"])
