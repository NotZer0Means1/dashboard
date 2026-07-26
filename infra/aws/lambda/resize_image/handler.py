"""S3-event-triggered image resize Lambda.

Trigger: S3 ObjectCreated notification scoped to the "projects/" prefix. That
filter cannot be narrower - notification prefixes take no wildcards, and the
project id sits in the middle of the key - so this function is also invoked for
document uploads and for its OWN writes of resized copies. _is_original() below
is what stops that from becoming infinite recursion; it is load-bearing, not a
tidiness check. See "Wire up the resize Lambda" in infra/aws/README.md.

Keys look like:

    projects/{project_id}/images/{image_id}/original/{filename}   <- resize this
    projects/{project_id}/images/{image_id}/resized/{filename}    <- ignore
    projects/{project_id}/documents/{document_id}/{filename}      <- ignore

Flow: download the original -> resize with Pillow -> upload the result beside it
under .../resized/{filename} -> POST the outcome back to the backend's
/internal/images/{image_id}/resize-callback, authenticated with a shared secret
(INTERNAL_CALLBACK_TOKEN) rather than a user token, since this call has no
logged-in user behind it.

Resizing lives here and nowhere else - the app only pre-validates uploads
(app/image_validation.py) and never resizes. This deploys as its own zip/layer
bundle, so it deliberately does not import the app package.

KEEP IN SYNC with app/image_storage.py, which builds these same keys. If they
drift, the app looks for the resized object under a key this function never
wrote and every image ends up "rejected" - tests/test_lambda_handler.py fails if
that happens. Likewise _FORMAT_BY_EXTENSION must cover every extension in
image_service.ALLOWED_EXTENSIONS, or new types silently fall back to JPEG.

Deployment note: Pillow ships C extensions, so it must be provided as a Lambda
layer built for the function's runtime/architecture (e.g. the public
"Klayers" Pillow layer, or one built via `pip install --platform manylinux2014_x86_64
--target . pillow` on Amazon Linux) - it will not work if just zipped from a
Windows/Mac dev machine's site-packages.
"""

import io
import json
import os
import urllib.error
import urllib.request
from urllib.parse import unquote_plus

import boto3
from PIL import Image, UnidentifiedImageError

s3 = boto3.client("s3")

PROJECTS_PREFIX = "projects/"
ORIGINAL_SEGMENT = "original"
RESIZED_SEGMENT = "resized"

MAX_IMAGE_DIMENSION = int(os.environ.get("MAX_IMAGE_DIMENSION", "512"))
CALLBACK_BASE_URL = os.environ["CALLBACK_BASE_URL"]  # e.g. http://<ec2-ip>:8000
INTERNAL_CALLBACK_TOKEN = os.environ["INTERNAL_CALLBACK_TOKEN"]

_FORMAT_BY_EXTENSION = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


def _is_original(key: str) -> bool:
    """Whether this key is an image original, and so ours to resize.

    THE RECURSION GUARD. The notification cannot exclude our own resized writes
    (see the module docstring), so returning True for one would have this
    function resize its own output forever. Everything else under projects/ -
    resized copies, documents - has to fall out here.
    """
    parts = key.split("/")
    return (
        len(parts) == 6
        and parts[0] == PROJECTS_PREFIX.rstrip("/")
        and parts[2] == "images"
        and parts[4] == ORIGINAL_SEGMENT
        and bool(parts[5])
    )


def _parse_key(key: str) -> tuple[int, int, str]:
    # projects/{project_id}/images/{image_id}/original/{filename}
    if not _is_original(key):
        raise ValueError(f"Unexpected S3 key layout: {key!r}")
    _, project_id, _, image_id, _, filename = key.split("/")
    return int(project_id), int(image_id), filename


def _resized_key(project_id: int, image_id: int, filename: str) -> str:
    return f"{PROJECTS_PREFIX}{project_id}/images/{image_id}/{RESIZED_SEGMENT}/{filename}"


def _resize(content: bytes, output_format: str) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        image = image.convert("RGB") if output_format == "JPEG" else image
        image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format=output_format)
        return buffer.getvalue(), image.width, image.height


def _callback(image_id: int, payload: dict) -> None:
    url = f"{CALLBACK_BASE_URL}/internal/images/{image_id}/resize-callback"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Internal-Token": INTERNAL_CALLBACK_TOKEN,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        # 404 (image row disappeared) or 401 (token mismatch) etc - nothing to
        # retry into, just surface it in CloudWatch logs.
        print(f"callback for image {image_id} failed: {exc.code} {exc.read()}")
        raise


def handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        if not _is_original(key):
            # A resized copy we just wrote, or a document. Dropping these is what
            # keeps the function from triggering itself - see _is_original.
            continue

        project_id, image_id, filename = _parse_key(key)
        extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        output_format = _FORMAT_BY_EXTENSION.get(extension, "JPEG")

        try:
            original = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            resized_bytes, width, height = _resize(original, output_format)
        except (UnidentifiedImageError, OSError) as exc:
            _callback(image_id, {"failed": True, "error": str(exc)})
            continue

        s3.put_object(
            Bucket=bucket, Key=_resized_key(project_id, image_id, filename), Body=resized_bytes
        )

        _callback(
            image_id,
            {
                "resized_size_bytes": len(resized_bytes),
                "width": width,
                "height": height,
            },
        )
