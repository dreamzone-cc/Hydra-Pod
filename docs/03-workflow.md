# 3. Workflow

## The adopted flow

```
Opus 5.5 → Plan → DeepSeek V4.1 Flash → Implement → Tests → GLM-5.3 Review
        → Validate Findings → Fix Ticket → DeepSeek Fix → Tests → Opus Final Verification → Done
```

## Ticket lifecycle

```
_tickets/open/     ready to be built ("write two, dispatch one")
      │  git mv to doing/ is the lock. Opus fills the claimed-by line (tool, model, time)
_tickets/doing/    being built, and stays here until the review finishes
      │
_tickets/done/     accepted, reviewed, and verified by Opus
_tickets/blocked/  waiting on something from outside the project (the reason is stated in its header)
_tickets/dropped/  cancelled (the reason is stated)
_receipts/         receipts, run logs (.jsonl), review reports (.review.md), and watchdog logs
```

## The steps in detail

1. **Plan (Opus):** writes the ticket with the `skill/opus-manager/templates/ticket.md` template, containing:
   - a one-sentence goal, and the list of files that may be modified only.
   - acceptance criteria in the form of **commands, not opinions**.
   - a **"why these checks"** paragraph saying what the tests must actually protect.
2. **Dispatch:** uses the command registered in `workers.md`, through the watchdog (see 04).
3. **Implement + Tests (DeepSeek):** modifies only the allowed files, runs the acceptance commands, and writes the receipt with the raw output.
4. **Accept (Opus):** the receipt is a claim, not evidence, therefore:
   - Opus re-runs **every** acceptance command itself and compares the output.
   - It reviews `git status` and `git diff`, and no change outside the allowed files is accepted.
   - It reads the "open questions" in the receipt.
   - If all that succeeds, it makes one commit naming the ticket.
5. **Review (GLM-5.3):** uses the registered command through the watchdog, and specifies a particular commit range `<base>..<head>`. The report is saved in `_receipts/<ticket>.review.md`.
6. **Validate Findings (Opus):** opens every finding in the code and reproduces it. See the rules below.
7. **Fix Ticket, then DeepSeek Fix, then Tests:** a new ticket such as `T<N>b` containing only the correct findings, with the values Opus corrected.
8. **Final Verification (Opus):** re-runs all the checks, and makes sure the regression test **fails on the broken code** and passes after the fix.
9. **Done:** Opus moves the tickets to `done/` and commits.

## Fix-loop rules (adopted)

- GLM's findings **are examined before any change to the code**.
- A correct finding becomes an explicit fix ticket for DeepSeek.
- An incorrect finding is rejected with a single line stating the reason, and the line is added at the end of the review report.
- **The fix suggested by the reviewer is not passed through without examination.** In T2 the expected value that GLM suggested for the third finding was wrong, and it would have produced a wrong test if passed through as is.
- GLM only reviews, DeepSeek only builds within the ticket's scope, and Opus is responsible for coordination, verification and final acceptance.
- If the fix is large, the review is repeated (and the file is named `.review-2.md`, without replacing the first report).
- The task does not end until every acceptance criterion passes.

## Seeding a regression to test the fix loop (optional)

This method was used in T2 to verify that the loop actually works:
1. After accepting a ticket, Opus makes a commit containing a limited real regression **that the existing tests do not catch**, but that violates the specification.
2. **The documentation of the regression stays outside the repository** until the review finishes, because the reviewer reads all the files in it.
3. GLM reviews a range that includes the seeded commit without any hint.
4. After the review, the documentation is added to the repository, such as `_receipts/T2-seed-note.md`, with Opus's verdict on every finding.
