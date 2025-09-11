from abc import ABC, abstractmethod


class BaseDriver(ABC):
    """Driver abstraction for OPC UA transports/stacks.

    Implementations must be thread-safe enough for the MVP's usage pattern.
    """

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def browse_recursive(self, depth: int = 1) -> list:
        """Return a nested list/dict describing address-space nodes."""
        raise NotImplementedError

    @abstractmethod
    def read_node(self, nodeid: str):
        raise NotImplementedError

    @abstractmethod
    def write_node(self, nodeid: str, value) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_subscription(self, interval_ms: int, nodeid_list: list, callback):
        """Create subscription and return a subscription wrapper. Callback signature: (nodeid, value, data)
        """
        raise NotImplementedError