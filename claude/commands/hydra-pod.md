---
description: Run a task in Hydra-Pod ticket mode (Opus manages; DeepSeek builds; GLM-5.3 reviews)
argument-hint: <task to manage, e.g. add remember-me to the login page>
---
Use the `opus-manager` skill for this task, in managed mode: you plan, dispatch, accept and verify; you do not write the implementation yourself.

Task: $ARGUMENTS

If no task was given above, ask me for one before doing anything else.

Governing flow: Opus plans tickets with acceptance criteria → DeepSeek implements and adds tests → tests → GLM-5.3 reviews read-only → Opus runs the reviewer's `PROBE:` lines with `~/Hydra-Pod/scripts/probe-run.py <report> --ref <head> [--run]` and validates every finding against the code (valid → explicit fix ticket for DeepSeek; invalid → one-line rejection; never forward a reviewer's proposed fix unchecked) → DeepSeek fixes within scope → tests → Opus final verification → done. Keep roles strictly separate.

Mechanical steps go through `hydra-pod-dispatch` (from the project root; set `HYDRA_POD_COMMIT_TRAILER` to the commit attribution line first):
- write each ticket from `_tickets/TICKET.template.md` (structured header: allowed_files, acceptance, test_command, earlier_specs, reviewers), then `hydra-pod-dispatch claim <T>` (runs `hydra-pod-dispatch preflight <T>` first: accounts, Z.ai credits, clean tree; if it fails, tell me exactly which `hydra-pod-connect connect <provider>` to run in a separate terminal and stop) → `hydra-pod-dispatch build <T>` → read the diff yourself → `hydra-pod-dispatch accept <T>` → `hydra-pod-dispatch review <T> [--reviewer zcode]` → `hydra-pod-dispatch probes <T> --run` → validate every finding and append Manager verdicts → a fix ticket (same header) or `hydra-pod-dispatch close <T>`. `hydra-pod-dispatch status` shows every ticket with its cost totals and writes `_tickets/STATE.md`; `hydra-pod-dispatch costs [<T>]` shows the per-run cost log. Report the cost of each ticket to me when you close it.
- hydra-pod-dispatch only automates checks; the judgment steps (tickets, diff reading, verdicts, fix tickets) stay yours.

Before dispatching, check accounts without spending quota: `hydra-pod-connect status` (hydra-pod-dispatch also stops a build/review if the provider is not connected). If a provider needed for this task is not Connected, ask me to run `hydra-pod-connect connect <provider>` (browser login; zcode-lite must be approved within ~5 minutes) instead of trying to authenticate yourself. Never read or copy credentials. Every `opencode run` you start must have stdin closed (`< /dev/null`).

If this project has no `_tickets/workers.md` yet, run the skill's first-use setup. If `~/Hydra-Pod/scripts/init-project.sh` exists, offer to run it first (it installs the verified reviewer agent, the dispatch watchdog and a workers.md draft). Propose this adopted baseline, but still confirm each choice with me as the skill requires:
- Builder: `opencode run --standalone --format json -m opencode-go/deepseek-v4.1-flash --auto`
- Reviewer: `opencode run --standalone --format json -m zai-coding-plan/glm-5.3 --agent reviewer` (Z.ai Lite via the Z.AI Coding Plan provider; the project-level `reviewer` agent enforces read-only)
- Wrap every opencode dispatch in `_tickets/run-watchdog.sh`.
- Build every review prompt from `~/Hydra-Pod/prompts/reviewer.md` (or `reviewer-zcode.md`) with its fixed context block filled in: current time, exact test command, earlier specs. Never drop that block.
- Optional alternative reviewer (only if I choose it): ZCode, via `~/Hydra-Pod/scripts/zcode-review-prep.sh <ticket> <base> <head>` then `hydra-pod-connect review zcode-lite --prompt-file _receipts/<ticket>.zcode-prompt.txt --out _receipts/<ticket>.review.md`. It is read-only (Read/Glob/Grep only, MCP off) and cannot run git or tests.
- Never use `opencode-go/glm-5.3` (bills OpenCode Go) or `zai/glm-5.3` (pay-as-you-go) for review, and never use `pi` for Z.ai.

Full framework docs: `~/Hydra-Pod/README.md`.
