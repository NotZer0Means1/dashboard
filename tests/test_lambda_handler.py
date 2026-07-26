"""Tests for the resize Lambda's pure helpers.

The handler deploys as its own bundle (no app imports), so it's loaded by path
rather than imported as a package module. It also reads its callback settings
from the environment at import time, so those are set before loading it.

The weight here is on _is_original: the S3 notification cannot exclude the
function's own writes, so that predicate is the only thing standing between this
design and infinite recursion.
"""

import importlib.util
import os
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
    # CALLBACK_BASE_URL and INTERNAL_CALLBACK_TOKEN are read with os.environ[...]
    # at import time - the function is meant to fail fast on a misconfigured
    # deployment rather than discover it mid-resize.
    os.environ.setdefault("CALLBACK_BASE_URL", "http://localhost:8000")
    os.environ.setdefault("INTERNAL_CALLBACK_TOKEN", "testing-token")

    spec = importlib.util.spec_from_file_location("resize_handler", _HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- _is_original (the recursion guard) -----------------------------------


def test_is_original_accepts_an_original_key(handler):
    assert handler._is_original("projects/7/images/42/original/pic.jpg")


def test_is_original_rejects_the_functions_own_resized_write(handler):
    """The one that matters: a True here is an infinite resize loop."""
    assert not handler._is_original("projects/7/images/42/resized/pic.jpg")


def test_is_original_rejects_documents(handler):
    assert not handler._is_original("projects/7/documents/42/report.pdf")


@pytest.mark.parametrize(
    "key",
    [
        "projects/7/images/42/original",  # no filename
        "projects/7/images/42/original/",  # empty filename
        "projects/7/images/42/original/a/b.jpg",  # extra segment
        "projects/7/images/42/pic.jpg",  # missing the marker segment
        "uploads/7/images/42/original/pic.jpg",  # outside the projects subtree
        "pic.jpg",
    ],
)
def test_is_original_rejects_unexpected_layouts(handler, key):
    assert not handler._is_original(key)


# --- _parse_key / _resized_key --------------------------------------------


def test_parse_key_extracts_project_image_and_filename(handler):
    assert handler._parse_key("projects/7/images/42/original/pic.jpg") == (7, 42, "pic.jpg")


def test_parse_key_rejects_anything_is_original_rejects(handler):
    with pytest.raises(ValueError):
        handler._parse_key("projects/7/images/42/resized/pic.jpg")


def test_parse_key_rejects_a_non_numeric_id(handler):
    with pytest.raises(ValueError):
        handler._parse_key("projects/seven/images/42/original/pic.jpg")


def test_resized_key_sits_beside_the_original(handler):
    original = "projects/7/images/42/original/pic.jpg"

    assert handler._resized_key(*handler._parse_key(original)) == (
        "projects/7/images/42/resized/pic.jpg"
    )


def test_the_resized_key_is_not_itself_an_original(handler):
    """Belt and braces on the loop: whatever _resized_key produces must be
    something _is_original turns away."""
    resized = handler._resized_key(*handler._parse_key("projects/7/images/42/original/pic.jpg"))

    assert not handler._is_original(resized)


# --- agreement with the app ------------------------------------------------


def test_key_layout_matches_the_app_builders(handler):
    """KEEP IN SYNC with app/image_storage.py - if these drift, the app looks for
    the resized object under a key the Lambda never wrote and every image ends up
    rejected."""
    from app.image_storage import build_original_key, build_resized_key

    assert build_original_key(7, 42, "pic.jpg") == "projects/7/images/42/original/pic.jpg"

    project_id, image_id, filename = handler._parse_key(build_original_key(7, 42, "pic.jpg"))
    assert handler._resized_key(project_id, image_id, filename) == build_resized_key(
        7, 42, "pic.jpg"
    )


def test_notification_prefix_matches_the_app_projects_prefix(handler):
    from app.s3 import PROJECTS_PREFIX

    assert handler.PROJECTS_PREFIX == f"{PROJECTS_PREFIX}/"
