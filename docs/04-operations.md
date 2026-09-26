# 4. Operating commands

All commands are run **from the project root**. `<ticket>` is the ticket name, such as `T3-foo`.

## The usual way: `hydra-pod-dispatch` (since 2026-09-26)

```bash
export HYDRA_POD_COMMIT_TRAILER="Co-Authored-By: …"   # optional: a line appended to the commits
hydra-pod-dispatch preflight <ticket> # the accounts, the balance, the tree and the head before starting (claim runs it automatically)
hydra-pod-dispatch claim  <ticket>    # open → doing, records base = HEAD, and signs claimed-by
hydra-pod-dispatch build  <ticket>    # makes sure the account is connected, then runs DeepSeek through the watchdog, then verifies the receipt and the scope
#   (Opus reads the diff itself here)
hydra-pod-dispatch accept <ticket>    # re-runs the acceptance commands, verifies the scope, makes a commit, records head, and sets the status → review
hydra-pod-dispatch review <ticket> [--reviewer zcode]   # a review request built from the ticket's head, with the context block (R1)
hydra-pod-dispatch probes <ticket> --run                 # runs the PROBE lines at head
#   (Opus rules on every finding: a fix ticket, or ↓)
hydra-pod-dispatch close  <ticket>    # doing → done
hydra-pod-dispatch status             # a table of every ticket with the cost, and writes _tickets/STATE.md
hydra-pod-dispatch costs [<ticket>]   # the cost log for every run: the duration, the calls, the tokens, the Z.ai balance, and the catalog estimate
```

- **Writing the ticket:** it is written from `_tickets/TICKET.template.md`. Its structured header (R2) defines the fields `allowed_files`, `acceptance`, `test_command`, `earlier_specs` and `reviewers` (opencode or zcode or both).
- **Z.ai credit floor:** `HYDRA_POD_MIN_ZAI_CREDITS` is the minimum balance required by the preflight (100 by default).
- **Partial matching in acceptance commands:** a line in `acceptance` may end with ` ==> text`. That means the command must exit successfully, and "text" must appear in its output.
- **What stays with Opus:** the manual commands in the following sections are still valid, and `hydra-pod-dispatch` only wraps them. Judgment (writing tickets, reading the diff, verdicts, and fix tickets) stays with Opus.

## The watchdog (used with both roles)

```bash
_tickets/run-watchdog.sh <out.jsonl> <timeout-s> -- <command…>
```

- If no event reaches the output file within 90 seconds, the watchdog stops the attempt and retries it, up to 3 attempts. The timeout can be changed with the `STARTUP_SECS` variable.
- It writes the attempt number and the exit code to stderr.
- Exit codes: `0` success, `124` the overall timeout expired, `125` all three attempts failed to start.
- Why it is needed: in 2.0.16 the private server sometimes never starts the session (see 05).

## The builder (DeepSeek)

```bash
_tickets/run-watchdog.sh _receipts/<ticket>.run.jsonl 1800 -- \
  opencode run --standalone --format json -m opencode-go/deepseek-v4.1-flash --auto "<prompt>" \
  2> _receipts/<ticket>.watchdog.log
```

The text of `<prompt>` is in `prompts/worker.md`, and Opus substitutes the ticket name in it. The builder writes the receipt itself in `_receipts/<ticket>.receipt.md`.

## The reviewer (GLM-5.3)

```bash
_tickets/run-watchdog.sh _receipts/<ticket>.review.jsonl 1200 -- \
  opencode run --standalone --format json -m zai-coding-plan/glm-5.3 --agent reviewer "<prompt>" \
  2> _receipts/<ticket>.review.watchdog.log

~/Hydra-Pod/scripts/extract-report.py _receipts/<ticket>.review.jsonl > _receipts/<ticket>.review.md
```

After that:
1. Opus runs the `PROBE:` lines that the reviewer wrote:
   ```bash
   ~/Hydra-Pod/scripts/probe-run.py _receipts/<ticket>.review.md --ref <head>        # display and safety check
   ~/Hydra-Pod/scripts/probe-run.py _receipts/<ticket>.review.md --ref <head> --run  # run in a temporary copy
   ```
2. It appends a **Manager verdicts** section at the end of `review.md`, writing its verdict on every finding along with the PROBE results table.

> **stdin:** any `opencode run` outside the watchdog must close stdin with `< /dev/null`, otherwise it waits forever (problem 0 in 05).

## The alternative reviewer: ZCode

```bash
git diff <base>..<head> -- src tests > _receipts/<ticket>.diff
git log --format='%h %s' <base>..<head> > _receipts/<ticket>.commits
~/Hydra-Pod/bin/hydra-pod-connect review zcode-lite --prompt-file <prompt> --out _receipts/<ticket>.review.md
```

- **Permissions:** it runs with `--mode yolo`, with every tool except `Read`, `Glob` and `Grep` removed via `--disallowed-tools`, that is, before the session starts.
- **MCP:** disabled via `.zcode/config.json` (the value `features.mcp: false`) inside the private review directory. Without that, the MCP servers defined in the machine's ZCode settings appear, such as user-level MCP servers (in testing, one of them could execute code).
- **Tool verification:** before the first review for each runtime version, it asks the tool for its tool list. It refuses to run if the list is not exactly Read, Glob and Grep (exit code 3).
- **Read-only:** it cannot run git or the tests, so Opus gives it a diff file and absolute paths (`prompts/reviewer-zcode.md`).

## Why exactly these options

| Option | Reason |
|---|---|
| `--standalone` | the shared opencode service runs in the background and serves other sessions, and may not see newly added authentication, so it stops silently. A private server per run isolates the problem |
| `--format json` | in the default mode, `opencode run` may finish the session successfully and then print nothing and not exit. json mode streams the events one by one and exits cleanly |
| `--agent reviewer` | the built-in `plan` agent allows any shell command. The `reviewer` agent in `opencode.json` prevents modification and allows only a specific list of commands |
| `--auto` (for the builder only) | automatic approval of permissions so that it works without interaction. It needs explicit approval from the operator for each project |

## The reviewer agent (from `templates/project/opencode.json`)

```json
"permission": {
  "edit": "deny",
  "webfetch": "deny",
  "question": "deny",
  "bash": { "*": "deny", "git diff*": "allow", "git log*": "allow",
            "git show*": "allow", "git status*": "allow",
            "python3 -B -m unittest*": "allow" }
}
```

- `question: deny` because the run is automated and nobody will answer.
- The `-B` option prevents writing `__pycache__` files.
- The reviewer cannot run `python3 -c`. This is intentional, and Opus runs these commands itself at acceptance.

## Following a running job

```bash
wc -l _receipts/<ticket>.run.jsonl                    # the number of events so far
opencode session list | head -3                        # was the session created?
opencode session export <id> | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["outcome"])'
```

If the session was created and the `outcome` value is `succeeded`, then the work has actually finished even if the command has not exited yet.

## Quota

```bash
~/Hydra-Pod/scripts/zai-quota.sh
```
