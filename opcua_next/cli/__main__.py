import typer
import json
import sys
from typing import Optional
from ..drivers.python_opcua_driver import PythonOpcUaDriver

app = typer.Typer()


@app.command()
def ls(endpoint: str, depth: int = 1):
    """List nodes from an OPC UA server."""
    driver = PythonOpcUaDriver(endpoint)
    try:
        with driver.connect_context():
            result = driver.browse_recursive(depth=depth)
            typer.echo(json.dumps(result, indent=2, default=str))
    except Exception as e:
        typer.echo(f"Error connecting to {endpoint}: {e}", err=True)
        sys.exit(1)


@app.command()
def read(endpoint: str, node_id: str):
    """Read a value from an OPC UA node."""
    driver = PythonOpcUaDriver(endpoint)
    try:
        with driver.connect_context():
            value = driver.read_node(node_id)
            typer.echo(f"{node_id}: {value}")
    except Exception as e:
        typer.echo(f"Error reading {node_id} from {endpoint}: {e}", err=True)
        sys.exit(1)


@app.command()
def write(endpoint: str, node_id: str, value: str):
    """Write a value to an OPC UA node."""
    driver = PythonOpcUaDriver(endpoint)
    try:
        with driver.connect_context():
            # Try to convert value to appropriate type
            try:
                # Try integer first
                typed_value = int(value)
            except ValueError:
                try:
                    # Try float
                    typed_value = float(value)
                except ValueError:
                    # Keep as string
                    typed_value = value
            driver.write_node(node_id, typed_value)
            typer.echo(f"Wrote {typed_value} to {node_id}")
    except Exception as e:
        typer.echo(f"Error writing {value} to {node_id} on {endpoint}: {e}", err=True)
        sys.exit(1)


@app.command()
def subscribe(
    endpoint: str, 
    node_ids: str, 
    interval: int = 1000,
    duration: Optional[int] = None,
    output: Optional[str] = None,
    format: str = "parquet"
):
    """Subscribe to OPC UA nodes and optionally save to file."""
    import time
    from ..sinks.parquet_sink import ParquetSink
    from ..sinks.csv_sink import CSVSink
    
    # Parse node IDs (comma-separated)
    node_list = [nid.strip() for nid in node_ids.split(',')]
    
    driver = PythonOpcUaDriver(endpoint)
    sink = None
    records = []
    
    if output:
        if format.lower() == "csv":
            sink = CSVSink(output)
        else:
            sink = ParquetSink(output)
    
    def data_change_handler(node_id: str, value, data):
        timestamp = time.time()
        record = {
            "timestamp": timestamp,
            "node_id": node_id,
            "value": value,
            "source_timestamp": getattr(data, 'source_timestamp', None),
            "server_timestamp": getattr(data, 'server_timestamp', None)
        }
        records.append(record)
        typer.echo(f"{timestamp:.3f} {node_id}: {value}")
        
        # Write to sink if provided
        if sink:
            sink.write_records([record])
    
    try:
        with driver.connect_context():
            typer.echo(f"Subscribing to {len(node_list)} nodes on {endpoint}")
            typer.echo(f"Interval: {interval}ms")
            if duration:
                typer.echo(f"Duration: {duration}s")
            if output:
                typer.echo(f"Output: {output}")
            typer.echo("Press Ctrl+C to stop...")
            
            subscription_info = driver.create_subscription(interval, node_list, data_change_handler)
            
            if duration:
                time.sleep(duration)
                typer.echo(f"\nSubscription completed. {len(records)} records collected.")
            else:
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    typer.echo(f"\nSubscription stopped. {len(records)} records collected.")
                    
    except Exception as e:
        typer.echo(f"Error subscribing to {endpoint}: {e}", err=True)
        sys.exit(1)


@app.command()
def web(host: str = "localhost", port: int = 8000):
    """Start the web UI server."""
    import uvicorn
    from ..web.app import app
    
    typer.echo(f"Starting OPC UA Next Web UI at http://{host}:{port}")
    typer.echo("Press Ctrl+C to stop the server")
    
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    app()