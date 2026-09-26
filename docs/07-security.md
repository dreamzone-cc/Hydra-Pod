# 7. Security, keys and service terms

## Keys

| Key | Where it is stored | Who uses it |
|---|---|---|
| OpenCode Go | the opencode store, after `opencode auth login` | the builder |
| Z.AI Coding Plan | the opencode store, after `opencode auth login zai-coding-plan` | the reviewer |
| Z.AI (a copy for querying) | `~/.config/hydra-pod/zai.key`, file permissions 600 and directory 700 | `zai-quota.sh` only |

- **No key is ever written** in this repository, nor in `workers.md`, nor in the receipts or the logs.
- Before every commit in the validation projects, this is verified with a `grep` for the key itself.
- The scripts pass the key only in the HTTP header, and do not print it.

## Enforcing read-only for the reviewer

- The prevention **is enforced by the tools**, and does not rely on the model's commitment: the `reviewer` agent has `edit: deny`, and `bash` is allowed only for a specific list of commands.
- Any command added to the `bash` list may become a way to modify files. Do not add general commands (`python3 *`, `node *`, `npm run *`, `make *`).
- Repeat the permissions experiment (the forced attempts) in every new project, and after any change to the list.

## The builder's permissions

- `--auto` means that the builder modifies files and runs commands without asking the operator. This needs **explicit approval for each project**, and it is recorded in `workers.md`.
- The real protection comes from three things: the ticket's boundaries, reviewing the `git diff` at acceptance, and preventing the builder from making a commit.

## Privacy

The project code is sent to OpenCode Go (and through it to the DeepSeek provider) and to Z.ai. The decision on that rests with the operator alone in each project, and the skill asks about it on first use. Review each provider's terms if the project is sensitive.

## Service terms

- Every model runs **through a tool its provider officially supports**. opencode is listed among the supported tools in the Z.ai documentation for the GLM Coding Plan (`docs.z.ai/devpack/tool/opencode`).
- **Deliberately excluded:**
  - reusing the ZCode app's login or session tokens outside ZCode.
  - `pi` with Z.ai: there are reports that it exposes the account to a ban.
