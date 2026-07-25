from functools import lru_cache

from app.s3 import S3ObjectStore, sanitize_filename

# The S3 event notification only watches the originals prefix (see
# infra/aws/README.md). Writing resized images under a different prefix is what
# stops the resize Lambda's own PUT from re-triggering itself.
#
# KEEP IN SYNC with infra/aws/lambda/resize_image/handler.py, which re-declares
# these prefixes and the resized key layout - it deploys as its own bundle and
# cannot import from this package.
ORIGINALS_PREFIX = "images/originals"
RESIZED_PREFIX = "images/resized"


def build_original_key(project_id: int, image_id: int, filename: str) -> str:
    return f"{ORIGINALS_PREFIX}/{project_id}/{image_id}/{sanitize_filename(filename, 'image')}"


def build_resized_key(project_id: int, image_id: int, filename: str) -> str:
    return f"{RESIZED_PREFIX}/{project_id}/{image_id}/{sanitize_filename(filename, 'image')}"


class S3ImageStorage(S3ObjectStore):
    """Image key layout on top of the shared object store.

    Only ever writes the original; the resized object is written by the Lambda.
    """

    def save_original(self, project_id: int, image_id: int, filename: str, content: bytes) -> str:
        return self.put(build_original_key(project_id, image_id, filename), content)

    def delete_project_images(self, project_id: int) -> None:
        self.delete_prefix(f"{ORIGINALS_PREFIX}/{project_id}/")
        self.delete_prefix(f"{RESIZED_PREFIX}/{project_id}/")


@lru_cache
def get_image_storage() -> S3ImageStorage:
    # Cached for the same reason as get_storage() - see app/storage.py.
    return S3ImageStorage()
