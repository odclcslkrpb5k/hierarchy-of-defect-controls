# Payload fixtures

One JSON file per hook event. The tests load these and override only
`session_id`, `cwd`, `scratchpad_dir`, `tool_input`, `tool_use_id`,
`agent_id` and `error`/`tool_response` per case, so a renamed or removed
field upstream fails the suite instead of failing silently.

**Provenance:** captured from a real Claude Code 2.1.270 session during the
round-3 adversarial review (2026-09-14) and sanitised: `session_id` to
`SESSION`, the repo path to `/repo`, home to `/home/u`, and the
`UserPromptSubmit` prompt shortened. Fields the hooks do not read
(`effort`, `prompt_id`, `duration_ms`, `is_interrupt`, the richer
`tool_response` objects) are kept as captured.

`transcript_2.1.270.jsonl` is 20 lines from the transcript of the same round-3
capture session (`~/.claude/projects/<encoded cwd>/<session>.jsonl`),
chosen to cover a reminder then a deny, a pre-0.4 no-op loop ending in a
deny, a user-turn boundary, and a denied call re-run after it. Sanitised
the same way: the work directory to `/repo`, the session id to `SESSION`,
home to `/home/u`, user prompts shortened. The report's parser depends on
this undocumented format; re-capture it with the payloads.

`transcript_2.1.289.jsonl` is the tool calls, results and hook context of
the 0.6.0 live check (2026-10-05, `claude -p` with `--plugin-dir`), sanitised
the same way. It exists because 2.1.289 changed the format: a deny's
`tool_result` now reads `PreToolUse:Bash hook error: <reason>`, and the
report counted no denies until it was taught the wrapper.

Re-capture after a Claude Code upgrade: a plugin whose hooks run
`cat >> payloads.jsonl` is enough.
