# 9. Implementation plan: connecting accounts to providers (ZCode Lite and OpenCode Go)

> Status (2026-09-25):
> - **Phase 0 complete**, with the details in `10-zcode-cli-findings.md`.
> - **Phase 1 complete:** `hydra_pod/`, `providers.json`, and `bin/hydra-pod-connect` were finished, the runtime was moved to `~/.local/share/hydra-pod/zcode/3.14.3/`, and 11 unit tests passed.
> - **Phase 2 complete:** the `zcode-lite` provider works. The actual connection was made, the approval took 13 seconds, the verification call succeeded, and the quota was charged to the Lite plan (the counter went from 128 to 129). The real ZCode files were not touched. 21 unit tests passed.
>   - `disconnect` has not been tried directly yet, because it requires logging in again. It will be tried in Phase 6.
> - **Phase 3 complete:** the `opencode-go` provider was finished, with these results:
>   - The official documentation (opencode.ai/docs/go) confirms that OpenCode Go works with the key only, and does not support browser login.
>   - The login through `device` is specific to OpenCode Zen, and Zen deducts from a separate balance. Therefore it was excluded, and `opencode/…` became forbidden to the builder.
> - **Update 2026-09-26:** OpenCode Go is connected from the browser with a device login, as in `docs/08`.
>   - The `connect` command opens the keys page `opencode.ai/auth`, then runs the official key request in an interactive terminal, and the key does not pass through our tools.
>   - The status is read from `opencode auth list`, and the verification is done with a `--standalone --format json` call, with a retry when startup stalls.
>   - The live verification succeeded within 4 seconds, and 30 unit tests passed.
>   - Entering the key was not actually tried, because the key is already stored and re-entering it is unnecessary. It will be tried in Phase 6 along with `disconnect`.

## Goal

```
Connect Account → Browser Login → Authorize → Callback → Verify → Connected
```

The goal is a connection flow like this for every provider, with three separate layers: **Authentication**, **Provider Integration**, and **Credential Storage**. And adding a new provider must be possible without redesigning.

## The "no external dependencies" principle

| Allowed | Forbidden |
|---|---|
| The official tools installed on the machine: `zcode.cjs` bundled in ZCode 3.14.3, `opencode`, `node`, `python3` (standard library only), `bash`, `git` | new npm and PyPI packages, including the unofficial `zcode-app-cli` and `@z_ai/mcp-server` |
| network connections made by the official tools themselves (login, model calls) | the `zcode-open-bridge` code (used as engineering knowledge only, with the source credited) |
| — | reading ZCode or opencode credential files, or writing our own OAuth flow, or calling ZCode's internal endpoints directly |

**Result:** we store no credentials. Every official tool stores its own session or key, and we only ask about the status.

## What was confirmed before writing the plan

- `zcode.cjs` is inside `ZCode-3.14.3-linux-x64.AppImage` at the path `resources/glm/zcode.cjs`. The CLI version is `0.16.9`, and it runs with the installed `node v26.8.2`.
- The official commands it contains:
  - `login` ("Sign in with Z.AI OAuth"), with `--no-browser` to print the link.
  - `logout`.
  - `-p/--prompt`, `--mode`, `--disallowed-tools`, `--json`, and `--cwd`.
- In opencode 2.0.16: `opencode-go` accepts the key only (`key`), and `opencode` (Zen) accepts `device` or `key`.
- **Warning:** the `zcode logout` command clears "the **shared** Z.AI login credentials", meaning the disconnect may also sign the operator out of the ZCode desktop app. We will verify this in Phase 0 before doing any Disconnect.

---

## Phase 0: exploration and verification (read-only, with no modification)

1. **Runtime location:** the proposal is to extract `resources/glm/` from the AppImage to `~/.local/share/hydra-pod/zcode/<app-version>/`, with a `VERSION` file. We verify that the extraction is enough without the rest of the application files (the `packages/` folder next to `zcode.cjs`).
2. **Node compatibility:** ZCode requests Node `24.14`, and the installed one is `26.8.2`. We try `doctor --json` and a simple `-p`. If a problem appears, we use the application's own runtime (Electron with `ELECTRON_RUN_AS_NODE`) instead of installing any new Node.
3. **Login:** reading `login --help` (the options: `zai` or `bigmodel`, `--no-browser`, and `--json`). We determine:
   - Is the CLI session separate from the desktop application session, or shared with it?
   - Where is success or failure reported (the exit code, the JSON output)?
4. **Knowing the status without reading credential files:** does `doctor --json` show the login status? If it does not show it, then the status is known from a small test call, with error code classification:
   - `1310` or `1308`: the quota is exhausted.
   - `401`: not connected, or the session expired.
5. **Model selection in `-p` mode:** through the official ZCode settings (the `/model` command, or the `model` key in `~/.zcode/cli/config.json` as the CLI README documents it), or through the `ZCODE_MODEL` variable if it is documented in the official code. We determine which models are available to the account: GLM-5.3 on Lite, and GLM-5.3-Flash on the ZCode Start Plan (in-app plan).
6. **Tool list:** we extract the tools offered by the installed version, to build the blocklist in Phase 4.

**Phase output:** `docs/10-zcode-cli-findings.md`, containing all of the above with the evidence.

## Phase 1: structure (Python standard library only)

```
hydra_pod/                   a Python package with no dependencies
  providers/
    base.py                     the Provider interface: connect(), status(), test(), disconnect(), worker_command(role)
    registry.py                 the provider registry from providers.json
    zcode_lite.py               delegates everything to the official zcode.cjs
    opencode_go.py              delegates everything to the official opencode
  auth/
    state.py                    NotConnected / Authenticating / Connected / AuthFailed / Expired
    flows.py                    DelegatedBrowserLogin (zcode login), DelegatedKeyLogin (opencode auth login)
  runtime/
    locate.py                   finds zcode.cjs, determines its version, and extracts it from the AppImage when needed
    run.py                      headless execution, with a watchdog, and JSON reading
providers.json                  the provider definitions: the supported methods, the keys page, the test command
bin/hydra-pod-connect                  connect | status | test | disconnect <provider>
```

- **Credential Storage:** we store nothing. Only a temporary cache of the last status (`~/.cache/hydra-pod/status.json`, with no secrets).
- **A new provider:** an entry in `providers.json`, and one file that implements the interface.

## Phase 2: the `zcode-lite` provider

| State or command | Implementation |
|---|---|
| Connect | `node zcode.cjs login zai` opens the browser. `--no-browser` prints the link so we can display it. The state is `Authenticating` until the command exits |
| Callback and Session | inside ZCode alone |
| Verify | `-p "Reply with exactly: OK" --json`. Success means `Connected` |
| Status | the last Verify result, with error code classification (Phase 0-4) |
| Expired | a call that succeeded then started returning 401, so we request re-authentication |
| Disconnect | `logout`, **after an explicit warning** if it is proven to sign the operator out of the desktop app as well |

## Phase 3: the `opencode-go` provider

| State or command | Implementation |
|---|---|
| Connect | opens the official keys page in the browser, then runs `opencode auth login opencode-go` in an interactive terminal. The operator is the one who pastes the key, and it does not pass through our tools |
| Verify | `opencode run --standalone --format json -m opencode-go/deepseek-v4.1-flash "Reply with exactly: OK"` |
| Status | `opencode auth list` with the Verify result |
| Disconnect | `opencode auth logout` (the official command) |

Note: OpenCode Go does not support browser connection without a key in version 2.0.16. We will examine whether a device login to an OpenCode Zen account grants the Go models. If it grants them we add it as a second method, and if it does not grant them we stay with the key.

## Phase 4: ZCode as a reviewer (an alternative to the opencode + zai-coding-plan path)

1. **The review command:** `node zcode.cjs -p "<prompt>" --mode yolo --disallowed-tools "<list>" --json --cwd <scratch>`
2. **The blocklist:** we build it from the installed version's tools (Phase 0-6), making use of the approach documented in zcode-open-bridge. It must include writing, Bash, Node REPL tools, and the dynamic workflow tools.
3. **A forced-permissions experiment:** writing a file, `Bash touch`, `js` with `fs.writeFileSync`, and `EvalWorkflowSnippet`. They must all fail and the tree must remain unchanged. **No adoption before this experiment succeeds.**
4. **The review needs the diff, and the reviewer cannot run git:** Opus writes the diff to `_receipts/<ticket>.diff`, and the reviewer reads it with the read tool.
5. **Integration:** as an option in `workers.md.template` and `init-project.sh`, while the tried opencode + zai-coding-plan path stays the default until the operator decides otherwise.

## Phase 5: integration and documentation

- `init-project.sh` asks about the provider: `hydra-pod-connect status` for every provider, and it offers `connect` for whatever is not connected.
- Update `install.sh`, `README.md`, `02-setup.md`, `05-troubleshooting.md`, and `08-decisions.md`.

## Phase 6: verification

| Check | Criterion |
|---|---|
| unit tests (`unittest`, with a dummy provider) | state transitions, error code classification, JSON parsing, and timeouts |
| an actual zcode-lite connection | `Not Connected` then `Authenticating` then `Connected`, with the link in the `--no-browser` case |
| the ZCode permissions experiment | every write attempt fails, and the tree is unchanged |
| T3 in `~/om-sandbox` (the validation sandbox project, not included in this repository) | a review with ZCode of a ticket containing a seeded regression, and comparing the result with the GLM review via opencode |
| Disconnect then Reconnect | it works. Its effect on the desktop app is documented |
| a secrets scan | there is no key or token in the repository, the logs, or the cache |

## Risks

| Risk | Mitigation |
|---|---|
| a ZCode app update changes `zcode.cjs` or its tool list | we pin the version of the extracted copy in the path (`<app-version>`), and when the version changes we repeat the permissions experiment before use |
| Node 26 incompatibility with 24.14 | the application's own runtime (Phase 0-2) |
| `logout` shared with the desktop app | a warning and confirmation before running |
| the quota shared between ZCode, other tools sharing the same Z.ai account, and the opencode path | check the quota before the review (`zai-quota.sh`) |
| the service terms | we use the official ZCode so that it works by itself, without impersonating it or reading its credentials. Intensive automated use remains the operator's responsibility toward Z.ai's policy |

## Decisions required from the operator before implementation

1. **ZCode as a reviewer:** an optional alternative alongside the current path (proposed), or does it replace it?
2. **The source of `zcode.cjs`:** extraction from the installed AppImage (proposed, and it needs no download), or building from the repository (needs pnpm and downloads)?
3. **Disconnect:** if it is proven that `logout` signs the operator out of the desktop app, do we settle for showing a warning, or disable the command and ask the operator to run it manually?

---

> **Phase 4 complete (2026-09-26):**
> - The command `hydra-pod-connect review zcode-lite` was added.
> - The tools available to the reviewer are only three: Read, Glob and Grep, and MCP is disabled, and this is verified for every runtime version.
> - The forced-write experiment succeeded, and a real review of the T2 scope succeeded and found the seeded regression.
> - 36 unit tests pass.

> **Phase 5 complete (2026-09-26):**
> - `install.sh` links `hydra-pod-connect` into `~/.local/bin`, and does not replace any file not related to the repository.
> - `init-project.sh` shows the account status without consuming the quota.
> - `scripts/zcode-review-prep.sh` was added, and it creates the diff files, the commits, and the request file with absolute paths. If the working tree differs from head, it takes a snapshot of head.
> - `/hydra-pod` now checks the accounts before dispatch, closes stdin, and offers the ZCode reviewer as an option.
> - All of the above was tried in temporary folders, then actually installed (with a backup of `/hydra-pod`).

> **Phase 6 complete (2026-09-26). The plan is fully implemented:**
> - The `disconnect` then `connect` cycle was actually tried. Retrying on flow-startup errors was added.
> - T3 was run as a comparison between the two reviewers on a seeded regression, and both found it.
> - It passed the final secrets scan.
> - Unit tests: 37.
