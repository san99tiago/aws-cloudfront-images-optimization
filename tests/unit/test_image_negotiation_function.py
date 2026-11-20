"""Unit tests for cloudfront/image-negotiation.js (executed with Node.js, same templating as the CDK stack)."""

# Built-in imports
import json
import shutil
import subprocess
from pathlib import Path

# External imports
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FUNCTION = REPO_ROOT / "cloudfront" / "image-negotiation.js"
WIDTHS = [320, 480, 640, 768, 1024]
BASE = "/img/telefonia-rufus/telefonia-rufus-01/4f3eec6bfd25"
ORIGIN = "/telefonia-rufus/telefonia-rufus-01/4f3eec6bfd25"
CHROME_ACCEPT = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is required")


def run(uri: str, query: dict | None = None, headers: dict | None = None) -> dict:
    code = FUNCTION.read_text().replace("__WIDTHS__", json.dumps(WIDTHS)).replace("__DEFAULT_WIDTH__", "640")
    event = {
        "request": {
            "uri": uri,
            "querystring": {key: {"value": value} for key, value in (query or {}).items()},
            "headers": {key.lower(): {"value": value} for key, value in (headers or {}).items()},
        }
    }
    script = code + f"\nprocess.stdout.write(JSON.stringify(handler({json.dumps(event)})));"
    output = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(output)


def test_avif_for_modern_browsers_with_dpr_snapping():
    result = run(BASE, {"w": "300", "dpr": "2"}, {"accept": CHROME_ACCEPT})
    assert result["uri"] == f"{ORIGIN}/640w-standard.avif"  # 300 * 2 = 600 -> 640 breakpoint
    assert result["querystring"] == {}


def test_webp_and_jpeg_fallbacks_from_accept_header():
    assert run(BASE, {"w": "640"}, {"accept": "image/webp,*/*"})["uri"] == f"{ORIGIN}/640w-standard.webp"
    assert run(BASE, {"w": "640"}, {"accept": "*/*"})["uri"] == f"{ORIGIN}/640w-standard.jpg"


def test_never_upscales_above_the_largest_variant_and_caps_dpr():
    assert run(BASE, {"w": "2000", "dpr": "5"}, {"accept": CHROME_ACCEPT})["uri"] == f"{ORIGIN}/1024w-standard.avif"


def test_default_width_when_missing():
    assert run(BASE, {}, {"accept": CHROME_ACCEPT})["uri"] == f"{ORIGIN}/640w-standard.avif"


def test_save_data_and_slow_networks_get_the_lite_tier():
    assert run(BASE, {"w": "320"}, {"accept": CHROME_ACCEPT, "save-data": "on"})["uri"] == f"{ORIGIN}/320w-lite.avif"
    assert run(BASE, {"w": "320"}, {"accept": CHROME_ACCEPT, "ect": "3g"})["uri"] == f"{ORIGIN}/320w-lite.avif"


def test_explicit_overrides_win():
    result = run(BASE, {"w": "480", "f": "jpeg", "q": "lite"}, {"accept": CHROME_ACCEPT})
    assert result["uri"] == f"{ORIGIN}/480w-lite.jpg"


def test_many_raw_requests_collapse_into_one_cache_key():
    uris = {run(BASE, {"w": str(width), "dpr": "1"}, {"accept": CHROME_ACCEPT})["uri"] for width in range(481, 641, 7)}
    assert uris == {f"{ORIGIN}/640w-standard.avif"}


def test_direct_variant_paths_pass_through_and_unknown_paths_are_rejected():
    direct = run(f"{ORIGIN}/768w-lite.webp", {"w": "100"})
    assert direct["uri"] == f"{ORIGIN}/768w-lite.webp" and direct["querystring"] == {}
    assert run(f"{ORIGIN}/original.png")["uri"] == f"{ORIGIN}/original.png"
    assert run("/")["statusCode"] == 404
    assert run("/img/../../etc/passwd")["statusCode"] == 404
