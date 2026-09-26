# 2. Setup

## Prerequisites

| Tool | Tested version | Notes |
|---|---|---|
| Claude Code | 2.1.x | on a Claude Pro subscription, and **connects directly to Anthropic** with no intermediary (see 05) |
| opencode | 2.0.16 | the commands documented here are specific to this version. Re-verify when upgrading |
| git and bash and python3 | — | for the acceptance commands and scripts |
| curl | — | for `zai-quota.sh` |

## 1. Installing the skill and the /hydra-pod command

```bash
~/Hydra-Pod/scripts/install.sh           # installs what is missing, and reports any differing file without touching it
~/Hydra-Pod/scripts/install.sh --force   # replaces differing files, after moving a backup to ~/.claude/backups/hydra-pod/<timestamp>/
```

The script installs:
- `skill/opus-manager` into `~/.claude/skills/opus-manager`
- `claude/commands/hydra-pod.md` into `~/.claude/commands/hydra-pod.md`

### Upgrading from an earlier opus-manager install

An existing installation keeps working after the rename, with no migration step:

- The config, key file, ZCode runtime and cache folders are still read under the legacy `opus-manager` names; each legacy folder is used only when the corresponding `hydra-pod` folder does not exist, and nothing is moved or copied.
- The legacy environment variables `OM_COMMIT_TRAILER`, `OM_MIN_ZAI_CREDITS` and `OM_BIN_DIR` are still read when the corresponding `HYDRA_POD_*` variable is unset.
- `install.sh` installs `/hydra-pod` and the `hydra-pod-*` links, but it leaves an old legacy `/om` command and legacy `om-*` links untouched; remove them by hand if you no longer want them.

## 2. OpenCode Go authentication (for the builder)

The preferred method is browser login, without a key. Actually tested on 2026-09-26:

```bash
~/Hydra-Pod/bin/hydra-pod-connect connect opencode-go          # shows a code and a link, and opens opencode.ai/console/device
~/Hydra-Pod/bin/hydra-pod-connect connect opencode-go --method key   # alternative: the key (needs an interactive terminal)
```

- The browser method calls `opencode auth login opencode --method device`, which is an official command. After approval, the line `OpenCode Console  Default  stored` appears in `opencode auth list`.
- **With this login alone, without a Go key,** `opencode-go/deepseek-v4.1-flash` responds. We verified this with a control experiment: with no login the result is `Model unavailable`, and after the Console login it is `OK`.
- **The model always stays `opencode-go/…`**. The same login also enables Zen models (`opencode/…`), but they are charged to the separate Zen balance, so do not use them.

## 2b. ZCode Lite (optional alternative reviewer)

```bash
hydra-pod-connect runtime install          # extracts the official CLI from the installed ZCode app (without downloading)
hydra-pod-connect connect zcode-lite       # Z.ai login through the browser; approve within about 5 minutes
hydra-pod-connect test zcode-lite
```

- The session is isolated in `~/.local/share/hydra-pod/zcode-home`, and does not affect the desktop ZCode app.
- Consumption is charged to the Z.ai Lite plan itself.

## 3. Z.AI Coding Plan authentication (for the reviewer)

```bash
opencode auth login zai-coding-plan
```

- **Needs a real interactive terminal.** Run it in a separate terminal window, not through `!` inside Claude Code. Otherwise it fails with the message `API key input requires an interactive terminal`, and `--method key --answer …` does not work with it in version 2.0.16.
- Confirm success with the command `opencode auth list`, and `Z.AI Coding Plan  Z.AI Coding Plan  stored` must appear.
- **Do not rely on the environment variable `ZHIPU_API_KEY`, nor on the `provider` section in `opencode.json`.** We tried both methods in 2.0.16, and neither of them enabled the provider (it showed 0 models), so `opencode run` stopped with no message at all.

## 4. The key file (for quota query only)

The review itself uses the key that opencode stored. This file is needed only by `zai-quota.sh`:

```bash
mkdir -p ~/.config/hydra-pod && chmod 700 ~/.config/hydra-pod
# put the key on the first line of the file (with a text editor, not with echo, so it is not saved in the command history)
chmod 600 ~/.config/hydra-pod/zai.key
~/Hydra-Pod/scripts/zai-quota.sh        # shows plan level: lite and the quota, and does not print the key
```

## 5. Preparing a project

```bash
~/Hydra-Pod/scripts/init-project.sh /path/to/project
```

- Creates `_tickets/{open,doing,done,blocked,dropped}` and `_receipts/`.
- Adds `_tickets/run-watchdog.sh` and `_tickets/workers.md` (a draft).
- Adds `opencode.json`, containing the `reviewer` agent that actually prevents modification.
- **Does not replace any existing file.** If the project has an `opencode.json` without a `reviewer` agent, it asks you to merge the section manually.

**One manual step:** edit the allowlist of `bash` commands permitted to the reviewer in `opencode.json` to suit your project's test command. The template permits only read-only git commands and `python3 -B -m unittest*`. For example, in a Rust project:

```json
"cargo test*": "allow"
```

Do not allow general commands such as `python3 *` or `bash *` or `npm run *`, because they open a door for the reviewer to modify files.

## 6. First use in a project

From inside the project in Claude Code:

```
/hydra-pod <the task>
```

If `workers.md` is not complete, the skill runs the first-use steps:
1. It asks you one by one: who builds, who reviews, which model for each of them, who is allowed to see the code, and whether you allow modification without asking permission.
2. It runs a small experiment for each role. For the reviewer it is a permissions experiment: it asks it to attempt forced writes, and all of them must be rejected with `permission.rejected`.
3. It completes the `workers.md` file with what you agreed to.
