---
name: langfuse
description: Debug AI traces, find exceptions, analyze sessions, and manage prompts via Langfuse MCP. Also handles MCP setup and configuration.
metadata:
  short-description: Langfuse observability via MCP
  compatibility: claude-code, codex-cli
---

# Langfuse Skill

Debug your AI systems through Langfuse observability.

**Triggers:** langfuse, traces, debug AI, find exceptions, set up langfuse, what went wrong, why is it slow

## Setup

**Step 1:** Get credentials from https://cloud.langfuse.com → Settings → API Keys

If self-hosted, use your instance URL for `LANGFUSE_HOST` and create keys there.

**Step 2:** Install MCP (pick one):

```bash
# Claude Code
claude mcp add langfuse -s project \
  -e LANGFUSE_PUBLIC_KEY=pk-... \
  -e LANGFUSE_SECRET_KEY=sk-... \
  -e LANGFUSE_HOST=https://cloud.langfuse.com \
  -- uvx --python 3.11 langfuse-mcp

# Codex CLI
codex mcp add langfuse \
  --env LANGFUSE_PUBLIC_KEY=pk-... \
  --env LANGFUSE_SECRET_KEY=sk-... \
  --env LANGFUSE_HOST=https://cloud.langfuse.com \
  -- uvx --python 3.11 langfuse-mcp
```

**Step 3:** Restart CLI, verify with `/mcp` (Claude) or `codex mcp list` (Codex)

**Step 4:** Test: `fetch_traces(age=60)`

For manual `.mcp.json` setup or troubleshooting, see `references/setup.md`.

---

## Playbooks

### "Where are the errors?"

```
find_exceptions(age=1440, group_by="file")
```
→ Shows error counts by file. Pick the worst offender.

```
find_exceptions_in_file(filepath="src/ai/chat.py", age=1440)
```
→ Lists specific exceptions. Grab a trace_id.

```
get_exception_details(trace_id="...")
```
→ Full stacktrace and context.

---

### "What happened in this interaction?"

```
fetch_traces(age=60, user_id="...")
```
→ Find the trace. Note the trace_id.

If you don't know the user_id, start with:
```
fetch_traces(age=60)
```

```
fetch_trace(trace_id="...", include_observations=true)
```
→ See all LLM calls in the trace.

```
fetch_observation(observation_id="...")
```
→ Inspect a specific generation's input/output.

---

### "Why is it slow?"

```
fetch_observations(age=60, type="GENERATION")
```
→ Find recent LLM calls. Look for high latency.

```
fetch_observation(observation_id="...")
```
→ Check token counts, model, timing.

---

### "What's this user experiencing?"

```
get_user_sessions(user_id="...", age=1440)
```
→ List their sessions.

```
get_session_details(session_id="...")
```
→ See all traces in the session.

---

### "Manage prompts"

```
list_prompts()
```
→ See all prompts with labels.

```
get_prompt(name="...", label="production")
```
→ Fetch current production version.

```
create_text_prompt(name="...", prompt="...", labels=["staging"])
```
→ Create new version in staging.

```
update_prompt_labels(name="...", version=N, labels=["production"])
```
→ Promote to production. (Rollback = re-apply label to older version)

---

## Quick Reference

| Task | Tool |
|------|------|
| List traces | `fetch_traces(age=N)` |
| Get trace details | `fetch_trace(trace_id="...", include_observations=true)` |
| List LLM calls | `fetch_observations(age=N, type="GENERATION")` |
| Get observation | `fetch_observation(observation_id="...")` |
| Error count | `get_error_count(age=N)` |
| Find exceptions | `find_exceptions(age=N, group_by="file")` |
| List sessions | `fetch_sessions(age=N)` |
| User sessions | `get_user_sessions(user_id="...", age=N)` |
| List prompts | `list_prompts()` |
| Get prompt | `get_prompt(name="...", label="production")` |

`age` = minutes to look back (max 10080 = 7 days)

---

## References

- `references/tool-reference.md` — Full parameter docs, filter semantics, response schemas
- `references/setup.md` — Manual setup, troubleshooting, advanced configuration
