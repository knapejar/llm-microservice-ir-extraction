"""Self-check for recording: services, evidence-backed endpoints, several
checkouts, source decoding and context trimming.

    python test_record.py
"""
import json, subprocess, tempfile
from pathlib import Path

import agent_extract as ag

tmp = Path(tempfile.mkdtemp())


def checkout(name, files):
    root = tmp / name
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(body if isinstance(body, bytes) else body.encode())
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


CTRL = """package demo;
@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/{userId}")
    public User getUser(@PathVariable String userId) { return null; }
}
"""
users = checkout("users", {
    "user-service/src/main/java/demo/UserController.java": CTRL,
    "user-service/src/main/java/demo/Legacy.java": "// komentář v cp1250\n@GetMapping(\"/old\")\n".encode("cp1250"),
    "user-service/src/main/java/demo/Wide.java": "@GetMapping(\"/wide\")\n".encode("utf-16"),
    "user-service/node_modules/x/index.js": "app.get('/vendored')",
    ".gitignore": "build/\n",
    "user-service/build/Gen.java": "@GetMapping(\"/generated\")",
})
repo = ag.Repo([users])

# Only tracked, non-vendored sources are visible; cp1250 and UTF-16 files are searchable.
assert "/user-service/build/Gen.java" not in repo.paths and not any("node_modules" in p for p in repo.paths), repo.paths
hits = repo.grep(r"@GetMapping")
assert "Legacy.java:2" in hits and "Wide.java:1" in hits and "generated" not in hits, hits
assert repo.list_dir("/user-service") == "src/", repo.list_dir("/user-service")
assert repo.find("src/main/java/**/*.java", "/user-service").count(".java") == 3   # globs on paths too
assert repo.find("*Controller.java") == "/user-service/src/main/java/demo/UserController.java"

rec = ag.Recorded(repo, "demo")
ep = {"className": "UserController", "methodName": "getUser", "httpMethod": "GET",
      "path": "/user/{userId}", "line": 5, "evidence": '@GetMapping("/{userId}")'}
F = "/user-service/src/main/java/demo/UserController.java"

# A file needs a recorded service whose dirs contain it.
msg, n = rec.record({"files": [{"path": F, "service": "user-service", "endpoints": [ep]}]})
assert n == 1 and "not recorded" in msg, msg
msg, n = rec.record("[Recorded 2 new: GET /x]")       # an echoed tool result is explained, not just rejected
assert n == 1 and "not a summary" in msg and "Recorded 2 new" in msg, msg
msg, n = rec.record(json.dumps({"services": [{"name": "user-service", "dirs": ["/other"]}]}))
assert n == 1 and "not a directory" in msg, msg
msg, n = rec.record({"services": [{"name": "user-service", "dirs": ["/user-service"]}],
                     "files": [{"path": F, "service": "user-service", "endpoints": [ep]}]})
assert n == 0 and rec.n_endpoints() == 1, msg
msg, n = rec.record({"services": [{"name": "gateway", "dirs": ["/user-service"]}],
                     "files": [{"path": F, "service": "user-service", "endpoints": [ep]}]})
assert "already recorded" not in msg and "no endpoints recorded yet: gateway" in msg, msg
msg, n = rec.record(json.dumps([{"path": F, "service": "user-service", "endpoints": [ep]}]))
assert n == 0 and "already recorded" in msg, msg     # a bare list of files is accepted

# Evidence must be at the cited line, agree with the verb and end the path; good entries are kept.
bad = [dict(ep, line=1),                                   # evidence not at that line
       dict(ep, httpMethod="POST"),                        # verb contradicts @GetMapping
       dict(ep, path="/user/{userId}/x"),                  # path does not end with the literal
       dict(ep, path="user/{userId}"),                     # not a full route
       dict(ep, evidence="5:     @GetMapping(\"/{userId}\")", line=6),  # numbered copy, 1 line off: valid
       dict(ep, evidence="@GetMapping( \"/ {userId}\" )")]        # spacing differs: still the same code
msg, n = rec.record({"files": [{"path": F, "service": "user-service", "endpoints": bad}]})
assert n == 4 and "Lines" in msg and "declares GET" in msg and "does not end" in msg and "starting with /" in msg, msg
assert rec.n_endpoints() == 1, rec.doc()      # the valid copy is a duplicate, not a second endpoint
assert rec.doc()["files"][0]["service"] == "user-service"

assert ag.verbs_in("@app.get('/x')") == {"GET"} and ag.verbs_in("[HttpPost(\"x\")]") == {"POST"}
assert ag.route_literals('@RequestMapping(value = "/a/:id", produces = "application/json")') == {"/a/{}"}
assert ag.route_literals('mux.HandleFunc("GET /items/{id}", h)') == {"/items/{}"}

# Several checkouts are mounted side by side.
orders = checkout("orders", {"main.go": 'r.GET("/orders", list)\n'})
multi = ag.Repo([users, orders])
assert multi.list_dir("/") == "orders/\nusers/", multi.list_dir("/")
assert "/orders/main.go:1" in multi.grep(r"GET") and multi.read_file("/orders/main.go").startswith("1: r.GET")
try:
    multi.resolve("/users/../../etc")
    raise AssertionError("escaped the checkout")
except ValueError:
    pass
assert ag.checkout_state(users) is None     # no commit yet: recorded as unknown, no crash

# Over budget, trimming drops to FIT_TARGET at once, so the next steps keep the same prefix.
msgs = [{"role": "system", "content": "s"}] + [
    {"role": "tool", "tool_call_id": str(i), "content": "x" * 1000} for i in range(20)]
assert ag.fit(msgs, 15000) > 0 and sum(ag.msg_size(m) for m in msgs) <= 15000 * ag.FIT_TARGET
assert ag.fit(msgs, 15000) == 0

# Cached input is billed at the cache rate where known.
assert ag.list_price("GLM-5.3-Flash", 1_000_000, 0, 1_000_000) == 0.03
assert ag.list_price("bonsai", 1, 1) is None
print("record OK")
