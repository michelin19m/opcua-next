"""FastAPI web application for OPC UA toolkit."""

import json
import asyncio
from typing import List, Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import Response
from pydantic import BaseModel
import pdb;

from ..drivers.python_opcua_driver import PythonOpcUaDriver
from ..storage.timescale import TimescaleStorage
from ..core.historian import HistorianManager
from ..core.state import StateStore



app = FastAPI(title="OPC UA Next", description="OPC UA Toolkit Web UI")
app.mount("/static", StaticFiles(directory="opcua_next/web/static"), name="static")
main_loop = asyncio.get_event_loop()
# Templates
templates = Jinja2Templates(directory="opcua_next/web/templates")



import logging
import threading

logger = logging.getLogger("opcua_next")
logger.setLevel(logging.DEBUG)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.debug("WebSocket connected. total=%d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass
        logger.debug("WebSocket disconnected. total=%d", len(self.active_connections))

    async def _safe_send(self, websocket: WebSocket, message: str):
        try:
            await websocket.send_text(message)
            return None
        except Exception as e:
            logger.exception("Error sending to websocket")
            return e

    async def broadcast(self, message: str):
        # Work on a snapshot so we can remove failing connections safely
        conns = list(self.active_connections)
        if not conns:
            logger.debug("Broadcast called but no active connections")
            return
        # Try sending concurrently
        tasks = [self._safe_send(c, message) for c in conns]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Remove failed connections
        for conn, res in zip(conns, results):
            if isinstance(res, Exception):
                try:
                    self.active_connections.remove(conn)
                except ValueError:
                    pass
        logger.debug("Broadcasted message to %d sockets", len(conns))

# --- websocket endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, nodeids: Optional[str] = Query(None)):
    await manager.connect(websocket)

    # parse nodeids
    nodeid_list = ["ns=2;i=1"]
    if nodeids:
        try:
            nodeid_list = json.loads(nodeids)
        except Exception:
            logger.warning("Failed to parse nodeids query param, using default")

    subscription_info = None

    # If driver present, create subscription and capture the *running* loop
    if current_driver and current_driver.is_connected():
        loop = asyncio.get_running_loop()  # the correct running loop at this moment

        def data_change_handler(node_id: str, value, data):
            # build simple serializable message
            import time
            message = {
                "type": "data_change",
                "timestamp": time.time(),
                "node_id": node_id,
                # convert value to JSONable representation
                "value": str(value)
            }
            payload = json.dumps(message)  # already str-ified value

            # schedule the broadcast safely into the running loop
            # use call_soon_threadsafe so it works from any thread
            loop.call_soon_threadsafe(lambda: asyncio.create_task(manager.broadcast(payload)))
            logger.debug("Scheduled broadcast for node %s (thread=%s)", node_id, threading.current_thread().name)

        try:
            subscription_info = current_driver.create_subscription(1000, nodeid_list, data_change_handler)
            logger.debug("Subscription created: %r", subscription_info)
        except Exception as e:
            logger.exception("Failed to create subscription")
            await manager.send_personal_message(json.dumps({"type": "error", "message": str(e)}), websocket)

    try:
        while True:
            data = await websocket.receive_text()
            # echo or some handling
            await manager.send_personal_message(data, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        # if your driver exposes unsubscribe/cancel, do it here:
        try:
            if subscription_info and hasattr(current_driver, "delete_subscription"):
                current_driver.delete_subscription(subscription_info)
                logger.debug("Subscription deleted on disconnect")
        except Exception:
            logger.exception("Failed to delete subscription")


manager = ConnectionManager()

# Global driver instance and historian
current_driver: Optional[PythonOpcUaDriver] = None
storage = TimescaleStorage()
historian = HistorianManager(storage)
state = StateStore()


class ConnectRequest(BaseModel):
    endpoint: str
    security: Optional[Dict] = None


class ReadRequest(BaseModel):
    node_id: str


class WriteRequest(BaseModel):
    node_id: str
    value: str


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """Serve the main web UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/connect")
async def connect_endpoint(request: ConnectRequest):
    """Connect to an OPC UA server."""
    global current_driver
    
    try:
        current_driver = PythonOpcUaDriver(request.endpoint, request.security)
        current_driver.connect()
        # upsert server in state
        saved = state.upsert_server(request.endpoint)
        # auto-start historian for saved tags if any
        tags = saved.get("tags", [])
        if tags:
            node_ids = [t["node_id"] for t in tags]
            try:
                historian.start(request.endpoint, node_ids, 1000)
            except Exception:
                pass
        return {"status": "connected", "endpoint": request.endpoint}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/disconnect")
async def disconnect_endpoint():
    """Disconnect from the current OPC UA server."""
    global current_driver
    
    if current_driver:
        current_driver.disconnect()
        current_driver = None
        return {"status": "disconnected"}
    return {"status": "not_connected"}


@app.get("/api/status")
async def get_status():
    """Get connection status."""
    global current_driver
    
    if current_driver and current_driver.is_connected():
        return {"status": "connected", "endpoint": current_driver.endpoint}
    return {"status": "disconnected"}

# ---- Saved servers / tags API ----

class ServerRequest(BaseModel):
    endpoint: str
    name: Optional[str] = None


@app.get("/api/servers")
async def list_servers():
    return {"servers": state.list_servers()}


@app.post("/api/servers")
async def add_server(req: ServerRequest):
    saved = state.upsert_server(req.endpoint, req.name)
    return saved


@app.delete("/api/servers/{server_id}")
async def delete_server(server_id: str):
    # Delete historian data for all tags of this server
    tags = state.list_tags(server_id)
    try:
        storage.delete_by_node_ids([t["node_id"] for t in tags])
    except Exception:
        pass
    # Stop historian if it was running for this server
    try:
        if hasattr(historian, "stop"):
            historian.stop()
    except Exception:
        pass
    state.delete_server(server_id)
    return {"status": "deleted"}


class TagRequest(BaseModel):
    server_id: str
    node_id: str
    path: str


@app.get("/api/servers/{server_id}/tags")
async def list_tags(server_id: str):
    return {"tags": state.list_tags(server_id)}


@app.post("/api/tags")
async def add_tag(req: TagRequest):
    state.add_tag(req.server_id, req.node_id, req.path)
    # Auto (re)start historian for this server's saved tags
    try:
        tags = state.list_tags(req.server_id)
        node_ids = [t["node_id"] for t in tags]
        historian.stop()
        if node_ids:
            historian.start(req.server_id, node_ids, 1000)
    except Exception:
        pass
    return {"status": "ok"}


@app.delete("/api/servers/{server_id}/tags")
async def remove_tag(server_id: str, node_id: str):
    state.remove_tag(server_id, node_id)
    try:
        storage.delete_by_node_ids([node_id])
    except Exception:
        pass
    # Auto (re)start historian reflecting removal
    try:
        tags = state.list_tags(server_id)
        node_ids = [t["node_id"] for t in tags]
        historian.stop()
        if node_ids:
            historian.start(server_id, node_ids, 1000)
    except Exception:
        pass
    return {"status": "deleted"}


@app.get("/api/browse")
async def browse_nodes(depth: int = 3):
    """Browse OPC UA nodes."""
    global current_driver
    if not current_driver or not current_driver.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to OPC UA server")
    try:
        result = current_driver.browse_recursive(depth)
        return json.loads(json.dumps({"nodes": result}, default=str))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/read")
async def read_node(request: ReadRequest):
    """Read a value from an OPC UA node."""
    global current_driver
    if not current_driver or not current_driver.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to OPC UA server")
    
    try:
        value = current_driver.read_node(request.node_id)
        return {"node_id": request.node_id, "value": value}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/write")
async def write_node(request: WriteRequest):
    """Write a value to an OPC UA node."""
    global current_driver
    
    if not current_driver or not current_driver.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to OPC UA server")
    
    try:
        try:
            typed_value = int(request.value)
        except ValueError:
            try:
                typed_value = float(request.value)
            except ValueError:
                typed_value = request.value
        
        current_driver.write_node(request.node_id, typed_value)
        return {"node_id": request.node_id, "value": typed_value}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# Historian endpoints
class HistorianStartRequest(BaseModel):
    endpoint: str
    node_ids: List[str]
    interval_ms: int = 1000


@app.post("/api/historian/start")
async def historian_start(req: HistorianStartRequest):
    try:
        historian.start(req.endpoint, req.node_ids, req.interval_ms)
        return {"status": "started", "count": len(req.node_ids)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/historian/stop")
async def historian_stop():
    try:
        historian.stop()
        return {"status": "stopped"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/trends")
async def trends(node_id: str, start: str, end: str, bucket_seconds: Optional[int] = None):
    from datetime import datetime
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        data = storage.query_range(node_id, s, e, bucket_seconds)
        return {"node_id": node_id, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/trends/last")
async def trends_last(node_id: str, n: int = 10):
    try:
        data = storage.query_last_n(node_id, n)
        return {"node_id": node_id, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/trends/plot.png")
async def trends_plot(node_id: str, n: int = 10):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import io

        series = storage.query_last_n(node_id, n)
        if not series:
            # return empty image
            fig, ax = plt.subplots(figsize=(6,2))
            ax.set_title('No data')
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight')
            plt.close(fig)
            return Response(content=buf.getvalue(), media_type='image/png')

        xs = [s['timestamp'] for s in series]
        ys = []
        for s in series:
            v = s['value']
            try:
                ys.append(float(v))
            except Exception:
                ys.append(float('nan'))

        fig, ax = plt.subplots(figsize=(8,3))
        ax.plot(xs, ys, marker='o')
        ax.set_title(f"{node_id} (last {n})")
        ax.set_xlabel('time')
        ax.set_ylabel('value')
        ax.grid(True, alpha=0.3)
        plt.xticks(rotation=45, ha='right')

        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        return Response(content=buf.getvalue(), media_type='image/png')
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
