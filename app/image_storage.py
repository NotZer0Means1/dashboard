from functools import lru_cache

from app.s3 import S3ObjectStore, project_prefix, sanitize_filename

# An image owns a folder, and the two copies sit side by side inside it:
#
#   projects/{project_id}/images/{image_id}/original/{filename}
#   projects/{project_id}/images/{image_id}/resized/{filename}
#
# The last segment before the filename is what tells them apart, and it is the
# only thing that does - the S3 notification cannot filter on it (no wildcards
# in prefixes), so the resize Lambda checks it in code and ignores anything that
# is not an original. Without that check its own write would re-trigger it.
#
# KEEP IN SYNC with infra/aws/lambda/resize_image/handler.py, which re-declares
# this layout - it deploys as its own bundle and cannot import from this package.
# tests/test_lambda_handler.py fails if the two drift.
ORIGINAL_SEGMENT = "original"
RESIZED_SEGMENT = "resized"


def build_image_prefix(project_id: int, image_id: int) -> str:
    return f"{project_prefix(project_id)}/images/{image_id}"


def build_original_key(project_id: int, image_id: int, filename: str) -> str:
    safe = sanitize_filename(filename, "image")
    return f"{build_image_prefix(project_id, image_id)}/{ORIGINAL_SEGMENT}/{safe}"


def build_resized_key(project_id: int, image_id: int, filename: str) -> str:
    safe = sanitize_filename(filename, "image")
    return f"{build_image_prefix(project_id, image_id)}/{RESIZED_SEGMENT}/{safe}"


class S3ImageStorage(S3ObjectStore):
    """Image key layout on top of the shared object store.

    Only ever writes the original; the resized object is written by the Lambda.
    """

    def save_original(self, project_id: int, image_id: int, filename: str, content: bytes) -> str:
        return self.put(build_original_key(project_id, image_id, filename), content)

    def delete_project_images(self, project_id: int) -> None:
        # One sweep takes both copies of every image, since they share a folder.
        self.delete_prefix(f"{project_prefix(project_id)}/images/")


@lru_cache
def get_image_storage() -> S3ImageStorage:
    # Cached for the same reason as get_storage() - see app/storage.py.
    return S3ImageStorage()
