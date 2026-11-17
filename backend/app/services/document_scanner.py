"""Office-package content disarm and ClamAV INSTREAM scanning."""

from __future__ import annotations

import io
import socket
import struct
import zipfile
from dataclasses import dataclass

from defusedxml import ElementTree

from app.config import Settings

BLOCKED_PARTS = ("/embeddings/", "/activex/", "vbaproject.bin")
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass
class ScanResult:
    clean: bool
    engine: str
    sanitized: bytes
    details: dict[str, object]


def disarm_office_package(data: bytes) -> tuple[bytes, list[str]]:
    removed: list[str] = []
    source = zipfile.ZipFile(io.BytesIO(data))
    if len(source.infolist()) > 5000 or sum(i.file_size for i in source.infolist()) > 250 * 1024 * 1024:
        raise ValueError("Office archive exceeds safe expansion limits")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError("Unsafe Office archive path")
            if any(part in name.lower() for part in BLOCKED_PARTS):
                removed.append(name)
                continue
            content = source.read(info)
            if name.endswith(".rels"):
                root = ElementTree.fromstring(content)
                for relationship in list(root):
                    if relationship.get("TargetMode") == "External":
                        removed.append(f"external:{relationship.get('Target')}")
                        root.remove(relationship)
                content = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            # Keep the member's original timestamp: writestr(name, ...) stamps the current time, which made
            # the sanitized bytes (and their SHA-256) depend on when the scan ran.
            member = zipfile.ZipInfo(name, date_time=info.date_time)
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = info.external_attr
            target.writestr(member, content)
    return output.getvalue(), removed


# Backward-compatible name for callers that specifically validate PPTX packages.
disarm_pptx = disarm_office_package


def _clamav(data: bytes, settings: Settings) -> tuple[bool, str]:
    if not settings.clamav_host:
        return True, "structural-only"
    with socket.create_connection(
        (settings.clamav_host, settings.clamav_port), settings.clamav_timeout_seconds
    ) as connection:
        connection.sendall(b"zINSTREAM\0")
        for offset in range(0, len(data), 1024 * 1024):
            chunk = data[offset : offset + 1024 * 1024]
            connection.sendall(struct.pack("!I", len(chunk)) + chunk)
        connection.sendall(struct.pack("!I", 0))
        response = connection.recv(4096).decode("utf-8", "replace").strip("\0\r\n")
    return response.endswith("OK"), response


def scan_and_disarm(data: bytes, settings: Settings, media_type: str | None = None) -> ScanResult:
    if zipfile.is_zipfile(io.BytesIO(data)):
        sanitized, removed = disarm_office_package(data)
    elif media_type and (media_type.startswith("text/") or media_type == "application/csv"):
        if b"\x00" in data:
            raise ValueError("Text document contains NUL bytes")
        sanitized, removed = data, []
    else:
        sanitized, removed = data, []
    clean, response = _clamav(sanitized, settings)
    return ScanResult(
        clean,
        "clamav" if settings.clamav_host else "structural-cdr",
        sanitized,
        {
            "scanner_response": response,
            "removed_active_content": removed,
            "original_bytes": len(data),
            "sanitized_bytes": len(sanitized),
        },
    )
