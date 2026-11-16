import io
import zipfile

from app.services.document_scanner import disarm_pptx


def test_disarm_removes_embedded_payloads_and_external_relationships():
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ppt/presentation.xml", "<presentation/>")
        archive.writestr("ppt/embeddings/payload.bin", b"payload")
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="https://example.invalid/payload" TargetMode="External"/></Relationships>',
        )
    sanitized, removed = disarm_pptx(source.getvalue())
    with zipfile.ZipFile(io.BytesIO(sanitized)) as archive:
        assert "ppt/embeddings/payload.bin" not in archive.namelist()
        assert b"example.invalid" not in archive.read("ppt/_rels/presentation.xml.rels")
    assert len(removed) == 2
