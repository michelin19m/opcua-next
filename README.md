# opcua-next-mvp

Minimal, open-source Python toolkit for OPC UA (MVP). Provides CLI and library to browse, read/write, subscribe, and record node data into Parquet files.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\\Scripts\\activate    # Windows

pip install -r requirements.txt

python -m opcua_next.cli ls opc.tcp://192.168.0.10:4840 --depth 2