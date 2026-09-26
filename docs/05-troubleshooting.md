# 5. Problems and their solutions

Everything below actually happened on 2026-09-25 and was diagnosed with evidence, and the version concerned is opencode 2.0.16.

## 1. `opencode auth login zai-coding-plan` fails

- **Symptoms:** the message `API key input requires an interactive terminal` appears. And with `--method key --answer key=…` the message `Unknown form field` appears.
- **Cause:** entering the key requires a real interactive terminal.
- **Solution:** run the command in a separate terminal window.

## 2. The reviewer stops with no output at all (the shared service)

- **Symptoms:** an empty log, 0 CPU usage, and no connection to api.z.ai.
- **Cause:** `opencode run` connects by default to the `opencode serve --service` service running in the background, and it does not see authentication or the environment added after it started.
- **Solution:** `--standalone`.

## 3. `ZHIPU_API_KEY` or the `provider` section in opencode.json does not enable the provider

- **Symptoms:** the command `opencode models` shows no `zai-coding-plan/*` model, and the run commands stop with no message.
- **Solution:** use `opencode auth login` only (problem 1).

## 4. `opencode run` does not return even though the session has finished

- **Symptoms:** no output, and the command does not exit. But the command `opencode session export` shows `outcome: succeeded` and `idle` after a few seconds.
- **Cause:** a defect in version 2.0.16 prevents the `opencode run` tool from noticing that the session has finished, in the default mode only. It happens sometimes, not always.
- **Solution:** `--format json`, and it succeeded in every run after it was adopted.
- **Note:** we first suspected that the `@` symbol in the prompt text was the cause. That was not proven, because the stop returned after it was removed.

## 0. (the root cause, discovered on 2026-09-26) `opencode run` waits for stdin

- **Symptoms:** any `opencode run` command produces no events, no session, and no CPU usage, and ends in a timeout. It happens with all models and all environments.
- **Cause:** if stdin is not a terminal and is not closed, then `opencode run` reads it as part of the message and waits for it to end.
- **Proof:** the same command stops with `> file 2> file`, and succeeds within 3 seconds with `< /dev/null` or when run from Python with `stdin=DEVNULL`.
- **Solution:** always close stdin (`< /dev/null`).
  - `run-watchdog.sh` now closes it.
  - `hydra_pod.runtime.proc.run` closes it by default.
- **Its effect on the rest of this page:** it is likely that this is the cause of problem 5, and of at least part of problem 4. It is also the cause of the failure of the first isolated-environment experiment for logging into OpenCode.

## 5. The private server does not start the session at all

- **Symptoms:** no session is created, and no events arrive even with `--format json`, and the command ends in a timeout (124).
- **Cause:** most likely problem 0 (stdin open). The run succeeded or failed according to what stdin inherited from the parent process.
- **Solution:** `run-watchdog.sh`, which retries if no event arrives within 90 seconds. It succeeded on the first attempt in every subsequent run.

## 6. The `plan` agent is not read-only

- **Discovery:** the command `opencode debug agents` shows that `plan` = `allow * *` + `deny edit *`, meaning it allows the shell.
- **In the experiment:** the model refused to write "on its own", but that is only a commitment from the model, not a prevention enforced by the tools.
- **Solution:** a `reviewer` agent with `bash` restricted to a list. The forced experiment proved that `touch`, `sed -i` and the write tool were all rejected with `permission.rejected`.

## 7. `pkill -f` kills the shell that launched it

- **Cause:** the pattern `pkill -f "…"` also matches the command line of the shell that contains the same text.
- **Solution:** stop the processes by their number (PID) after taking it from `pgrep -fa`, or leave the stopping to the watchdog.

## A quick checklist when any run stops

1. `opencode auth list`: is the required provider registered?
2. `opencode session list | head`: was a session created? If not, it is problem 5, so retry through the watchdog.
3. `opencode session export <id>`: is the `outcome` value `succeeded`? If so, it is problem 4, so extract the result from the session.
4. `ss -tnp | grep <pid>`, and `ps -o time -p <pid>`: no connection and no CPU usage means it is waiting for something.
5. `~/Hydra-Pod/scripts/zai-quota.sh`: is the quota exhausted? In that case the server returns error 1310 or 429.
