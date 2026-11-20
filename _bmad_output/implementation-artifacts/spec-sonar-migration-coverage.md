---
title: 'Sonar ignores migrations in coverage'
type: 'chore'
created: '2026-11-20'
status: 'done'
baseline_commit: '1dcec2f'
route: 'oneshot'
review_loop_iteration: 0
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** PR #69 failed the SonarQube Cloud quality gate on new-code coverage (0% against 80%): the 15 lines of migration `0026` counted as uncovered, although ten tests run it. CI measures coverage for the `app` package only (`pytest --cov=app`), and tests load migrations through `importlib`, so migrations never reach `coverage.xml`.

**Approach:** Exclude `backend/migrations/**` from coverage with `sonar.coverage.exclusions` in `sonar-project.properties`, as agreed after the Sonar review of 2026-11-19 (Vlad's go, 2026-11-20). Migrations stay analysed for bugs and code smells; only coverage ignores them.

</frozen-after-approval>

## Implementation Notes

- Key checked in the SonarQube Cloud docs: `sonar.coverage.exclusions` "Defines the source files to be excluded from the code coverage analysis", comma-separated path patterns relative to the project base directory.
- The rest of the agreed exclusions (`_bmad/**`, `n8n/**`) stay out of this change.
- Verification: the PR's SonarQube Cloud quality gate.
