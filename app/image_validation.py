import io

from PIL import Image as PILImage
from PIL import UnidentifiedImageError


class InvalidImageError(Exception):
    """Raised when image bytes can't be decoded: corrupt file, truncated upload,
    or content that doesn't actually match its extension."""


def validate_image(content: bytes) -> None:
    """Cheap structural check, without a full pixel decode. Rejects garbage before
    it's uploaded to S3 and handed off to the resize Lambda, which does the actual
    resizing - this module deliberately does none."""
    try:
        with PILImage.open(io.BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError(str(exc)) from exc
