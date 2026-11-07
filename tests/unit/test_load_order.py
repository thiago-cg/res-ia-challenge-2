from __future__ import annotations

from src.index.load_db import _parent_first
from tests.fixtures.chunk_seed import make_device


def test_parent_first_inserts_parent_before_child_despite_ordem() -> None:
    parent = make_device("lmp/art121/par2", artigo_id="lmp/art121", tipo="paragrafo", ordem=9)
    child = make_device(
        "lmp/art121/par2/inc1",
        parent_id="lmp/art121/par2",
        artigo_id="lmp/art121",
        tipo="inciso",
        ordem=1,
    )

    ordered = _parent_first([child, parent])

    assert [device.id for device in ordered] == [
        "lmp/art121/par2",
        "lmp/art121/par2/inc1",
    ]
