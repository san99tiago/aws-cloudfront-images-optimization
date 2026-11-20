"""Unit tests for the image optimizer (pure logic, no AWS calls)."""

# Built-in imports
import importlib
import importlib.util
import io
import sys
from pathlib import Path

# External imports
import pytest
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "lambdas" / "image_optimizer"))

import optimizer  # noqa: E402

MAGIC = {"avif": b"ftyp", "webp": b"WEBP", "jpeg": b"\xff\xd8\xff"}


@pytest.fixture(scope="module")
def original_png() -> bytes:
    """A 1024x1536 synthetic pop-up (gradient + shapes), similar in structure to the real campaign images."""
    image = Image.new("RGB", (1024, 1536))
    draw = ImageDraw.Draw(image)
    for y in range(1536):
        draw.line([(0, y), (1024, y)], fill=(10, 26 + y // 20, 63 + y // 12))
    draw.ellipse([212, 500, 812, 1100], fill=(255, 176, 32))
    draw.rounded_rectangle([200, 1350, 824, 1460], radius=55, fill=(0, 209, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def result(original_png):
    return optimizer.optimize_image(original_png, max_workers=4)


def test_builds_every_width_format_and_quality(result):
    names = {variant.name for variant in result.variants}
    assert len(result.variants) == 5 * 3 * 2
    assert "640w-standard.avif" in names and "320w-lite.jpg" in names and "1024w-standard.webp" in names


def test_encoded_bytes_match_the_declared_format(result):
    for variant in result.variants:
        if variant.format == "jpeg":
            assert variant.data.startswith(MAGIC["jpeg"])
        else:
            assert MAGIC[variant.format] in variant.data[:16]


def test_resizes_without_upscaling_and_keeps_the_aspect_ratio(original_png):
    result = optimizer.optimize_image(original_png, widths=[320, 2048])
    widths = sorted({variant.width for variant in result.variants})
    assert widths == [320, 1024]  # 2048 collapses into the original width
    for variant in result.variants:
        assert variant.height == round(1536 * variant.width / 1024)


def test_lite_tier_is_lighter_than_standard(result):
    sizes = {variant.name: variant.size for variant in result.variants}
    for width in (320, 640, 1024):
        for ext in ("avif", "webp", "jpg"):
            assert sizes[f"{width}w-lite.{ext}"] < sizes[f"{width}w-standard.{ext}"]


def test_modern_formats_are_lighter_than_jpeg(result):
    sizes = {variant.name: variant.size for variant in result.variants}
    assert sizes["640w-standard.avif"] < sizes["640w-standard.jpg"]
    assert sizes["640w-standard.webp"] < sizes["640w-standard.jpg"]


def test_version_is_a_stable_content_hash(original_png, result):
    assert result.version == optimizer.content_version(original_png)
    assert len(result.version) == 12
    assert optimizer.content_version(original_png + b"x") != result.version


def test_lqip_and_dominant_color_are_tiny(result):
    assert result.lqip.startswith("data:image/webp;base64,")
    assert len(result.lqip) < 1500
    assert result.dominant_color.startswith("#") and len(result.dominant_color) == 7


def test_handler_parses_only_campaign_keys(monkeypatch):
    monkeypatch.setenv("OPTIMIZED_BUCKET", "test-bucket")
    monkeypatch.setenv("CATALOG_TABLE", "test-table")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location(
        "image_optimizer_handler", REPO_ROOT / "backend" / "lambdas" / "image_optimizer" / "handler.py"
    )
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    assert handler.parse_key("campaigns/telefonia-rufus/telefonia-rufus-01.png") == (
        "telefonia-rufus",
        "telefonia-rufus-01",
        "png",
    )
    assert handler.parse_key("campaigns/telefonia-rufus/telefonia-rufus-01.JSON")[2] == "json"
    assert handler.parse_key("other/file.png") is None
    assert handler.parse_key("campaigns/no-extension") is None
