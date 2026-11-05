from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn
        self._rows: list[tuple[Any, ...]] = []
        self.rowcount = 0

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        normalized = " ".join(sql.split())
        values = tuple(params or ())
        self.conn.executions.append((normalized, values))
        self._rows = []
        self.rowcount = 0

        if normalized.startswith("INSERT INTO norm_versions"):
            key = (str(values[0]), values[1])
            if key not in self.conn.norm_versions:
                self.conn.norm_versions[key] = self.conn.next_id()
            self._rows = [(self.conn.norm_versions[key],)]
        elif normalized.startswith("INSERT INTO devices"):
            self.conn.devices.add(str(values[0]))
        elif normalized.startswith("INSERT INTO device_versions"):
            key = (str(values[0]), int(values[2]))
            if key not in self.conn.device_versions:
                self.conn.device_versions[key] = self.conn.next_id()
                self._rows = [(self.conn.device_versions[key],)]
        elif normalized.startswith("INSERT INTO norms"):
            self.conn.norms.add(str(values[0]))
        elif normalized.startswith("INSERT INTO ingest_runs"):
            self.conn.ingest_runs.append(self.conn.next_id())
            self._rows = [(self.conn.ingest_runs[-1],)]
        elif normalized.startswith("UPDATE ingest_runs"):
            self.rowcount = 1
            self._rows = [(int(values[-1]),)]
        elif normalized.startswith("UPDATE device_versions"):
            self.conn.updates.append((normalized, values))
            self.rowcount = 1

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self.updates: list[tuple[str, tuple[Any, ...]]] = []
        self.norms: set[str] = set()
        self.devices: set[str] = set()
        self.norm_versions: dict[tuple[str, Any], int] = {}
        self.device_versions: dict[tuple[str, int], int] = {}
        self.ingest_runs: list[int] = []
        self._id = 0

    def next_id(self) -> int:
        self._id += 1
        return self._id

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)
