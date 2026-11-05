from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.contracts import IndexReport
from src.index import run
from src.index.chunk import build_chunks
from src.index.qdrant import ALIAS_NAME
from tests.fixtures.chunk_seed import lmp_art22_devices, lmp_art22_versions


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        if self.conn.fail:
            raise RuntimeError("db unavailable")
        self.conn.executions.append((sql, params))

    def fetchall(self) -> list[tuple]:
        return self.conn.rows


class FakeConnection:
    def __init__(self, rows: list[tuple] | None = None, *, fail: bool = False) -> None:
        self.rows = rows or []
        self.fail = fail
        self.executions: list[tuple[str, object]] = []
        self.committed = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class FakeEncoder:
    model_name = "fake-encoder"
    revision = "rev-1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def encode_documents(self, texts):
        if self.fail:
            raise RuntimeError("encoder exploded")
        self.calls.append(list(texts))
        return [[float(index)] * 4 for index, _ in enumerate(texts)]

    def encode_query(self, text):
        return [1.0, 0.0, 0.0, 0.0]


class FakeClient:
    def __init__(self, *, fail_exists: bool = False) -> None:
        self.fail_exists = fail_exists
        self.collections: set[str] = set()
        self.aliases: list[SimpleNamespace] = []
        self.upserts: list[dict] = []

    def collection_exists(self, name: str) -> bool:
        if self.fail_exists:
            raise RuntimeError("qdrant unavailable")
        return name in self.collections

    def create_collection(self, **kwargs) -> None:
        self.collections.add(kwargs["collection_name"])

    def get_aliases(self):
        return SimpleNamespace(aliases=self.aliases)

    def update_collection_aliases(self, change_aliases_operations):
        for operation in change_aliases_operations:
            if operation.create_alias is not None:
                create = operation.create_alias
                self.aliases = [
                    alias for alias in self.aliases if alias.alias_name != create.alias_name
                ]
                self.aliases.append(
                    SimpleNamespace(
                        alias_name=create.alias_name,
                        collection_name=create.collection_name,
                    )
                )

    def upsert(self, collection_name, points, wait=True):
        self.upserts.append({"collection_name": collection_name, "points": list(points)})


def chunks():
    return build_chunks(lmp_art22_devices(), lmp_art22_versions()).chunks


def test_index_fallback_embeds_and_updates_each_version() -> None:
    conn = FakeConnection()
    encoder = FakeEncoder()

    report = run.index_fallback(chunks(), conn=conn, encoder=encoder)

    assert report.path == "fallback"
    assert report.indexed == len(chunks())
    assert report.skipped == 0
    assert report.errors == []
    assert report.model == "fake-encoder"
    assert report.model_revision == "rev-1"
    assert len(conn.executions) == len(chunks())
    assert all("UPDATE device_versions" in sql for sql, _ in conn.executions)
    assert conn.executions[0][1][4] == chunks()[0].device_id


def test_index_fallback_records_update_errors_and_never_silently_skips() -> None:
    conn = FakeConnection(fail=True)

    report = run.index_fallback(chunks(), conn=conn, encoder=FakeEncoder())

    assert report.indexed == 0
    assert report.skipped == len(chunks())
    assert len(report.errors) == len(chunks())
    assert "db unavailable" in report.errors[0]


def test_index_fallback_skips_blank_literal_and_counts_it() -> None:
    items = [chunk.model_copy(update={"texto_indexacao": "  "}) for chunk in chunks()[:2]]
    conn = FakeConnection()

    report = run.index_fallback(items, conn=conn, encoder=FakeEncoder())

    assert report.indexed == 0
    assert report.skipped == 2
    assert conn.executions == []


def test_index_fallback_accounts_for_invalid_versions() -> None:
    report = run.index_fallback([object()], conn=FakeConnection(), encoder=FakeEncoder())

    assert report.indexed == 0
    assert report.skipped == 1
    assert len(report.errors) == 1
    assert "invalid version" in report.errors[0]


def test_index_fallback_reports_encoder_failure() -> None:
    report = run.index_fallback(
        chunks(),
        conn=FakeConnection(),
        encoder=FakeEncoder(fail=True),
    )

    assert report.indexed == 0
    assert report.skipped == len(chunks())
    assert "encoder exploded" in report.errors[0]


def test_index_target_upserts_into_qdrant_without_text() -> None:
    client = FakeClient()
    encoder = FakeEncoder()

    report = run.index_target(chunks(), client=client, encoder=encoder)

    assert report.path == "target"
    assert report.indexed == len(chunks())
    assert report.skipped == 0
    assert report.errors == []
    assert len(client.upserts) == 1
    assert client.upserts[0]["collection_name"] == ALIAS_NAME
    points = client.upserts[0]["points"]
    assert len(points) == len(chunks())
    assert all("late" in point.vector and "bm25" in point.vector for point in points)
    assert all("device_id" in point.payload for point in points)
    assert all("texto_literal" not in point.payload for point in points)


def test_index_target_records_encoder_errors_per_chunk() -> None:
    client = FakeClient()

    report = run.index_target(chunks(), client=client, encoder=FakeEncoder(fail=True))

    assert report.indexed == 0
    assert report.skipped == len(chunks())
    assert len(report.errors) == len(chunks())
    assert client.upserts == []


def test_index_target_reports_collection_setup_failure() -> None:
    report = run.index_target(
        chunks(),
        client=FakeClient(fail_exists=True),
        encoder=FakeEncoder(),
    )

    assert report.indexed == 0
    assert report.skipped == len(chunks())
    assert "ensure collection failed" in report.errors[0]


def test_upsert_batches_are_accounted() -> None:
    client = FakeClient()

    report = run.index_target(
        chunks(),
        client=client,
        encoder=FakeEncoder(),
        batch_size=2,
    )

    assert report.indexed == len(chunks())
    assert [len(call["points"]) for call in client.upserts] == [2, 2]


def test_build_parser_requires_path_and_reads_source() -> None:
    parser = run.build_parser()
    args = parser.parse_args(["--path", "fallback", "--source", "lmp"])

    assert args.path == "fallback"
    assert args.source == "lmp"

    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--path", "other"])


def test_main_returns_one_when_database_connection_fails(monkeypatch, capsys) -> None:
    def fail(url: str):
        raise RuntimeError("cannot connect")

    monkeypatch.setattr(run, "_connect", fail)

    code = run.main(["--path", "fallback"])

    assert code == 1
    assert "cannot connect" in capsys.readouterr().err


def test_main_returns_one_when_report_has_errors(monkeypatch) -> None:
    monkeypatch.setattr(run, "_connect", lambda url: FakeConnection())
    monkeypatch.setattr(run, "get_encoder", lambda settings: FakeEncoder())
    monkeypatch.setattr(
        run,
        "index_fallback",
        lambda versions, **kwargs: IndexReport(
            path="fallback",
            indexed=0,
            skipped=1,
            errors=["boom"],
            model="fake-encoder",
        ),
    )

    assert run.main(["--path", "fallback"]) == 1


def test_main_prints_compact_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(run, "_connect", lambda url: FakeConnection())
    monkeypatch.setattr(
        run,
        "index_fallback",
        lambda versions, **kwargs: IndexReport(
            path="fallback",
            indexed=3,
            skipped=1,
            errors=[],
            model="fake-encoder",
            model_revision="rev-1",
        ),
    )

    assert run.main(["--path", "fallback", "--source", "lmp"]) == 0
    assert "fallback: indexed=3 skipped=1 errors=0 model=fake-encoder@rev-1" in (
        capsys.readouterr().out
    )
