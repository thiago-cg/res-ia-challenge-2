"""Structural chunker for legal devices.

The unit of retrieval is the device (artigo/caput/inciso/alinea/item), never a
fixed token window.  ``build_chunks`` joins identity (``Device``) with text
(``DeviceVersion``) by ``device_id`` and produces one persistable chunk per
``(device_id, norm_version_id)``.  Article-level contexts are in-memory
``ArticleContext`` objects: they are not rows in ``devices`` and must never be
persisted as a device.

Literal text is never truncated.  An oversized parent may only be omitted when
every word of its literal is covered, in order, by descendant literals; the
check uses whitespace-normalized words.  Otherwise ``ChunkTooLong`` is raised.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from src.contracts import Device, DeviceType, DeviceVersion, VigenciaStatus

DEFAULT_TOKEN_SCALE = 1.3
Tokenizer = Callable[[str], int]


class ChunkTooLong(Exception):
    """Raised when a literal cannot be split without losing any of its text."""

    def __init__(self, device_id: str, estimated_tokens: int, max_tokens: int) -> None:
        self.device_id = device_id
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens
        super().__init__(
            f"device {device_id!r} needs ~{estimated_tokens} tokens (limit {max_tokens}) and "
            "its literal is not fully covered by descendant devices; split it structurally "
            "or raise max_tokens. Literal text was not truncated."
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


class ArticleContext(BaseModel):
    """In-memory article header context for the LLM.

    It deliberately has no ``device_id``/``qdrant_point_id``: an article may have
    no row in ``devices``, so this object must never be persisted as a device.
    """

    artigo_id: str
    norm_id: str
    norm_version_id: int
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
    content_hash: str
    leaf_device_ids: list[str] = Field(default_factory=list)


@dataclass
class ChunkSet:
    """Persistable chunks plus non-persistable article contexts."""

    chunks: list[Chunk]
    article_contexts: list[ArticleContext]

    def __iter__(self) -> Iterator[Chunk]:
        return iter(self.chunks)

    def __len__(self) -> int:
        return len(self.chunks)

    def __getitem__(self, index: int) -> Chunk:
        return self.chunks[index]


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
) -> ChunkSet:
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

    for device in devices_by_id.values():
        for version in versions_by_device[device.id]:
            if not version.texto_literal.strip():
                continue
            index_text = version.contexto + "\n" + version.texto_literal
            estimated = estimate_tokens(index_text, tokenizer)
            if estimated <= max_tokens:
                chunks[(device.id, version.norm_version_id)] = _make_chunk(device, version)
                continue

            descendants = _descendant_literals(
                device,
                version.norm_version_id,
                versions_by_device,
                children_by_parent,
            )
            if not _covers(version.texto_literal, descendants):
                raise ChunkTooLong(device.id, estimated, max_tokens)

    article_contexts = _build_article_contexts(devices_by_id, versions_by_device, chunks)
    return ChunkSet(chunks=list(chunks.values()), article_contexts=article_contexts)


def _descendant_literals(
    device: Device,
    norm_version_id: int,
    versions_by_device: dict[str, list[DeviceVersion]],
    children_by_parent: dict[str, list[Device]],
) -> list[str]:
    literals: list[str] = []
    for child in sorted(children_by_parent.get(device.id, []), key=lambda item: item.ordem):
        if child.artigo_id != device.artigo_id:
            continue
        version = _version_for(versions_by_device.get(child.id, []), norm_version_id)
        if version is not None:
            literals.append(version.texto_literal)
        literals.extend(
            _descendant_literals(child, norm_version_id, versions_by_device, children_by_parent)
        )
    return literals


def _covers(parent_literal: str, descendant_literals: list[str]) -> bool:
    """True when every whitespace-normalized parent word appears in order."""
    parent_words = parent_literal.split()
    if not parent_words:
        return True
    descendant_words = " ".join(descendant_literals).split()
    position = 0
    for word in descendant_words:
        if position < len(parent_words) and word == parent_words[position]:
            position += 1
            if position == len(parent_words):
                return True
    return False


def _build_article_contexts(
    devices_by_id: dict[str, Device],
    versions_by_device: dict[str, list[DeviceVersion]],
    chunks: dict[tuple[str, int], Chunk],
) -> list[ArticleContext]:
    groups: dict[tuple[str, int], tuple[Device, DeviceVersion]] = {}
    for device in devices_by_id.values():
        for device_version in versions_by_device.get(device.id, []):
            groups.setdefault(
                (device.artigo_id, device_version.norm_version_id),
                (device, device_version),
            )

    contexts: list[ArticleContext] = []
    for (artigo_id, norm_version_id), (leaf_device, leaf_version) in groups.items():
        article = devices_by_id.get(artigo_id)
        reference: Device
        version: DeviceVersion

        if article is not None and (
            article_version := _version_for(versions_by_device.get(article.id, []), norm_version_id)
        ):
            reference, version = article, article_version
        elif (caput := _find_caput(devices_by_id, artigo_id)) is not None and (
            caput_version := _version_for(versions_by_device.get(caput.id, []), norm_version_id)
        ):
            reference, version = caput, caput_version
        else:
            reference, version = leaf_device, leaf_version

        leaf_ids = [
            chunk.device_id
            for chunk in chunks.values()
            if chunk.artigo_id == artigo_id
            and chunk.norm_version_id == norm_version_id
            and chunk.device_id != artigo_id
        ]
        contexts.append(_make_article_context(artigo_id, reference, version, leaf_ids=leaf_ids))
    return contexts


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
    artigo_id: str,
    reference: Device,
    version: DeviceVersion,
    *,
    leaf_ids: list[str],
) -> ArticleContext:
    texto_literal = version.texto_literal
    return ArticleContext(
        artigo_id=artigo_id,
        norm_id=reference.norm_id,
        norm_version_id=version.norm_version_id,
        rotulo=reference.rotulo,
        caminho=reference.caminho,
        texto_literal=texto_literal,
        contexto=version.contexto,
        citacao=version.citacao,
        vigencia_status=version.vigencia_status,
        vigencia_inicio=version.vigencia_inicio,
        vigencia_fim=version.vigencia_fim,
        search_text=version.search_text,
        texto_indexacao=version.contexto + "\n" + texto_literal,
        content_hash=version.content_hash,
        leaf_device_ids=leaf_ids,
    )
