import io

from PIL import Image as PILImage


class FakeUploadFile:
    """Stand-in for fastapi.UploadFile - only .filename/.content_type/.read() are used."""

    def __init__(self, filename: str, content: bytes, content_type: str = "application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


def jpeg_bytes(size: tuple[int, int] = (800, 800), color: str = "blue") -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", size, color=color).save(buffer, format="JPEG")
    return buffer.getvalue()
