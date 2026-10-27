# Safety

- Never `git add`, `git commit` or `git push` unless Vlad explicitly asks in the current task.
- Never change git state: no checkout, switch, branch, pull, fetch, stash, reset, merge or rebase.
- Never delete files: no `rm`, no `git rm`, no unlink, even for dead code. Ask first.
- Never read `.env` or other secret files. If a setting seems missing, ask.
- Never run formatters unless asked. The pre-commit hook formats staged files.
- Reproduce bugs through the real API with curl. Never mint tokens or write data with SQL;
  read-only SELECTs on the local database are fine.
- When the environment breaks, such as a misbehaving server, an unexplained 500 or a failing tool,
  report and wait. Do not spin up workarounds like a second server instance.
