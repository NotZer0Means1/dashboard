"""Tests for the resize Lambda client's request/response contract.

Everything here mocks boto3 - the point is the payload we send and how we read
what comes back, not AWS itself.
"""

import io
import json

import pytest

from app.lambda_client import ResizeInvocationError, ResizeLambdaClient


class _FakeLambda:
    """Minimal stand-in for a boto3 lambda client."""

    def __init__(self, payload=None, function_error=None, raises=None):
        self._payload = payload
        self._function_error = function_error
        self._raises = raises
        self.invoke_kwargs = None

    def invoke(self, **kwargs):
        self.invoke_kwargs = kwargs
        if self._raises:
            raise self._raises
        response = {"Payload": io.BytesIO(json.dumps(self._payload).encode())}
        if self._function_error:
            response["FunctionError"] = self._function_error
        return response


def _client(fake) -> ResizeLambdaClient:
    return ResizeLambdaClient(function_name="test-resize", client=fake)


def _resize(client: ResizeLambdaClient):
    return client.resize(
        bucket="bucket",
        source_key="images/originals/1/2/pic.jpg",
        target_key="images/resized/1/2/pic.jpg",
        filename="pic.jpg",
        width=512,
        height=256,
    )


def test_resize_sends_a_synchronous_invoke_with_the_full_payload():
    fake = _FakeLambda({"ok": True, "resized_size_bytes": 100, "width": 512, "height": 256})

    _resize(_client(fake))

    assert fake.invoke_kwargs["FunctionName"] == "test-resize"
    # Anything but RequestResponse and the caller would get no result back.
    assert fake.invoke_kwargs["InvocationType"] == "RequestResponse"
    assert json.loads(fake.invoke_kwargs["Payload"]) == {
        "bucket": "bucket",
        "source_key": "images/originals/1/2/pic.jpg",
        "target_key": "images/resized/1/2/pic.jpg",
        "filename": "pic.jpg",
        "width": 512,
        "height": 256,
    }


def test_resize_parses_a_successful_result():
    fake = _FakeLambda({"ok": True, "resized_size_bytes": 4096, "width": 512, "height": 256})

    result = _resize(_client(fake))

    assert (result.ok, result.resized_size_bytes) == (True, 4096)
    assert (result.width, result.height) == (512, 256)


def test_resize_returns_a_failed_result_when_the_lambda_could_not_decode():
    """A bad image is a result, not an exception - the caller marks it rejected."""
    fake = _FakeLambda({"ok": False, "error": "cannot identify image file"})

    result = _resize(_client(fake))

    assert result.ok is False
    assert result.error == "cannot identify image file"


def test_resize_raises_when_the_function_crashed():
    """An unhandled Lambda exception still returns HTTP 200 - FunctionError is
    the only thing separating it from a real result."""
    fake = _FakeLambda({"errorMessage": "boom"}, function_error="Unhandled")

    with pytest.raises(ResizeInvocationError):
        _resize(_client(fake))


def test_resize_raises_when_the_invoke_call_itself_fails():
    fake = _FakeLambda(raises=RuntimeError("ResourceNotFoundException"))

    with pytest.raises(ResizeInvocationError):
        _resize(_client(fake))


def test_resize_raises_on_an_unparseable_payload():
    class _Garbage:
        def invoke(self, **kwargs):
            return {"Payload": io.BytesIO(b"not json")}

    with pytest.raises(ResizeInvocationError):
        _resize(_client(_Garbage()))
