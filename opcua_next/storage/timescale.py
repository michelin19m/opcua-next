import os
import json
import threading
from datetime import datetime, timezone
from typing import Iterable, List, Dict, Optional, Tuple

import psycopg


DEFAULT_DSN = os.getenv("OPCUA_NEXT_DB_DSN", "postgresql://localhost/postgres")


class TimescaleStorage:
    """Thin TimescaleDB storage for tag time-series.

    Schema:
      measurements(time timestamptz NOT NULL, node_id text NOT NULL, value jsonb NOT NULL)
      INDEX on (node_id, time DESC)
    Hypertable on time.
    """

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or DEFAULT_DSN
        self._lock = threading.RLock()

    def _connect(self):
        return psycopg.connect(self.dsn, autocommit=True)

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS measurements (
                        time timestamptz NOT NULL,
                        node_id text NOT NULL,
                        value jsonb NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_measurements_node_time
                        ON measurements(node_id, time DESC);
                    """
                )
                # Try to create hypertable if Timescale is installed
                try:
                    cur.execute(
                        "SELECT create_hypertable('measurements', 'time', if_not_exists=>TRUE);"
                    )
                except Exception:
                    # Timescale extension may not be present; ignore
                    pass

    def insert_records(self, records: List[Dict]) -> int:
        if not records:
            return 0
        rows = []
        for r in records:
            ts = r.get("timestamp")
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            elif isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            elif not isinstance(ts, datetime):
                ts = datetime.now(tz=timezone.utc)
            rows.append((ts, r.get("node_id"), json.dumps(r.get("value"))))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO measurements(time, node_id, value) VALUES (%s, %s, %s)",
                    rows,
                )
        return len(rows)

    def query_range(
        self,
        node_id: str,
        start: datetime,
        end: datetime,
        bucket_seconds: Optional[int] = None,
    ) -> List[Dict]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                if bucket_seconds and bucket_seconds > 0:
                    cur.execute(
                        """
                        SELECT time_bucket(%s::interval, time) AS bucket,
                               last(value, time) AS value
                        FROM measurements
                        WHERE node_id = %s AND time >= %s AND time <= %s
                        GROUP BY bucket
                        ORDER BY bucket
                        """,
                        (f"{bucket_seconds} seconds", node_id, start, end),
                    )
                    rows = cur.fetchall()
                    return [
                        {"timestamp": r[0].isoformat(), "node_id": node_id, "value": r[1]}
                        for r in rows
                    ]
                else:
                    cur.execute(
                        """
                        SELECT time, value
                        FROM measurements
                        WHERE node_id = %s AND time >= %s AND time <= %s
                        ORDER BY time
                        """,
                        (node_id, start, end),
                    )
                    rows = cur.fetchall()
                    return [
                        {"timestamp": r[0].isoformat(), "node_id": node_id, "value": r[1]}
                        for r in rows
                    ]


