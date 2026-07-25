"""Directly-invoked image resize Lambda.

Trigger: a synchronous boto3 invoke from the backend's POST /image/{id}/resize
(see app/lambda_client.py). There is deliberately no S3 event notification on the
bucket any more - resizing happens only when a user asks for it, so uploading an
image no longer costs a Lambda invocation.

Flow: download source_key -> resize with Pillow -> upload the result to
target_key -> return the outcome to the caller. The caller applies it to the
database, so this function does not call back into the app and needs no
credentials for it.

Resizing lives here and nowhere else - the app only pre-validates uploads
(app/image_validation.py) and never resizes. This deploys as its own zip/layer
bundle, so it deliberately does not import the app package.

KEEP IN SYNC with app/lambda_client.py, which builds the event below and parses
the response. _FORMAT_BY_EXTENSION must also cover every extension in
image_service.ALLOWED_EXTENSIONS, or new types silently fall back to JPEG.

Deployment note: Pillow ships C extensions, so it must be provided as a Lambda
layer built for the function's runtime/architecture (e.g. the public
"Klayers" Pillow layer, or one built via `pip install --platform manylinux2014_x86_64
--target . pillow` on Amazon Linux) - it will not work if just zipped from a
Windows/Mac dev machine's site-packages.
"""

import io
import os

import boto3
from PIL import Image, UnidentifiedImageError

s3 = boto3.client("s3")

# Only used when the caller omits the dimensions; the app normally sends them.
DEFAULT_DIMENSION = int(os.environ.get("MAX_IMAGE_DIMENSION", "512"))
# Hard ceiling regardless of what the caller asks for, so a bad request can't
# exhaust the function's memory. The app validates too; this is defence in depth.
MAX_DIMENSION = int(os.environ.get("MAX_ALLOWED_DIMENSION", "4096"))

_FORMAT_BY_EXTENSION = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


def _output_format(filename: str) -> str:
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _FORMAT_BY_EXTENSION.get(extension, "JPEG")


def _clamp(value, fallback: int) -> int:
    try:
        dimension = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(1, min(dimension, MAX_DIMENSION))


def _resize(content: bytes, output_format: str, width: int, height: int) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        image = image.convert("RGB") if output_format == "JPEG" else image
        # thumbnail() fits the image inside the box and preserves aspect ratio,
        # so the result can be smaller than requested in one dimension. It also
        # never upscales, which is why the original is kept as the resize source.
        image.thumbnail((width, height), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format=output_format)
        return buffer.getvalue(), image.width, image.height


def handler(event, context):
    bucket = event["bucket"]
    source_key = event["source_key"]
    target_key = event["target_key"]
    filename = event.get("filename") or source_key.rsplit("/", 1)[-1]
    width = _clamp(event.get("width"), DEFAULT_DIMENSION)
    height = _clamp(event.get("height"), DEFAULT_DIMENSION)

    try:
        original = s3.get_object(Bucket=bucket, Key=source_key)["Body"].read()
        resized_bytes, actual_width, actual_height = _resize(
            original, _output_format(filename), width, height
        )
    except (UnidentifiedImageError, OSError) as exc:
        # A decodable-image problem, not an infrastructure one: report it as a
        # result so the caller can mark the image rejected rather than retrying.
        return {"ok": False, "error": str(exc)}

    s3.put_object(Bucket=bucket, Key=target_key, Body=resized_bytes)

    return {
        "ok": True,
        "resized_size_bytes": len(resized_bytes),
        "width": actual_width,
        "height": actual_height,
    }
