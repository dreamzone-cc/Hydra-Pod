# 8. Decisions log

| Date | Decision | Reason |
|---|---|---|
| 2026-09-25 | adopting the distribution: Opus manages, DeepSeek (OpenCode Go) builds, and GLM-5.3 (Z.ai Lite) reviews | using the existing subscriptions, each through its own service, instead of a paid API for each model |
| 2026-09-25 | adopting the flow and the fix-loop rules (findings are validated before any change) | every role stays within its boundaries, and files are not modified because of an incorrect finding |
| 2026-09-25 | the reviewer runs via opencode and the `zai-coding-plan` provider | an official path, and opencode stores the key. It is superior to the alternative of running `claude -p` with Z.ai variables |
| 2026-09-25 | a project-specific `reviewer` agent instead of `plan` | the `plan` agent allows any shell command |
| 2026-09-25 | both roles run with `--standalone --format json` | a remedy for the shared service stopping and the defect of `opencode run` not returning after the session finishes. The previous baseline is the tag `workflow-baseline-t1` in om-sandbox (the validation sandbox project, not included in this repository) |
| 2026-09-25 | every run passes through `run-watchdog.sh` | intermittent stopping when the private server starts |
| 2026-09-25 | excluding `pi` with Z.ai | reports that it exposes the account to a ban |
| 2026-09-26 | **OpenCode Go is linked from the browser** (`hydra-pod-connect connect opencode-go`), and the key is an alternative | the experiment in the real environment: the Go key was removed via `hydra-pod-connect disconnect`, so the result was `Model unavailable`. Then the login was done via `opencode auth login opencode --method device`, so `opencode-go/deepseek-v4.1-flash` answered `OK` in both attempts. The previous opposite result was wrong, and its cause was problem 0 (stdin open), not the login itself. **Billing:** verify it on the usage page in the Console, and it must appear under Go, not under Zen |
| 2026-09-26 | ZCode as an alternative reviewer (optional), and the opencode + zai-coding-plan path stays the default | in the forced-write experiment the Write, Edit, Bash, js, workflow and subagent tools were **not present at all**, and the version did not change. And in a real review of the seeded T2 scope it found the regression (high), and suggested a correct value for the weak test. As for its third finding (UNSURE: commit `d58bc16` is not mentioned in the receipt), it is **partially correct**: the commit is indeed outside the documented work, and it is the seeded regression, but its attribution to the builder is wrong. The cause of the error is that the prompt text in the experiment did not mention that Opus is the one who makes the commits, and that was added later in `prompts/reviewer-zcode.md`. The result: 3 findings, 2 correct and 1 partially correct. The cost was 15 units of Lite and the duration 2:35 |
| 2026-09-26 | **The project is renamed Hydra-Pod** for its public release (AGPL-3.0-or-later) | the commands, the package, the environment variables and the folders were renamed, and the legacy `om-*`, `opus_manager` and `OM_*` names are kept as fallbacks; the vendored skill keeps its upstream name `opus-manager` and its MIT license |

## Known and open limitations

- The framework has been tried only on a small Python project. In every new project, adjust the reviewer's command list and repeat the permissions experiment.
- The options and commands are documented for version **opencode 2.0.16**. Re-verify problems 1 to 6 in `05-troubleshooting.md` after any upgrade.
- The reviewer cannot run `python3 -c`, so it verifies some acceptance commands by reading the code. Opus runs them itself at acceptance.
- The root cause of the stop at startup (problem 5) is unknown, and the watchdog only works around it.
- The Z.ai Lite quota is also consumed by other tools sharing the same Z.ai account, and by ZCode.
