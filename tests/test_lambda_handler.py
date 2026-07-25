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
    spec = importlib.util.spec_from_file_location("resize_handler", _HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("pic.jpg", "JPEG"),
        ("pic.JPEG", "JPEG"),
        ("pic.png", "PNG"),
        ("pic.webp", "WEBP"),
    ],
)
def test_output_format_maps_known_extensions(handler, filename, expected):
    assert handler._output_format(filename) == expected


@pytest.mark.parametrize("filename", ["noextension", "pic.bmp"])
def test_output_format_falls_back_to_jpeg(handler, filename):
    # The app rejects these at upload; this is just the handler not crashing.
    assert handler._output_format(filename) == "JPEG"


def test_clamp_passes_through_a_sane_dimension(handler):
    assert handler._clamp(512, 256) == 512


def test_clamp_uses_fallback_for_missing_or_junk_values(handler):
    assert handler._clamp(None, 256) == 256
    assert handler._clamp("wide", 256) == 256


def test_clamp_caps_absurd_dimensions(handler):
    # Without this a caller could ask for 50000x50000 and exhaust the function.
    assert handler._clamp(50_000, 256) == handler.MAX_DIMENSION


def test_clamp_floors_at_one(handler):
    assert handler._clamp(0, 256) == 1
    assert handler._clamp(-10, 256) == 1
