---
title: 'Menu dishes as a data migration'
type: 'feature'
created: '2026-11-09'
status: 'in-progress'
baseline_commit: '2e742a42a52113772dded3d5998bd01c57f08935'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The dev API serves an empty menu (`GET /api/v1/menu/dishes` → `total: 0`). The menu spec planned to seed dev from the developer machine through an SSH tunnel, but by ADR 2 humans have no SSH or network path to the server, so the dev database cannot be seeded that way. The 30 pictures are already in the dev bucket.

**Approach:** Decision (Vlad, 2026-11-09): migration `0007` inserts the 30 dishes of `backend/seed/menu/dishes.json` as data, so every deploy fills its database. Rows are written with `INSERT … ON CONFLICT (slug) DO NOTHING`, so databases already seeded by the script (the local one) keep their rows; `created_at` and `updated_at` are fixed timestamps, one minute apart in file order (first entry newest); `downgrade` deletes those 30 slugs. The migration holds the data as literals (the seed folder stays git-ignored). Test modules that count dishes start each test from an empty `dishes` table inside the rolled-back test transaction. Pictures for staging and prod buckets are out of scope.

</frozen-after-approval>

## Implementation Notes

- `backend/migrations/versions/0007_add_menu_dishes.py` holds the 30 dishes as literals generated from `backend/seed/menu/dishes.json`; `image_key` is `dishes/<slug>.jpg`, timestamps step back one minute from 2026-11-09 12:00 UTC in list order.
- `backend/tests/test_menu_data_migration.py` (written first; 2 of 3 failed before the migration) checks 10 dishes per category, picture keys and the newest dish. `test_menu.py` and the async tests of `test_seed_menu.py` delete the migrated dishes inside the rolled-back test transaction.
- Verification: ruff, format, mypy, lint-imports, 255 tests; on a throwaway PostgreSQL 18 an already-seeded `pkhali-trio` (popularity 999) survived `upgrade`, 30 rows after it, 0 after `downgrade 0006`, 30 again after `upgrade`, `alembic check` clean.
