"""Structural chunker for legal devices.

The unit of retrieval is the device (artigo/caput/inciso/alinea/item), never a
fixed token window.  ``build_chunks`` joins identity (``Device``) with text
(``DeviceVersion``) by ``device_id`` and produces one chunk per
``(device_id, norm_version_id)``.  Article-level context chunks are produced
once per article and linked to the leaves by ``artigo_id``.

Literal text is never truncated.  Oversized structural parents are split into
their children (same ``artigo_id``); an oversized leaf raises ``ChunkTooLong``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from src.contracts import Device, DeviceType, DeviceVersion, VigenciaStatus

DEFAULT_TOKEN_SCALE = 1.3
Tokenizer = Callable[[str], int]


class ChunkTooLong(Exception):
    """Raised when a literal leaf cannot fit in ``max_tokens``."""

    def __init__(self, device_id: str, estimated_tokens: int, max_tokens: int) -> None:
        self.device_id = device_id
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens
        super().__init__(
            f"device {device_id!r} needs ~{estimated_tokens} tokens (limit {max_tokens}); "
            "split it by structural subnodes or raise max_tokens. Literal text was not truncated."
        )


class MissingVersionError(Exception):
    """Raised when a device has no matching ``DeviceVersion``."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(
            f"device {device_id!r} has no DeviceVersion; join identity and text by device_id "
            "before building chunks."
        )


class Chunk(BaseModel):
    device_id: str
    parent_id: str | None
    norm_version_id: int
    norm_id: str
    artigo_id: str
    tipo: DeviceType
    rotulo: str
    caminho: str
    texto_literal: str
    contexto: str
    citacao: str
    vigencia_status: VigenciaStatus
    vigencia_inicio: date
    vigencia_fim: date | None
    search_text: str
    texto_indexacao: str
    qdrant_point_id: UUID
    content_hash: str


def estimate_tokens(text: str, tokenizer: Tokenizer | None = None) -> int:
    """Estimate tokens without importing a model tokenizer.

    The default is ``ceil(whitespace_tokens * 1.3)``: legal Portuguese often
    tokenizes into more pieces than whitespace words, so the 1.3 factor keeps
    the limit conservative.  Tests pin this contract.
    """

    if tokenizer is not None:
        return tokenizer(text)
    return math.ceil(len(text.split()) * DEFAULT_TOKEN_SCALE)


def build_chunks(
    devices: list[Device],
    versions: list[DeviceVersion],
    *,
    max_tokens: int = 8192,
    tokenizer: Tokenizer | None = None,
) -> list[Chunk]:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    devices_by_id: dict[str, Device] = {device.id: device for device in devices}
    versions_by_device: dict[str, list[DeviceVersion]] = defaultdict(list)
    for version in versions:
        versions_by_device[version.device_id].append(version)

    for device in devices_by_id.values():
        if device.id not in versions_by_device:
            raise MissingVersionError(device.id)

    children_by_parent: dict[str, list[Device]] = defaultdict(list)
    for device in devices_by_id.values():
        if device.parent_id:
            children_by_parent[device.parent_id].append(device)

    chunks: dict[tuple[str, int], Chunk] = {}
    skipped: dict[tuple[str, int], tuple[Device, DeviceVersion]] = {}

    for device in devices_by_id.values():
        for version in versions_by_device[device.id]:
            index_text = version.contexto + "\n" + version.texto_literal
            if estimate_tokens(index_text, tokenizer) <= max_tokens:
                chunks[(device.id, version.norm_version_id)] = _make_chunk(device, version)
                continue

            children = [
                child
                for child in children_by_parent.get(device.id, [])
                if child.artigo_id == device.artigo_id
            ]
            if not children:
                raise ChunkTooLong(
                    device.id,
                    estimate_tokens(index_text, tokenizer),
                    max_tokens,
                )
            skipped[(device.id, version.norm_version_id)] = (device, version)

    _ensure_article_contexts(devices_by_id, versions_by_device, chunks, skipped)
    return list(chunks.values())


def _ensure_article_contexts(
    devices_by_id: dict[str, Device],
    versions_by_device: dict[str, list[DeviceVersion]],
    chunks: dict[tuple[str, int], Chunk],
    skipped: dict[tuple[str, int], tuple[Device, DeviceVersion]],
) -> None:
    groups: dict[tuple[str, int], tuple[Device, DeviceVersion]] = {}
    for device in devices_by_id.values():
        for version in versions_by_device.get(device.id, []):
            groups.setdefault((device.artigo_id, version.norm_version_id), (device, version))

    for (artigo_id, norm_version_id), (leaf_device, leaf_version) in groups.items():
        key = (artigo_id, norm_version_id)
        if key in chunks:
            continue

        article = devices_by_id.get(artigo_id)
        skipped_entry = skipped.get(key)
        if skipped_entry is not None:
            reference, version, include_literal = (
                article or skipped_entry[0],
                skipped_entry[1],
                False,
            )
        elif article is not None:
            reference = article
            version = (
                _version_for(versions_by_device.get(article.id, []), norm_version_id)
                or leaf_version
            )
            include_literal = True
        else:
            caput = _find_caput(devices_by_id, artigo_id)
            caput_version = (
                _version_for(versions_by_device.get(caput.id, []), norm_version_id)
                if caput is not None
                else None
            )
            if caput is not None and caput_version is not None:
                reference, version, include_literal = caput, caput_version, True
            else:
                reference, version, include_literal = leaf_device, leaf_version, False

        chunks[key] = _make_article_context(
            article,
            reference,
            artigo_id,
            version,
            include_literal=include_literal,
        )


def _find_caput(devices_by_id: dict[str, Device], artigo_id: str) -> Device | None:
    for device in devices_by_id.values():
        if device.artigo_id == artigo_id and device.tipo == "caput":
            return device
    return None


def _version_for(versions: list[DeviceVersion], norm_version_id: int) -> DeviceVersion | None:
    for version in versions:
        if version.norm_version_id == norm_version_id:
            return version
    return None


def _make_chunk(device: Device, version: DeviceVersion) -> Chunk:
    return Chunk(
        device_id=device.id,
        parent_id=device.parent_id,
        norm_version_id=version.norm_version_id,
        norm_id=device.norm_id,
        artigo_id=device.artigo_id,
        tipo=device.tipo,
        rotulo=device.rotulo,
        caminho=device.caminho,
        texto_literal=version.texto_literal,
        contexto=version.contexto,
        citacao=version.citacao,
        vigencia_status=version.vigencia_status,
        vigencia_inicio=version.vigencia_inicio,
        vigencia_fim=version.vigencia_fim,
        search_text=version.search_text,
        texto_indexacao=version.contexto + "\n" + version.texto_literal,
        qdrant_point_id=version.qdrant_point_id,
        content_hash=version.content_hash,
    )


def _make_article_context(
    article: Device | None,
    reference: Device,
    artigo_id: str,
    version: DeviceVersion,
    *,
    include_literal: bool,
) -> Chunk:
    texto_literal = version.texto_literal if include_literal else ""
    return Chunk(
        device_id=artigo_id,
        parent_id=article.parent_id if article is not None else None,
        norm_version_id=version.norm_version_id,
        norm_id=reference.norm_id,
        artigo_id=artigo_id,
        tipo="artigo",
        rotulo=article.rotulo if article is not None else _article_label(artigo_id),
        caminho=article.caminho if article is not None else reference.caminho,
        texto_literal=texto_literal,
        contexto=version.contexto,
        citacao=version.citacao,
        vigencia_status=version.vigencia_status,
        vigencia_inicio=version.vigencia_inicio,
        vigencia_fim=version.vigencia_fim,
        search_text=version.search_text,
        texto_indexacao=version.contexto + "\n" + texto_literal,
        qdrant_point_id=uuid5(NAMESPACE_URL, f"{artigo_id}@{version.norm_version_id}#context"),
        content_hash=version.content_hash,
    )


def _article_label(artigo_id: str) -> str:
    tail = artigo_id.rsplit("/", 1)[-1]
    if tail.startswith("art"):
        return "Art. " + tail[3:]
    return tail
