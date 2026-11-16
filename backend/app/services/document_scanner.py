"""PPTX structural disarm and ClamAV INSTREAM scanning."""

from __future__ import annotations

import io
import socket
import struct
import zipfile
from dataclasses import dataclass

from defusedxml import ElementTree

from app.config import Settings

BLOCKED_PARTS = ("ppt/embeddings/", "ppt/activex/", "vbaproject.bin")
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass
class ScanResult:
    clean: bool
    engine: str
    sanitized: bytes
    details: dict[str, object]


def disarm_pptx(data: bytes) -> tuple[bytes, list[str]]:
    removed: list[str] = []
    source = zipfile.ZipFile(io.BytesIO(data))
    if len(source.infolist()) > 5000 or sum(i.file_size for i in source.infolist()) > 250 * 1024 * 1024:
        raise ValueError("PPTX archive exceeds safe expansion limits")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError("Unsafe PPTX archive path")
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
            target.writestr(name, content)
    return output.getvalue(), removed


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


def scan_and_disarm(data: bytes, settings: Settings) -> ScanResult:
    sanitized, removed = disarm_pptx(data)
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
