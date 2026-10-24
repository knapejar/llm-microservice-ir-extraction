"""Self-check for parse_call, parse_tool_calls and build_body."""
from agent_extract import parse_call

assert parse_call("<tool_call>grep<arg_key>pattern</arg_key><arg_value>@Get</arg_value>") == ("grep", {"pattern": "@Get"})
assert parse_call("<tool_call>read_file<arg_path>/a/B.java</arg_path><arg_start>1</arg_start>") == (
    "read_file", {"path": "/a/B.java", "start": "1"})
assert parse_call("<tool_call>find{<arg_key>pattern</arg_key><arg_value>*.java</arg_value><arg_path>/</arg_path>}") == (
    "find", {"pattern": "*.java", "path": "/"})

# Native tool calling: every structured call is kept, with its id (none dropped)
from agent_extract import parse_tool_calls
calls = parse_tool_calls([{"id": "a", "function": {"name": "grep", "arguments": '{"pattern": "@GetMapping"}'}},
                          {"function": {"name": "list_dir", "arguments": {"path": "/"}}}], 7)
assert calls == [("a", "grep", {"pattern": "@GetMapping"}), ("call_7_1", "list_dir", {"path": "/"})], calls
# Qwen3.8 no-thinking: effort-in-template -> enable_thinking=False, no top-level reasoning_effort
from agent_extract import build_body
b = build_body("qwen3.8-27b", [], "none", None, 16384, effort_in_template=True)
assert b["chat_template_kwargs"] == {"enable_thinking": False}, b
assert "reasoning_effort" not in b and b["stop"] == ["</tool_call>"], b
b = build_body("qwen3.8-27b", [], "medium", None, 16384, effort_in_template=True)
assert b["chat_template_kwargs"] == {"reasoning_effort": "medium"}, b
# LM Studio path unchanged: top-level reasoning_effort
b = build_body("spark-x2.5-4b", [], "none", None, 8192, effort_in_template=False)
assert b["reasoning_effort"] == "none" and b["chat_template_kwargs"] == {"enable_thinking": False}, b
print("parse_call OK")
