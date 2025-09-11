import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path


class ParquetSink:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_records(self, records: list[dict]):
        if not records:
            return
        df = pd.DataFrame(records)
        table = pa.Table.from_pandas(df)
        if self.path.exists():
            existing = pq.read_table(self.path)
            table = pa.concat_tables([existing, table])
        pq.write_table(table, self.path)