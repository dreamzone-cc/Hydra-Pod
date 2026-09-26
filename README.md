# Hydra-Pod

*Unified Multi-Agent AI Orchestration*

A proven framework that combines three existing subscriptions, and uses each model through the service it belongs to, instead of paying for a separate API for each model.
Hydra-Pod is the framework (Opus manages, DeepSeek builds, GLM reviews), built on the upstream [opus-manager](https://github.com/yanauto/opus-manager) skill that runs inside Claude Code. This repository adds on top of it the configuration, templates and scripts that proved necessary to run it reliably in practice.

```
Opus 5.5 → Plan → DeepSeek → Implement → Tests → GLM-5.3 Review → Validate Findings
        → Fix Ticket → DeepSeek Fix → Tests → Opus Final Verification → Done
```

| Role | Subscription | Tool | Model |
|---|---|---|---|
| **Manager and verifier** | Claude Pro | Claude Code + skill `opus-manager` | Opus 5.5 |
| **Builder** | OpenCode Go | `opencode run` | `opencode-go/deepseek-v4.1-flash` |
| **Independent reviewer** (read-only) | Z.ai Lite (GLM Coding Plan) | `opencode run --agent reviewer`, or optionally `hydra-pod-connect review zcode-lite` | `zai-coding-plan/glm-5.3` / GLM-5.3 via ZCode |

## Status: tested end to end (2026-09-25)

| Test | What it proved | Evidence |
|---|---|---|
| **T1**: the successful path | plan, then implementation, then acceptance, then a PASS review, then close | `~/om-sandbox` (the validation sandbox project, not included in this repository), commits from `a50b811` to `743365a` |
| **T3/T3b**: two independent reviewers (opencode and ZCode) | both found the same seeded regression. ZCode raised no false finding, and opencode raised one incorrect finding | commits from `d3ce09b` to `2ac1548` |
| **T2/T2b**: the fix loop | a real regression was seeded and GLM caught it, and Opus validated the findings and corrected an incorrect suggestion from the reviewer, then DeepSeek fixed it, and Opus verified finally | commits from `33818a1` to `0b88ae8` |

Full details are in [docs/06-validation.md](docs/06-validation.md).

## Quick start

```bash
# 1. Install the skill and the /hydra-pod command inside ~/.claude, and link hydra-pod-connect in ~/.local/bin
#    (does not overwrite any differing file unless --force is given)
~/Hydra-Pod/scripts/install.sh

# 2. Link the accounts through the browser, once
hydra-pod-connect connect opencode-go     # the builder: OpenCode Go
hydra-pod-connect connect zcode-lite      # optional alternative reviewer: ZCode Lite (approve within 5 minutes)
hydra-pod-connect list                    # statuses

# 3. Prepare your project (does not overwrite any existing file, and shows the account status)
~/Hydra-Pod/scripts/init-project.sh /path/to/project

# 4. From inside the project in Claude Code:
/hydra-pod add feature such-and-such
#    (Opus writes the ticket from TICKET.template.md, then uses hydra-pod-dispatch for every automated step)
```

**The default reviewer** (GLM-5.3 via opencode + Z.AI Coding Plan) needs its own opencode authentication, detailed in `docs/02-setup.md` section 3.

Before first use, complete the prerequisites and authentication described in [docs/02-setup.md](docs/02-setup.md).

## Repository contents

```
README.md                 this page
docs/
  01-architecture.md      roles, subscriptions and routing, and the billing mistakes to avoid
  02-setup.md             prerequisites, OpenCode Go and Z.ai authentication, the key file, and installation
  03-workflow.md          the ticket lifecycle, the fix-loop rules, and role separation
  04-operations.md        the actual operating commands for each role, the watchdog, report extraction, and quota
  05-troubleshooting.md   the problems we hit and their solutions (opencode 2.0.16 and others)
  06-validation.md        the results of tests T1 and T2/T2b with numbers
  07-security.md          keys, read-only enforcement, and service terms
  08-decisions.md         the decisions log (what was adopted, what was dropped, and why)
  09/10                   the account-linking plan and ZCode inspection results
  11-layers-and-handoffs.md  a report on the workflow between layers and coordination between agents, with recommendations
templates/project/        what is copied into each project: opencode.json (the reviewer agent), run-watchdog.sh, and workers.md
prompts/                  the text of the builder prompt and the reviewer prompt
claude/commands/hydra-pod.md     the /hydra-pod command
skill/opus-manager/       an identical copy of the original skill (MIT, commit 55bb47c)
scripts/                  install.sh, init-project.sh, zcode-review-prep.sh, extract-report.py, probe-run.py, zai-quota.sh
providers.json            the provider registry (zcode-lite, opencode-go)
hydra_pod/             the authentication, provider and runtime layers (Python, standard library only)
bin/hydra-pod-connect            account linking: list, status, test, connect, disconnect, review, runtime
bin/hydra-pod-dispatch           ticket steps: preflight, claim, build, accept, review, probes, close, status, costs
tests/                    unit tests
```

## License

This project is licensed under the GNU Affero General Public License v3.0 or later (see `LICENSE`). The vendored skill in `skill/opus-manager/` keeps its original MIT license (© 2026 yanauto, https://github.com/yanauto/opus-manager), see `skill/UPSTREAM.md`.
