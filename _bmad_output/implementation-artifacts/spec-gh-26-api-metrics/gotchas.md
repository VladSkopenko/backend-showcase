# Gotchas

Found by the independent spec review of 2026-11-18 and checked against the code. Each one breaks the feature if ignored.

## API (CAP-1)

- The `Exception` handler runs in `ServerErrorMiddleware`, outside user middleware. The metrics middleware sees the raw exception with no `http.response.start`: record `status="500"` and re-raise. Record in `finally`, so a stream ended by a client disconnect counts once.
- Two routes stream SSE: `POST /api/v1/assistant/sessions/{session_id}/messages` and `POST /api/v1/assistant/sessions/{session_id}/actions/{action_id}/apply`. Use a pure ASGI middleware; `BaseHTTPMiddleware` buffers streaming.
- `start_http_server` in prometheus-client 0.26.0 binds `0.0.0.0`, returns `(httpd, thread)` and never closes the socket. Stop with `shutdown()`, `server_close()`, `thread.join()`: the suite runs with `filterwarnings = ["error"]`, so a leaked socket fails it.
- Tests must never bind 9000: `METRICS_PORT=0` at import in `tests/conftest.py` and `METRICS_` among the prefixes it strips. `tests/test_cleanup.py` runs the real lifespan.
- Use one registry per app instance: tests build the app many times, and the default registry rejects duplicates.

## Prometheus (CAP-2)

- Tailscale reaches UIs by service name on the platform's `default` network. Prometheus needs `networks: [default, observability]`, because listing any network drops the implicit default.
- Prometheus does not watch its config file, and compose does not recreate a container for a changed bind-mounted file. `deploy/platform/deploy.sh` sends SIGHUP after `up`, like the Caddy reload. Keep `--web.enable-lifecycle` off: the query path is public through Grafana.
- `command:` replaces the image's default arguments, so `--config.file` and `--storage.tsdb.path` must be repeated next to retention and query limits.
- Check the image's user id before writing the `init` line. Do not assume 65534.
- `observability` is created as `--internal` by both deploy scripts, whichever runs first, the same pattern as `analytics-dev`.

## Grafana (CAP-3)

- `backend/tests/test_grafana_dashboards.py` asserts exactly five SQL dashboards in the directory. `api.json` needs its own test covering tag, time range, timezone, `editable: false` and data source uid `prometheus`. Its metric-name check allows the `_bucket`, `_sum`, `_count`, `_total` and `_created` suffixes.
