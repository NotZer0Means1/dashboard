import pytest

from app.image_validation import InvalidImageError, validate_image
from tests.helpers import jpeg_bytes


def test_validate_image_accepts_real_image():
    validate_image(jpeg_bytes((10, 10)))  # must not raise


def test_validate_image_rejects_garbage_bytes():
    with pytest.raises(InvalidImageError):
        validate_image(b"not an image")


def test_validate_image_rejects_truncated_file():
    with pytest.raises(InvalidImageError):
        validate_image(jpeg_bytes((200, 200))[:20])
