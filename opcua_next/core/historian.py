import threading
import time
from typing import List, Dict, Optional

from ..drivers.python_opcua_driver import PythonOpcUaDriver
from ..storage.timescale import TimescaleStorage


class HistorianManager:
    """Subscribes to selected node IDs and stores data in TimescaleDB."""

    def __init__(self, storage: TimescaleStorage):
        self.storage = storage
        self._driver: Optional[PythonOpcUaDriver] = None
        self._sub_info = None
        self._lock = threading.RLock()
        self._buffer: List[Dict] = []
        self._flush_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self, endpoint: str, node_ids: List[str], interval_ms: int = 1000) -> None:
        with self._lock:
            if self._driver is not None:
                self.stop()

            self.storage.ensure_schema()

            self._driver = PythonOpcUaDriver(endpoint)
            self._driver.connect()

            def handler(node_id: str, value, data):
                ts = getattr(data, 'source_timestamp', None) or getattr(data, 'server_timestamp', None)
                try:
                    ts = ts.isoformat()
                except Exception:
                    ts = time.time()
                rec = {"timestamp": ts, "node_id": node_id, "value": value}
                self._buffer.append(rec)

            self._sub_info = self._driver.create_subscription(interval_ms, node_ids, handler)

            # Start background flush
            self._stop.clear()
            self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._flush_thread.start()

    def _flush_loop(self):
        while not self._stop.wait(1.0):
            try:
                buf = None
                with self._lock:
                    if self._buffer:
                        buf, self._buffer = self._buffer, []
                if buf:
                    self.storage.insert_records(buf)
            except Exception:
                # swallow and continue
                pass

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            if self._flush_thread and self._flush_thread.is_alive():
                self._flush_thread.join(timeout=2)
            if self._driver is not None:
                try:
                    self._driver.disconnect()
                finally:
                    self._driver = None
            # flush remaining
            if self._buffer:
                try:
                    self.storage.insert_records(self._buffer)
                finally:
                    self._buffer = []


