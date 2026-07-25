"""Tests for the resize Lambda's pure helpers.

The handler deploys as its own bundle (no app imports), so it's loaded by path
rather than imported as a package module.
"""

import importlib.util
import pathlib

import pytest

_HANDLER_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "infra"
    / "aws"
    / "lambda"
    / "resize_image"
    / "handler.py"
)


@pytest.fixture(scope="module")
def handler(dummy_aws_credentials):
    import os

    os.environ.setdefault("CALLBACK_BASE_URL", "http://example.invalid")
    os.environ.setdefault("INTERNAL_CALLBACK_TOKEN", "testing")
    spec = importlib.util.spec_from_file_location("resize_handler", _HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_key_extracts_project_image_and_filename(handler):
    assert handler._parse_key("images/originals/12/34/my pic.jpg") == (12, 34, "my pic.jpg")


def test_parse_key_keeps_slashes_inside_filename(handler):
    assert handler._parse_key("images/originals/1/2/a/b.jpg") == (1, 2, "a/b.jpg")


@pytest.mark.parametrize("key", ["images/originals/1/2", "images/originals", "a/b/c/d"])
def test_parse_key_rejects_malformed_keys(handler, key):
    # Guards against an IndexError/ValueError crash on an unexpected S3 event.
    with pytest.raises(ValueError):
        handler._parse_key(key)
