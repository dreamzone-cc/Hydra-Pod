---
ticket: T<N>-<slug>
state: open
worker: opencode-go/deepseek-v4.1-flash
base:
head:
test_command: <the project's exact test command, allowed in opencode.json>
allowed_files:
  - <path>
acceptance:
  - <command that must exit 0>
  - <command> ==> <text that must appear in its stdout>
earlier_specs:
  - <path of an earlier ticket whose rules still apply, or remove this key>
reviewers:
  - opencode        # and/or: zcode
---
# T<N>: <short title>

> from: Claude Code (Opus 5.5) | date: YYYY-MM-DD | worker: opencode:opencode-go/deepseek-v4.1-flash
> claimed-by: (the manager fills this in at dispatch)

## Goal
<One sentence: what problem this ticket solves.>

## Read first
1. <project rules, specs, files this change touches>

## Boundaries
1. Touch only the files in `allowed_files`. Nothing else (the receipt file excepted).
2. No secrets in code, docs or logs.
3. No git commit / push (the manager commits after acceptance).
4. Leave this ticket file in `_tickets/doing/`.

## Specification
<exact behaviour, including edge cases>

## Acceptance
The commands in the header, run by `hydra-pod-dispatch accept`. The worker pastes their unedited output in its receipt.

## Why these checks
<What real outcome the checks protect. Passing the checks is not the goal; this is.>

## Deliverables
- <files to create or change>
