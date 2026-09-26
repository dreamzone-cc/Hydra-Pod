# 10. Phase 0 findings: the official ZCode CLI

> Date 2026-09-25. The application is ZCode 3.14.3, and the CLI version is 0.16.9. The code source: the official repository `zai-org/ZCode` at commit `29628c9` (release v3.14.3).
> **No credential files were read.** Everything here is taken from the official code and from the output of the official commands.

## 0-1 Runtime location

- `zcode.cjs` exists inside `ZCode-3.14.3-linux-x64.AppImage` at the path `resources/glm/` (the folder size is 79 MB, and it includes `packages/`).
- **Important note:** the CLI needs the file `zcode-builtin.json` in `glm/provider/`. In the application this file is in `resources/config/provider/`, and without it the error `无法定位 CLI ZCode Built-in Provider Config` appears.
- The proposed layout: `~/.local/share/hydra-pod/zcode/3.14.3/glm/` + `glm/provider/zcode-builtin.json`.
- The `--version` command works from a standalone copy after extraction (`--appimage-extract`), and it returned `0.16.9`.

## 0-2 Node

- The installed version is `v26.8.2`, and the officially required one is `24.14`.
- The commands `--version`, `doctor --json` and `-p` all worked without any warning. No other Node is needed.

## 0-3 Login (from `login-command.ts` and `cli-oauth.ts`)

- The syntax: `zcode login [zai|bigmodel] [--no-browser] [--json]`, and logout with `zcode logout [--json]`.
- The flow:
  1. `…/oauth/cli/init` returns `authorize_url` and `poll_interval_sec`.
  2. The user logs in at `chat.z.ai/api/oauth/authorize`, then is redirected to `zcode.z.ai/api/v1/oauth/cli/callback/zai`.
  3. The CLI polls `…/oauth/cli/poll/<flowId>` periodically.
- With `--json` the link is written to **stderr**.
  - On success it prints JSON to stdout: `{status: "ready", provider, user{…}, model, credentialsPath, configPath, browserOpened}`.
  - On exit it prints `{status: "logged_out", provider, credentialsPath}`.
  - On failure it prints `Error: …` to stderr, and the exit code is 1.
- The session location: `<base>/.zcode/v2/credentials.json`, where `<base>` = `ZCODE_DATA_BASE_DIR`, or `homedir()` if it is not set (`shared-credentials.ts:289`). This is **the same file as the desktop application**, so isolation is required.

## 0-4 Status

- `doctor --json` does not show the login status (only `cli`, `runtime` and `packaging`).
- The **Not Connected** state (with the isolated home and without login): the `-p` command ends with `Error: Model creation failed (traceId: …)` and exit code 1, **with no quota consumption**.
- The **Connected** state: the command `-p "Reply with exactly: OK" --json` returns exit code 0 and JSON containing `response`, `usage` and `projection.status = "idle"`.
- Error code reference (from Z.ai's behavior):
  - `1308` or `1310`: the quota is exhausted, and the timeout is computed according to the window.
  - `401`: the session expired, so re-authentication is required.

## 0-5 Model and provider

- `-p` does not accept a `--model` option. The provider and the model are determined from the provider settings: `<base>/.zcode/v2/<personal provider config>` with `zcode-builtin.json`. The two files can be overridden with `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE` and `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` (`provider-runtime-env.ts`).
- **Discovery:** the CLI on this machine, with the user's current settings, used a custom `openai-compatible` provider from the user's own ZCode CLI settings, not the ZCode account. The Lite quota counter did not change after two calls.
  - **Result:** we do not use the user's settings at all. We work in an isolated home.
- **Correct isolation:** set `ZCODE_DATA_BASE_DIR=<iso>` alone, and **do not change `HOME`**.
  - Changing `HOME` prevents `xdg-open` from finding the default browser, so no tab is opened. And with `--json` the failure message is hidden as well.
  - Login writes nothing except next to the session file, in `<base>/.zcode/v2/` (`auth-login.ts:344-346`).
  - We verified with a snapshot of the file data before and after login: the real ZCode files did not change because of us.
  - `logout` inside the isolation does not touch the desktop app, and this solves the "shared session" problem.
- **Verification (23:20):** after `login zai` in the isolated folder the result was `status: ready` and the model `account:zai-individual-coding-plan/GLM-5.3`, and the two files `credentialsPath` and `configPath` were inside the isolated folder.
  - The verification call used the provider `account:zai-individual-coding-plan` through the address `https://api.z.ai/api/anthropic` (of the anthropic type), and it returned `OK`.
  - **Billing from the Lite plan:** the quota counter rose from 125 to 128, and the level is `level=lite`.

## 0-6 Tools (from `packages/core/src/tool/handlers`, 117 files)

| Type | Tools |
|---|---|
| read (kept) | `Read`, `Glob`, `Grep`, `TodoRead`, `ReadSessionContext` |
| write or execute (blocked) | `Write`, `Edit`, `Bash`, `js`, `mcp__node_repl__js` (and its extensions), `Agent` (subagents), `EvalWorkflowSnippet`, `CreateWorkflow`, `AmendWorkflow`, `SaveWorkflow`, `ResumeWorkflowRun`, `ResolveWorkflowQuestion`, `CronCreate`, `CronUpdate`, `CronDelete`, `OffPeakCreate`, `TodoWrite`, `TaskStop`, `SendMessage`, `RespondToCoordinator`, `submit_result`, `escalate`, `ExitPlanMode` |
| external or interactive (blocked) | `WebFetch`, `WebSearch`, `AskUserQuestion`, `Skill` |
| blocked as a precaution | `GetWorkflowRun`, `ListWorkflowRuns`, `ListSavedWorkflows`, `CronList`, `OffPeakList`, `ListModels`, `TaskOutput` |

- Note: the code classifies `Bash` and `Agent` as `readOnly: true` in the tool definition. This is a classification for interface purposes, not an execution prevention. Therefore we block them explicitly.
- The `glm/packages/*` add-ons (browser-use, pdf, and others) may add MCP tools under other names. The permissions experiment must verify that the model does not see any write tool.
- The forced-permissions experiment has not been run yet. **Adoption is conditional on its success.**

## 0-7 The login mechanism as observed on the machine (2026-09-25)

- **The desktop and the CLI use the same OAuth application** (`client_P8X5CMWmlaRO9gyO-KSqtg`, which is a public identifier and not a secret), with the authorization page `chat.z.ai/api/oauth/authorize`. The difference between them is the return method:

  | | Desktop | CLI |
  |---|---|---|
  | redirect_uri | `zcode://oauth/callback` (a deep link) | `https://zcode.z.ai/api/v1/oauth/cli/callback/zai` |
  | login completion | `oauth.startOAuthWithPolling` then polling every two seconds, with a deep link back to the application | polling through `/oauth/cli/poll/<flowId>` |

- **The flow timeout is about 5 minutes** (`expiresInMs: 299410`) in both cases.
- In the desktop log: the flow started at 23:13:12 and completed at 23:13:27, that is, within 15 seconds.
- **The cause of the first five failures:** the approval arrived after the flow expired. The "Authorization Failed" page that appeared was for a closed flow (logid 23:11:26, while the flow was closed at 23:10:48).
  - **The application in `connect`:** it does not open the tab and then wait for a reply in the conversation. The user runs the command themselves and approves immediately, and sees a countdown. Old tabs must be closed before starting.
- `zcode logout` on the desktop clears the Z.ai login from the application. This is what happened at 23:14:03 by the user's own action, and it has nothing to do with the isolated folder.

## Phase 0 summary

Ready for implementation:

- The runtime is extracted from the AppImage, and it works with Node 26.
- The official browser login works in an isolated folder.
- Verification is possible with a `-p` call.
- Billing is from the Lite plan.

Remaining for a later phase:

- The forced-permissions experiment on the blocklist (0-6), within Phase 4.
- Moving the isolated folder from the scratchpad to a permanent path in Phase 1: `~/.local/share/hydra-pod/zcode/3.14.3/` for the runtime, and `~/.local/share/hydra-pod/zcode-home/` for the session. This requires logging in once more there, or moving the folder as is.
