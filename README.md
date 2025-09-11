# opcua-next-mvp

Minimal, open-source Python toolkit for OPC UA (MVP). Provides CLI and library to browse, read/write, subscribe, and record node data into Parquet/CSV files with auto-reconnect and web UI.

## Features

- **CLI Interface**: Browse, read, write, and subscribe to OPC UA nodes
- **Data Sinks**: Save subscription data to Parquet or CSV files
- **Auto-reconnect**: Automatic reconnection on connection loss
- **Web UI**: Modern web interface for OPC UA operations
- **Secure by default**: Support for certificates and security policies

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\\Scripts\\activate    # Windows

pip install -r requirements.txt

# List nodes from an OPC UA server
python -m opcua_next.cli ls opc.tcp://192.168.0.10:4840 --depth 2

# Read a value from a node
python -m opcua_next.cli read opc.tcp://192.168.0.10:4840 "ns=2;i=1"

# Write a value to a node
python -m opcua_next.cli write opc.tcp://192.168.0.10:4840 "ns=2;i=1" "42"

# Subscribe to nodes and save to file
python -m opcua_next.cli subscribe opc.tcp://192.168.0.10:4840 "ns=2;i=1,ns=2;i=2" --output data.parquet

# Start web UI
python -m opcua_next.cli web