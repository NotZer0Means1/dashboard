"""Synchronous client for the image resize Lambda.

The Lambda used to be triggered by an S3 event notification on upload. It is now
invoked directly and synchronously by POST /image/{id}/resize, so the caller gets
the resized image back in one request instead of polling for a callback.

KEEP IN SYNC with infra/aws/lambda/resize_image/handler.py: the request payload
keys and the response shape below are that function's contract. It deploys as its
own bundle and cannot import from this package.
"""

import json
from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings


class ResizeInvocationError(Exception):
    """The Lambda could not be invoked, or crashed instead of returning a result.

    Distinct from the Lambda cleanly reporting that it could not decode the image
    (ResizeResult.ok == False), which is a problem with the image rather than
    with the infrastructure.
    """


@dataclass(frozen=True)
class ResizeResult:
    ok: bool
    resized_size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None


class ResizeLambdaClient:
    def __init__(self, function_name: str | None = None, client=None) -> None:
        settings = get_settings()
        self.function_name = function_name or settings.resize_lambda_name
        self.client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings):
        import boto3
        from botocore.config import Config

        # The function's own timeout is 30s; give the socket a little more so a
        # slow resize surfaces as the Lambda's error rather than a read timeout
        # here, and disable retries so a timeout can't silently resize twice.
        return boto3.client(
            "lambda",
            region_name=settings.aws_region,
            config=Config(read_timeout=40, connect_timeout=5, retries={"max_attempts": 0}),
        )

    def resize(
        self,
        *,
        bucket: str,
        source_key: str,
        target_key: str,
        filename: str,
        width: int,
        height: int,
    ) -> ResizeResult:
        payload = {
            "bucket": bucket,
            "source_key": source_key,
            "target_key": target_key,
            "filename": filename,
            "width": width,
            "height": height,
        }
        try:
            response = self.client.invoke(
                FunctionName=self.function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload).encode("utf-8"),
            )
        except Exception as exc:  # boto3/botocore errors are a wide family
            raise ResizeInvocationError(f"Could not invoke {self.function_name}: {exc}") from exc

        # An unhandled exception inside the function still returns HTTP 200 here;
        # FunctionError is the only thing that distinguishes it from a result.
        if response.get("FunctionError"):
            body = response["Payload"].read().decode("utf-8", "replace")
            raise ResizeInvocationError(f"{self.function_name} failed: {body}")

        try:
            result = json.loads(response["Payload"].read())
        except (KeyError, ValueError) as exc:
            raise ResizeInvocationError(f"{self.function_name} returned no usable payload") from exc

        if not result.get("ok"):
            return ResizeResult(ok=False, error=result.get("error", "resize failed"))
        return ResizeResult(
            ok=True,
            resized_size_bytes=result["resized_size_bytes"],
            width=result["width"],
            height=result["height"],
        )


@lru_cache
def get_resize_lambda_client() -> ResizeLambdaClient:
    # Cached for the same reason as get_storage() - see app/storage.py.
    return ResizeLambdaClient()
