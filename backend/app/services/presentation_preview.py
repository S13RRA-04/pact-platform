"""Text-only slide previews and metadata for controlled PPTX comparison."""

import io
import re
import zipfile

from defusedxml import ElementTree


def preview_pptx(data: bytes) -> dict[str, object]:
    slides = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=lambda name: int(re.search(r"\d+", name).group()),
        )
        for index, name in enumerate(names, 1):
            root = ElementTree.fromstring(archive.read(name))
            texts = [
                node.text.strip()
                for node in root.iter()
                if node.tag.endswith("}t") and node.text and node.text.strip()
            ]
            slides.append(
                {"number": index, "title": texts[0] if texts else f"Slide {index}", "text": "\n".join(texts)}
            )
    return {"slide_count": len(slides), "slides": slides}
