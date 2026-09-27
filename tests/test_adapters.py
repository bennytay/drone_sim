import struct
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from drone_sim.context import DeterministicFileReader


def reader(tmp_path: Path) -> tuple[Path, DeterministicFileReader]:
    source = tmp_path / "deployment"
    source.mkdir()
    return source, DeterministicFileReader(source, max_file_bytes=4096)


def test_csv_is_summarized_without_materializing_the_stream(tmp_path: Path) -> None:
    source, adapter = reader(tmp_path)
    rows = ["timestamp,altitude_m,battery_v"]
    rows.extend(f"{index},{index * 2},{16 - index / 100}" for index in range(100))
    (source / "flight.csv").write_text("\n".join(rows))

    parsed = adapter.parse("flight.csv")

    assert parsed.adapter == "csv_summary"
    assert parsed.artifact_kind == "telemetry"
    assert parsed.content["row_count"] == 100
    assert len(parsed.content["sample_rows"]) == 5
    assert parsed.content["numeric_ranges"]["altitude_m"] == {
        "min": 0.0,
        "max": 198.0,
    }
    assert parsed.truncated
    assert parsed.bytes_materialized < parsed.size_bytes


def test_kml_returns_route_bounds_and_bounded_samples(tmp_path: Path) -> None:
    source, adapter = reader(tmp_path)
    coordinates = " ".join(f"{151 + i / 1000},{-33 - i / 1000},{i}" for i in range(30))
    (source / "route.kml").write_text(
        f'<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><LineString>'
        f"<coordinates>{coordinates}</coordinates></LineString></Placemark></kml>"
    )

    parsed = adapter.parse("route.kml")

    assert parsed.artifact_kind == "route"
    assert parsed.content["placemark_count"] == 1
    assert parsed.content["coordinate_count"] == 30
    assert len(parsed.content["sample_coordinates"]) == 20
    assert parsed.truncated


def test_pdf_and_docx_extract_bounded_document_content(tmp_path: Path) -> None:
    source, adapter = reader(tmp_path)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with (source / "operations.pdf").open("wb") as handle:
        writer.write(handle)
    with zipfile.ZipFile(source / "risk.docx", "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:test"><w:body><w:p><w:r>'
            "<w:t>Drone risk assessment</w:t></w:r></w:p></w:body></w:document>",
        )

    pdf = adapter.parse("operations.pdf")
    docx = adapter.parse("risk.docx")

    assert pdf.content["page_count"] == 1
    assert docx.content["text"] == "Drone risk assessment"
    assert pdf.artifact_kind == docx.artifact_kind == "document"


def test_binary_drone_artifacts_return_metadata_not_raw_bytes(tmp_path: Path) -> None:
    source, adapter = reader(tmp_path)
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(
        ">II", 1920, 1080
    )
    (source / "site.png").write_bytes(png_header + b"x" * 10_000)
    (source / "flight.ulg").write_bytes(
        b"ULog\x01\x12\x35" + bytes([1]) + struct.pack("<Q", 123456) + b"x" * 10_000
    )

    image = adapter.parse("site.png")
    log = adapter.parse("flight.ulg")

    assert image.content["width_px"] == 1920
    assert image.content["height_px"] == 1080
    assert log.content["ulog_version"] == 1
    assert log.content["start_timestamp_us"] == 123456
    assert image.bytes_materialized < image.size_bytes
    assert log.bytes_materialized < log.size_bytes


def test_unknown_formats_are_rejected(tmp_path: Path) -> None:
    source, adapter = reader(tmp_path)
    (source / "unknown.xyz").write_bytes(b"data")

    with pytest.raises(ValueError, match="no deterministic adapter"):
        adapter.parse("unknown.xyz")
