---
title: 'n8n workflow checks as a small Node project'
type: 'refactor'
created: '2026-11-14'
status: 'done'
baseline_commit: '63799301a1fe2b2120526102afafc6b5fe22d5f2'
route: 'oneshot'
review_loop_iteration: 0
context:
  - '{project-root}/n8n/README.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The checks for the two n8n workflows are two loose scripts in `n8n/` (`check-simulator-plan.mjs`, `check-waiter-plan.mjs`) with no `package.json`, no test runner, and the same helpers copied into both (loading Code nodes from the workflow JSON with `node:vm`, the seeded PRNG, the binomial tolerance, the execution emulator and stubs).

**Approach:** Turn `n8n/` into a small Node project without dependencies, shaped like the backend's `tests/` and `tests/support/`:
- `n8n/package.json` (private, `"type": "module"`, an `engines.node` matching the Node in use, script `test` = `node --test tests/`).
- `n8n/tests/booking-simulator.test.mjs` and `n8n/tests/waiter-bot.test.mjs` — the current checks as `node:test` tests (`describe`/`test`), one test per current `ok` line or group, same assertions, same tolerances, same seeds (`SIMULATOR_SEED`, `WAITER_SEED` still repeat a run; a failing test prints its seed).
- `n8n/tests/support/` — the shared helpers, one module per concern; no copies left in the test files.
- `n8n/README.md` points to `npm test` in `n8n/` instead of the scripts. The two old scripts are not deleted by the implementer (no `rm`, no `git rm`); the parent session asks Vlad and removes them.

Behaviour of the checks does not change: every assertion that exists today exists after, nothing new is added. No dependencies, no linters, no CI change (CI is Vlad's); the workflow JSON files are not touched.

</frozen-after-approval>

## Implementation Notes

- 2026-11-14: `n8n/package.json`, `n8n/tests/{booking-simulator,waiter-bot}.test.mjs`, shared helpers in `n8n/tests/support/` (constants, random, checks, shares, workflow, emulator, staff-api). `npm test` passes 163 of 163 (122 + 41, one per former `ok` line). The implementer compared old and new failure lines at a 0.5 SE tolerance for four seeds: identical. The parent session reran `npm test` and removed the two old scripts with Vlad's go-ahead.
