"""Driver implemented on top of python-opcua (FreeOpcUa)."""

import logging
import threading
import time
from contextlib import contextmanager
from typing import List, Dict, Optional, Union, Callable
import pdb

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
    def __init__(self, endpoint: str, security: Optional[Dict] = None, timeout: int = 4, auto_reconnect: bool = True):
        super().__init__(endpoint)
        self.security = security
        self.timeout = timeout
        self.auto_reconnect = auto_reconnect
        self._client: Optional[Client] = None
        self._lock = threading.RLock()
        self._connected = False
        self._reconnect_thread: Optional[threading.Thread] = None
        self._stop_reconnect = threading.Event()

    def _connect(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception:
                    pass

            self._client = Client(self.endpoint)
            # self._client.set_session_timeout(self.timeout * 1000)  # Convert to milliseconds

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
            
            # Start auto-reconnect thread if enabled
            if self.auto_reconnect:
                self._start_reconnect_thread()

    def _disconnect(self) -> None:
        with self._lock:
            # Stop reconnect thread
            self._stop_reconnect.set()
            if self._reconnect_thread and self._reconnect_thread.is_alive():
                self._reconnect_thread.join(timeout=2)
            
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
            return self._browse_node(root)
        
    def _browse_node(self, node) -> list:
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
            # Only recurse if this node has children
            try:
                ch_children = ch.get_children()
            except Exception:
                ch_children = []
            if ch_children:
                entry["children"] = self._browse_node(ch)
            else:
                # Leaf node: try to get value
                try:
                    entry["value"] = ch.get_value()
                except Exception:
                    entry["value"] = None
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

    def _start_reconnect_thread(self) -> None:
        """Start the auto-reconnect thread."""
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        
        self._stop_reconnect.clear()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, 
            daemon=True,
            name=f"opcua-reconnect-{id(self)}"
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """Auto-reconnect loop that runs in a separate thread."""
        while not self._stop_reconnect.is_set():
            try:
                # Check connection every 5 seconds
                if self._stop_reconnect.wait(5):
                    break
                
                if not self.is_connected():
                    logger.warning("Connection lost, attempting to reconnect...")
                    try:
                        self._connect()
                        logger.info("Successfully reconnected to OPC UA server")
                    except Exception as e:
                        logger.error(f"Reconnection failed: {e}")
                        
            except Exception as e:
                logger.exception("Error in reconnect loop")
                time.sleep(5)  # Wait before retrying

    def connect(self) -> None:
        """Connect to the OPC UA server."""
        self._connect()

    def disconnect(self) -> None:
        """Disconnect from the OPC UA server."""
        self._disconnect()

    @contextmanager
    def connect_context(self):
        """Context manager to connect and disconnect automatically."""
        self._connect()
        try:
            yield self
        finally:
            self._disconnect()