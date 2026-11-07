from __future__ import annotations

from datetime import date

from src.ingest.models import close_version_windows
from tests.fixtures.chunk_seed import make_version


def test_close_version_windows_closes_the_previous_version() -> None:
    old = make_version(
        "lmp/art22",
        "texto antigo",
        vigencia_inicio=date(2006, 9, 22),
        vigencia_fim=None,
    )
    new = make_version(
        "lmp/art22",
        "texto novo",
        vigencia_inicio=date(2024, 1, 1),
        vigencia_fim=None,
    )

    closed = close_version_windows([old, new])

    assert [version.vigencia_inicio for version in closed] == [
        date(2006, 9, 22),
        date(2024, 1, 1),
    ]
    assert closed[0].vigencia_fim == date(2023, 12, 31)
    assert closed[1].vigencia_fim is None


def test_close_version_windows_keeps_an_earlier_revocation_date() -> None:
    revoked = make_version(
        "lmp/art22",
        "texto revogado",
        vigencia_inicio=date(2006, 9, 22),
        vigencia_fim=date(2010, 1, 1),
    )
    new = make_version(
        "lmp/art22",
        "texto novo",
        vigencia_inicio=date(2024, 1, 1),
        vigencia_fim=None,
    )

    closed = close_version_windows([revoked, new])

    assert closed[0].vigencia_fim == date(2010, 1, 1)
