"""Deterministic, bounded adapters for drone deployment source artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import struct
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from pypdf.errors import PyPdfError


class ParsedSource(BaseModel):
    """Bounded adapter output safe to persist and present to an agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    adapter: str
    artifact_kind: str
    content: Any
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    bytes_materialized: int = Field(ge=0)
    truncated: bool = False


class SourceAdapter(Protocol):
    name: str
    suffixes: frozenset[str]

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _result(
    path: Path,
    adapter: str,
    kind: str,
    content: Any,
    *,
    materialized: int,
    truncated: bool = False,
) -> ParsedSource:
    return ParsedSource(
        adapter=adapter,
        artifact_kind=kind,
        content=content,
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        bytes_materialized=materialized,
        truncated=truncated,
    )


class JsonAdapter:
    name = "json"
    suffixes = frozenset({".json", ".geojson"})

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource:
        size = path.stat().st_size
        if size > max_materialized_bytes:
            raise ValueError(
                f"structured file exceeds {max_materialized_bytes} byte parse limit"
            )
        raw = path.read_bytes()
        return _result(
            path,
            self.name,
            "route" if path.suffix.lower() == ".geojson" else "structured_data",
            json.loads(raw.decode("utf-8")),
            materialized=len(raw),
        )


class CsvSummaryAdapter:
    name = "csv_summary"
    suffixes = frozenset({".csv"})
    sample_limit = 5

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource:
        samples: list[dict[str, str]] = []
        numeric: dict[str, dict[str, float]] = {}
        row_count = 0
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(reader.fieldnames or ())
            for row in reader:
                row_count += 1
                if len(samples) < self.sample_limit:
                    samples.append(dict(row))
                for key, raw_value in row.items():
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    stats = numeric.setdefault(key, {"min": value, "max": value})
                    stats["min"] = min(stats["min"], value)
                    stats["max"] = max(stats["max"], value)
        content = {
            "format": "csv",
            "columns": columns,
            "row_count": row_count,
            "sample_rows": samples,
            "numeric_ranges": numeric,
        }
        materialized = len(json.dumps(content, default=str).encode("utf-8"))
        if materialized > max_materialized_bytes:
            raise ValueError("CSV summary unexpectedly exceeds materialization limit")
        return _result(
            path,
            self.name,
            "telemetry",
            content,
            materialized=materialized,
            truncated=row_count > len(samples),
        )


class TextAdapter:
    name = "text"
    suffixes = frozenset({".md", ".txt"})

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource:
        with path.open("rb") as handle:
            raw = handle.read(max_materialized_bytes + 1)
        truncated = len(raw) > max_materialized_bytes
        raw = raw[:max_materialized_bytes]
        return _result(
            path,
            self.name,
            "document",
            raw.decode("utf-8"),
            materialized=len(raw),
            truncated=truncated,
        )


class PdfAdapter:
    name = "pdf"
    suffixes = frozenset({".pdf"})
    page_limit = 5

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource:
        reader = PdfReader(path)
        pages: list[dict[str, Any]] = []
        used = 0
        for index, page in enumerate(reader.pages[: self.page_limit]):
            text = page.extract_text() or ""
            encoded = text.encode("utf-8")
            remaining = max(max_materialized_bytes - used, 0)
            clipped = encoded[:remaining].decode("utf-8", errors="ignore")
            pages.append({"page": index + 1, "text": clipped})
            used += len(clipped.encode("utf-8"))
            if used >= max_materialized_bytes:
                break
        content = {"format": "pdf", "page_count": len(reader.pages), "pages": pages}
        return _result(
            path,
            self.name,
            "document",
            content,
            materialized=used,
            truncated=len(reader.pages) > len(pages) or used >= max_materialized_bytes,
        )


class DocxAdapter:
    name = "docx"
    suffixes = frozenset({".docx"})

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("word/document.xml")
        root = ET.fromstring(raw)
        text = "\n".join(value for value in root.itertext() if value.strip())
        encoded = text.encode("utf-8")
        clipped = encoded[:max_materialized_bytes].decode("utf-8", errors="ignore")
        return _result(
            path,
            self.name,
            "document",
            {"format": "docx", "text": clipped},
            materialized=len(clipped.encode("utf-8")),
            truncated=len(encoded) > max_materialized_bytes,
        )


def _coordinates(text: str) -> Iterator[tuple[float, float, float | None]]:
    for item in text.replace("\n", " ").split():
        parts = item.split(",")
        if len(parts) < 2:
            continue
        try:
            yield float(parts[0]), float(parts[1]), (
                float(parts[2]) if len(parts) > 2 else None
            )
        except ValueError:
            continue


class KmlAdapter:
    name = "kml"
    suffixes = frozenset({".kml"})
    sample_limit = 20

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource:
        placemarks = 0
        coordinate_count = 0
        samples: list[tuple[float, float, float | None]] = []
        bounds: list[float] | None = None
        for _, element in ET.iterparse(path, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "Placemark":
                placemarks += 1
            elif tag == "coordinates" and element.text:
                for longitude, latitude, altitude in _coordinates(element.text):
                    coordinate_count += 1
                    if len(samples) < self.sample_limit:
                        samples.append((longitude, latitude, altitude))
                    if bounds is None:
                        bounds = [longitude, latitude, longitude, latitude]
                    else:
                        bounds = [
                            min(bounds[0], longitude),
                            min(bounds[1], latitude),
                            max(bounds[2], longitude),
                            max(bounds[3], latitude),
                        ]
            element.clear()
        content = {
            "format": "kml",
            "placemark_count": placemarks,
            "coordinate_count": coordinate_count,
            "bounds_lon_lat": bounds,
            "sample_coordinates": samples,
        }
        materialized = len(json.dumps(content).encode("utf-8"))
        return _result(
            path,
            self.name,
            "route",
            content,
            materialized=materialized,
            truncated=coordinate_count > len(samples),
        )


class BinaryMetadataAdapter:
    name = "binary_metadata"
    suffixes = frozenset(
        {
            ".ulg",
            ".tlog",
            ".bin",
            ".mcap",
            ".bag",
            ".obj",
            ".ply",
            ".pcd",
            ".las",
            ".laz",
            ".glb",
            ".gltf",
            ".png",
            ".jpg",
            ".jpeg",
            ".mp4",
            ".mov",
        }
    )

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource:
        suffix = path.suffix.lower()
        with path.open("rb") as handle:
            header = handle.read(min(max_materialized_bytes, 64 * 1024))
        kind = _binary_kind(suffix)
        content: dict[str, Any] = {
            "format": suffix.removeprefix("."),
            "size_bytes": path.stat().st_size,
        }
        if suffix == ".ulg" and header.startswith(b"ULog") and len(header) >= 16:
            content["ulog_version"] = header[7]
            content["start_timestamp_us"] = struct.unpack("<Q", header[8:16])[0]
        elif suffix == ".mcap":
            content["magic_valid"] = header.startswith(b"\x89MCAP0\r\n")
        elif suffix == ".png" and header.startswith(b"\x89PNG") and len(header) >= 24:
            content["width_px"], content["height_px"] = struct.unpack(">II", header[16:24])
        elif suffix in {".obj", ".ply", ".pcd"}:
            decoded = header.decode("utf-8", errors="ignore")
            content["header"] = decoded[:4096]
        materialized = len(json.dumps(content).encode("utf-8"))
        return _result(
            path,
            self.name,
            kind,
            content,
            materialized=materialized,
            truncated=True,
        )


def _binary_kind(suffix: str) -> str:
    if suffix in {".ulg", ".tlog", ".bin", ".mcap", ".bag"}:
        return "telemetry"
    if suffix in {".obj", ".ply", ".pcd", ".las", ".laz", ".glb", ".gltf"}:
        return "site_model"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "image"
    return "video"


class AdapterRegistry:
    """Stable suffix-to-adapter dispatch with duplicate registration checks."""

    def __init__(self, adapters: tuple[SourceAdapter, ...]) -> None:
        self.adapters = adapters
        self._by_suffix: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            for suffix in adapter.suffixes:
                if suffix in self._by_suffix:
                    raise ValueError(f"duplicate source adapter for {suffix}")
                self._by_suffix[suffix] = adapter

    def parse(self, path: Path, *, max_materialized_bytes: int) -> ParsedSource:
        suffix = path.suffix.lower()
        try:
            adapter = self._by_suffix[suffix]
        except KeyError as error:
            raise ValueError(
                f"no deterministic adapter for {suffix or 'extensionless file'}"
            ) from error
        try:
            return adapter.parse(path, max_materialized_bytes=max_materialized_bytes)
        except (
            OSError,
            UnicodeError,
            ValueError,
            ET.ParseError,
            zipfile.BadZipFile,
            csv.Error,
            PyPdfError,
            KeyError,
        ) as error:
            raise ValueError(
                f"{adapter.name} could not parse {path.name}: {error}"
            ) from error


DEFAULT_ADAPTERS = AdapterRegistry(
    (
        JsonAdapter(),
        CsvSummaryAdapter(),
        TextAdapter(),
        PdfAdapter(),
        DocxAdapter(),
        KmlAdapter(),
        BinaryMetadataAdapter(),
    )
)
