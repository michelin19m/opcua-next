"""FastAPI web application for OPC UA toolkit."""

import json
import asyncio
from typing import List, Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import pdb;

from ..drivers.python_opcua_driver import PythonOpcUaDriver


app = FastAPI(title="OPC UA Next", description="OPC UA Toolkit Web UI")
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

# Global driver instance
current_driver: Optional[PythonOpcUaDriver] = None


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


@app.get("/api/browse")
async def browse_nodes(depth: int = 1):
    """Browse OPC UA nodes."""
    global current_driver
    if not current_driver or not current_driver.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to OPC UA server")
    try:
        result = current_driver.browse_recursive(depth)
        return {"nodes": result}
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
