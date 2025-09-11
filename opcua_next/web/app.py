"""FastAPI web application for OPC UA toolkit."""

import json
import asyncio
from typing import List, Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..drivers.python_opcua_driver import PythonOpcUaDriver


app = FastAPI(title="OPC UA Next", description="OPC UA Toolkit Web UI")

# Templates
templates = Jinja2Templates(directory="opcua_next/web/templates")

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                self.active_connections.remove(connection)


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


@app.post("/api/browse")
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
        # Try to convert value to appropriate type
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time data."""
    await manager.connect(websocket)
    
    # Subscribe to data changes if connected
    if current_driver and current_driver.is_connected():
        def data_change_handler(node_id: str, value, data):
            import time
            message = {
                "type": "data_change",
                "timestamp": time.time(),
                "node_id": node_id,
                "value": value
            }
            asyncio.create_task(manager.broadcast(json.dumps(message)))
        
        # Subscribe to all readable nodes (simplified for demo)
        try:
            subscription_info = current_driver.create_subscription(
                1000, ["ns=2;i=1"], data_change_handler  # Example node
            )
        except Exception as e:
            await manager.send_personal_message(
                json.dumps({"type": "error", "message": str(e)}), 
                websocket
            )
    
    try:
        while True:
            data = await websocket.receive_text()
            # Echo back for now
            await manager.send_personal_message(data, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
