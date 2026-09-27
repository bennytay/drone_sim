# Source adapters v0.1

The source-adapter registry is the deterministic boundary between operator
files and the context agent. Adapters implement `SourceAdapter.parse` and
return the same immutable `ParsedSource` contract:

- adapter and artifact-kind identifiers;
- structured, JSON-serializable content;
- SHA-256 of the complete source bytes;
- complete source byte size;
- bytes materialized into the agent-facing result; and
- whether the result is truncated or summarized.

Suffix registration is unique and explicit. Unknown formats fail closed, and
adapter errors become parse-error inspection events rather than agent guesses.

## Initial drone-focused coverage

- JSON and GeoJSON: complete deterministic parsing under the configured size
  limit, preserving canonical manifests and routes;
- CSV: streaming row count, bounded samples, columns, and numeric min/max
  summaries without retaining the full time series;
- Markdown and text: bounded UTF-8 extraction;
- PDF and DOCX: bounded document text plus page/format metadata;
- KML: streaming placemark count, coordinate count, bounds, and samples;
- PX4 ULog, ArduPilot/DJI-style binary logs, TLog, MCAP, and ROS bags: format,
  size, hash, magic/header metadata where safely available;
- OBJ, PLY, PCD, LAS/LAZ, GLB, and glTF: bounded site-model or point-cloud
  metadata; and
- PNG/JPEG and MP4/MOV: bounded image/video metadata.

Opaque vendor logs are not interpreted as facts. Until a validated decoder is
registered, they remain typed external artifacts with provenance and bounded
metadata. Selective telemetry querying is a future adapter extension, not a
reason to expose raw streams to the LLM.
