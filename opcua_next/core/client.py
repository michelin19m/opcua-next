from opcua import Client
from contextlib import contextmanager
from typing import Optional


class OPCUAClient:
    def __init__(self, endpoint: str, cert: Optional[str] = None, private_key: Optional[str] = None):
        self.endpoint = endpoint
        self.cert = cert
        self.private_key = private_key
        self.client: Optional[Client] = None

    @contextmanager
    def connect(self):
        """Context manager to connect and disconnect automatically."""
        self.client = Client(self.endpoint)

        if self.cert and self.private_key:
            self.client.set_security_string(
                f"Basic256Sha256,SignAndEncrypt,{self.cert},{self.private_key}"
            )

        try:
            self.client.connect()
            yield self
        finally:
            self.client.disconnect()
            self.client = None

    def browse(self, node_id: str = None, depth: int = 1):
        """Browse nodes starting from root or given node."""
        if not self.client:
            raise RuntimeError("Client is not connected")

        if node_id:
            node = self.client.get_node(node_id)
        else:
            node = self.client.get_root_node()

        return self._browse_recursive(node, depth)

    def _browse_recursive(self, node, depth):
        children = []
        if depth > 0:
            for child in node.get_children():
                try:
                    children.append({
                        "id": child.nodeid.to_string(),
                        "browse_name": str(child.get_browse_name()),
                        "children": self._browse_recursive(child, depth - 1)
                    })
                except Exception as e:
                    children.append({
                        "id": child.nodeid.to_string(),
                        "error": str(e)
                    })
        return children

    def read(self, node_id: str):
        if not self.client:
            raise RuntimeError("Client is not connected")
        node = self.client.get_node(node_id)
        return node.get_value()

    def write(self, node_id: str, value):
        if not self.client:
            raise RuntimeError("Client is not connected")
        node = self.client.get_node(node_id)
        node.set_value(value)

    def subscribe(self, node_ids, handler, publishing_interval=1000):
        if not self.client:
            raise RuntimeError("Client is not connected")
        subscription = self.client.create_subscription(publishing_interval, handler)
        handles = [subscription.subscribe_data_change(self.client.get_node(nid)) for nid in node_ids]
        return subscription, handles