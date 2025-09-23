import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_DIR = Path(os.getenv("OPCUA_NEXT_STATE_DIR", Path.home() / ".opcua_next"))
DEFAULT_PATH = DEFAULT_DIR / "state.json"


class StateStore:
    """Simple JSON-backed store for servers and their saved tags.

    Schema:
      {
        "servers": [
           {"id": "hash", "endpoint": "opc.tcp://...", "name": "Server A", "tags": [
               {"node_id": "ns=2;i=1", "path": "Objects/PLC1/Speed"}
           ]}
        ]
      }
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"servers": []})

    def _read(self) -> Dict:
        with self._lock:
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {"servers": []}

    def _write(self, data: Dict) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp.replace(self.path)

    def list_servers(self) -> List[Dict]:
        return self._read().get("servers", [])

    def upsert_server(self, endpoint: str, name: Optional[str] = None) -> Dict:
        data = self._read()
        servers = data.setdefault("servers", [])
        # id can be endpoint for simplicity
        sid = endpoint
        for s in servers:
            if s.get("id") == sid:
                if name is not None:
                    s["name"] = name
                self._write(data)
                return s
        entry = {"id": sid, "endpoint": endpoint, "name": name or endpoint, "tags": []}
        servers.append(entry)
        self._write(data)
        return entry

    def delete_server(self, server_id: str) -> None:
        data = self._read()
        data["servers"] = [s for s in data.get("servers", []) if s.get("id") != server_id]
        self._write(data)

    def list_tags(self, server_id: str) -> List[Dict]:
        for s in self._read().get("servers", []):
            if s.get("id") == server_id:
                return s.get("tags", [])
        return []

    def add_tag(self, server_id: str, node_id: str, path: str) -> None:
        data = self._read()
        for s in data.get("servers", []):
            if s.get("id") == server_id:
                tags = s.setdefault("tags", [])
                if not any(t.get("node_id") == node_id for t in tags):
                    tags.append({"node_id": node_id, "path": path})
                self._write(data)
                return

    def remove_tag(self, server_id: str, node_id: str) -> None:
        data = self._read()
        for s in data.get("servers", []):
            if s.get("id") == server_id:
                s["tags"] = [t for t in s.get("tags", []) if t.get("node_id") != node_id]
                break
        self._write(data)


