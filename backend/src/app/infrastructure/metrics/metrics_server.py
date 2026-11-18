import threading
from wsgiref.simple_server import WSGIServer

from prometheus_client import CollectorRegistry, start_http_server


class MetricsServer:
    def __init__(self, *, port: int, registry: CollectorRegistry) -> None:
        self._port = port
        self._registry = registry
        self._server: WSGIServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("The metrics server has not been started")
        return self._server.server_port

    def start(self) -> None:
        self._server, self._thread = start_http_server(self._port, registry=self._registry)

    def stop(self) -> None:
        # start_http_server never closes its socket; shutdown alone leaves it open.
        if self._server is None or self._thread is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
