# 1. Architecture: roles, subscriptions and routing

## The idea

Opus excels at judging things: dividing the work, defining when it counts as done, and distinguishing a real regression from a false alarm. But writing code is what consumes most of the tokens.
Therefore the Claude Pro quota is spent on planning and verification only, and implementation and review are handled by two models from two other companies, each through its own subscription.

## The three roles

| Role | What it does | What it never does |
|---|---|---|
| **Opus 5.5**: manager and verifier | splits the work into tickets with acceptance criteria, dispatches them to the builder, re-runs the acceptance commands itself, examines every finding from the reviewer, writes the fix tickets, performs the final verification, and commits | does not write the implementation code itself |
| **DeepSeek V4.1 Flash**: builder | writes the code and tests within the ticket's scope, runs the acceptance commands, and writes the receipt | does not go outside the ticket's scope, does not move tickets, does not commit, and does not review its own work |
| **GLM-5.3**: independent reviewer | reads the diff and the code and runs the tests, and looks for logic errors, regressions, security problems and weak tests, and writes a report of findings | does not modify any file. opencode's tools actually prevent it from doing so, and the matter does not rely on its commitment |

The reviewer is from a company other than the builder's company (Zhipu and DeepSeek), as the skill requires.

## Routing and billing

| Model as written in opencode | Charged to | Use here |
|---|---|---|
| `opencode-go/deepseek-v4.1-flash` | OpenCode Go subscription | ✅ builder |
| `zai-coding-plan/glm-5.3` | Z.ai Lite plan (GLM Coding Plan) | ✅ reviewer |
| `opencode-go/glm-5.3` | **OpenCode Go**, not Z.ai | ❌ do not use it for review |
| `zai/glm-5.3` | **Z.ai prepaid balance** | ❌ do not use it |

Both providers `zai` and `zai-coding-plan` are defined by the opencode catalog with the same environment variable `ZHIPU_API_KEY`. So always write the full name `zai-coding-plan/…` so that usage is not charged to the wrong balance.

### Z.ai URLs

| Use | Base URL | Who uses it |
|---|---|---|
| GLM Coding Plan (OpenAI-compatible) | `https://api.z.ai/api/coding/paas/v4` | the `zai-coding-plan` provider in opencode, which is our path |
| Prepaid | `https://api.z.ai/api/paas/v4` | the `zai` provider in opencode |
| Coding Plan (Anthropic-compatible) | `https://api.z.ai/api/anthropic` | Claude Code and the "Z.ai Coding Plan" template in ZCode |
| ZCode Start Plan (in-app plan) | `https://zcode.z.ai/api/v1/zcode-plan/anthropic` | ZCode only, and requires logging in with a Z.ai account. Not used outside it |
| Quota query (read-only) | `https://api.z.ai/api/monitor/usage/quota/limit` | `scripts/zai-quota.sh` |

## Z.ai Lite quota

2,000 units every 5 hours, and 10,000 weekly. **It is also consumed by** other tools sharing the same Z.ai account, and by ZCode on the same account, so check the quota before a large review round:

```bash
~/Hydra-Pod/scripts/zai-quota.sh
```

For comparison: the reviewer experiments and the T1 review cost about 20 units.

## Flow diagram

```
            ┌─────────────── Opus 5.5 (Claude Code + opus-manager) ───────────────┐
            │ plan → ticket → dispatch → ACCEPT → dispatch review → VALIDATE → close│
            └───────┬──────────────────▲────────────┬──────────────▲──────────────┘
                    │ ticket           │ receipt    │ range        │ report
                    ▼                  │            ▼              │
           DeepSeek V4.1 Flash ────────┘      GLM-5.3 (read-only) ─┘
           opencode-go, --auto                zai-coding-plan, --agent reviewer
                    ▲
                    │ fix ticket (valid findings only, with corrected values)
                    └──────────────────── Opus
```
