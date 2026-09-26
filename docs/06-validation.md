# 6. Validation: what was accomplished and proven to work

The validation project is `~/om-sandbox` (the validation sandbox project, not included in this repository): a git repository containing a small Python package named `sandbox.textutil`. All the evidence (receipts, run logs, and review reports) is in `_receipts/` inside it.

## Setup experiments

| Experiment | Result |
|---|---|
| Builder experiment: a `reverse_words` function with a test, in a temporary folder | it succeeded in 24 seconds, and the test actually verifies the output |
| Reviewer connection: the request "Reply with exactly: OK" | it replied within about 4 seconds |
| Reviewer permissions: forced write attempts | the write tool, `touch` and `sed -i` were all rejected with `permission.rejected`, `git log` was allowed, and no file changed |
| Billing: the Z.ai quota before and after the experiments | the value `level=lite`, and consumption rose from 0 to 20 in both the five-hour and weekly windows. That is, consumption is charged to the Lite plan |

## T1: the successful path (top_words)

| Stage | Result | commit |
|---|---|---|
| Plan | a ticket with the specification: upper and lower case are equal, ties are ordered alphabetically, `n <= 0`, and the empty string | (inside `a50b811`) |
| DeepSeek | 26 seconds, 11 tool calls, 7 new tests | |
| Opus accept | re-ran the two acceptance commands: 9/9 succeeded, and the output matches | `a50b811` |
| GLM review | **PASS** with no findings, 13 tool calls | |
| Opus verify | a mutation check: every violation of the specification is caught by at least one test | `743365a` |

## T2 and T2b: the fix loop (min_length + a seeded regression)

| Stage | Result | commit |
|---|---|---|
| DeepSeek (with the unified settings) | 52 seconds, 18 tool calls, 6 new tests, one reasonable open question about Unicode length | `33818a1` |
| Opus accept | 15/15 succeeded, and no existing test was deleted | `33818a1` |
| **a seeded regression** | `split(" ")` instead of `split()`: the tab character and the newline no longer separated the words. All 15 tests passed despite it | `d58bc16` |
| GLM review | **REJECT**: it found the defect and classified it **high**, and attributed it specifically to `d58bc16`. And it added one medium finding and another low | |
| Opus validate | high is correct, and it became T2b. medium is correct but does not need a separate fix. low is correct, **but the value the reviewer suggested was wrong**, so it was corrected | `69b7e9e` |
| DeepSeek fix (T2b) | 65 seconds, 19 tool calls: a one-line fix, a new regression test, and another test that became more precise | `e18f841` |
| Opus final verify | 16/16 succeeded. The regression test **fails on `d58bc16`**. The modified test catches the mutation that measures the length before converting the characters. And the `src` code matches `33818a1` exactly | `0b88ae8` |

## T3 and T3b: two reviewers on the same seeded regression (stage 6, 2026-09-26)

| Stage | Result | commit |
|---|---|---|
| DeepSeek (T3: `stopwords`) | on the first attempt, 14 tool calls, 10 new tests, 26/26 | `d3ce09b` |
| **a seeded regression** | `Counter.most_common` when stopwords are present, so tied words are ordered by order of appearance. It escaped all 26 tests | `f744f60` |
| GLM review via opencode | it found the defect (high), and found two correct medium findings, and one incorrect low finding (UNSURE) | |
| GLM review via ZCode | it found the defect (HIGH), and found the same two medium findings, **with no incorrect finding at all**. The duration was 1:38 and 10 units of Lite | |
| T3b (merging the correct findings from the two reviews) | 29/29, and the three new tests fail on `f744f60`, and `src` became identical to `d3ce09b` again | `9716cd6` |

The details are in `~/om-sandbox/_receipts/T3-reviewer-comparison.md`.

## The account-linking cycle (stage 6)

| Check | Result |
|---|---|
| `disconnect zcode-lite` | ✅ the isolated session only. `test` returned "no active login" without consuming quota. The desktop ZCode files did not change |
| `connect zcode-lite` again | ✅ after adding the retry on flow-start errors (`fetch failed`), the authorization completed in 234 seconds and verification succeeded |
| `disconnect opencode-go` | ✅ it was tried in stage 3 (deleting the key). After it, `connect` went through the browser |
| Secrets check | ✅ no keys and no tokens in the two repositories, including the full git history, and none in the Hydra-Pod caches. The email address appears only in one review report, because the reviewer ran `git log` and displayed the author data that is originally present in every commit |

## Comparison with the baseline

The baseline is the tag `workflow-baseline-t1`: the builder without `--standalone --format json`.

- **The builder:** every build succeeded on the first attempt. The times: 26 seconds (T1), then 52 seconds (T2) and 65 seconds (T2b). The T2 and T2b tickets are larger, so the numbers are not fit for direct comparison.
- **The reviewer:** before the solutions we hit problems 2 and 4 (see 05). After adopting `--standalone --format json` and the watchdog, the T2 review and the T2b fix succeeded on the first attempt.

## Conclusion

The whole workflow was tried on two real paths:
- **The successful path:** T1.
- **The fix path with a real regression:** T2 and T2b.

And the experiment proved that the **finding validation** step is necessary, because the reviewer's suggestion for fixing one of the findings was wrong.
