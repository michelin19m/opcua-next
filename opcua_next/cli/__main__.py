import typer
import json
from ..drivers.python_opcua_driver import PythonOpcuaDriver

app = typer.Typer()


@app.command()
def ls(endpoint: str, depth: int = 1):
    """List nodes from an OPC UA server."""
    driver = PythonOpcuaDriver(endpoint)
    with driver.connect():
        result = driver.browse(depth=depth)
        typer.echo(json.dumps(result, indent=2))


@app.command()
def read(endpoint: str, node_id: str):
    driver = PythonOpcuaDriver(endpoint)
    with driver.connect():
        value = driver.read(node_id)
        typer.echo(f"{node_id}: {value}")


@app.command()
def write(endpoint: str, node_id: str, value: str):
    driver = PythonOpcuaDriver(endpoint)
    with driver.connect():
        driver.write(node_id, value)
        typer.echo(f"Wrote {value} to {node_id}")


if __name__ == "__main__":
    app()