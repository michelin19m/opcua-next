"""Driver implemented on top of python-opcua (FreeOpcUa)."""

import logging
import threading
import time
from typing import List

from opcua import Client

from .base import BaseDriver

logger = logging.getLogger(__name__)


class _SubHandler:
    def __init__(self, cb):
        self._cb = cb

    def datachange_notification(self, node, val, data):
        try:
            nid = node.nodeid.to_string()
        except Exception:
            try:
                nid = getattr(node, "nodeid", str(node))
            except Exception:
                nid = str(node)
        try:
            self._cb(nid, val, data)
        except Exception:
            logger.exception("subscription callback error")


class PythonOpcUaDriver(BaseDriver):
    def __init__(self, endpoint: str, security: dict | None = None, timeout: int = 4):
        super().__init__(endpoint)
        self.security = security
        self._client: Client | None = None
        self._lock = threading.RLock()
        self._connected = False

    def connect(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception:
                    pass

            self._client = Client(self.endpoint)

            # Basic convenience: support security dict {policy, cert, key}
            if self.security:
                policy = self.security.get("policy")
                cert = self.security.get("cert")
                key = self.security.get("key")
                if policy and cert and key:
                    # python-opcua expects a single security string
                    sec_string = f"{policy},SignAndEncrypt,{cert},{key}"
                    try:
                        self._client.set_security_string(sec_string)
                    except Exception:
                        logger.exception("set_security_string failed; continuing without it")

            # Attempt connect
            self._client.connect()
            self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception:
                    logger.exception("error on disconnect")
                finally:
                    self._client = None
            self._connected = False

    def is_connected(self) -> bool:
        # Quick-and-practical connectivity check
        with self._lock:
            if self._client is None:
                return False
            try:
                # touch root node — will raise on broken transport
                self._client.get_root_node()
                return True
            except Exception:
                return False

    def browse_recursive(self, depth: int = 1) -> list:
        with self._lock:
            root = self._client.get_root_node()
            return self._browse_node(root, depth)

    def _browse_node(self, node, depth: int) -> list:
        if depth <= 0:
            return []
        result = []
        try:
            children = node.get_children()
        except Exception:
            return result
        for ch in children:
            try:
                browse_name = ch.get_browse_name().Name
            except Exception:
                browse_name = str(ch)
            entry = {
                "browse_name": browse_name,
                "nodeid": ch.nodeid.to_string(),
            }
            if depth > 1:
                entry["children"] = self._browse_node(ch, depth - 1)
            result.append(entry)
        return result

    def read_node(self, nodeid: str):
        with self._lock:
            node = self._client.get_node(nodeid)
            return node.get_value()

    def write_node(self, nodeid: str, value) -> None:
        with self._lock:
            node = self._client.get_node(nodeid)
            node.set_value(value)

    def create_subscription(self, interval_ms: int, nodeid_list: List[str], callback):
        """Create a subscription and subscribe to nodeids.

        Returns a dict with keys: 'sub' (the subscription), 'handles' (list), 'nodes'.
        """
        with self._lock:
            handler = _SubHandler(callback)
            subscription = self._client.create_subscription(interval_ms, handler)
            handles = []
            for nid in nodeid_list:
                try:
                    node = self._client.get_node(nid)
                    handle = subscription.subscribe_data_change(node)
                    handles.append(handle)
                except Exception:
                    logger.exception("subscribe_data_change failed for %s", nid)
            return {"sub": subscription, "handles": handles, "nodes": nodeid_list, "handler": handler}