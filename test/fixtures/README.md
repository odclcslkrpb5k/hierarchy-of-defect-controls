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

Re-capture after a Claude Code upgrade: a plugin whose hooks run
`cat >> payloads.jsonl` is enough.
