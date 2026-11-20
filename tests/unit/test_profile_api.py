"""Unit tests for the segmentation rule of the profile API (risk profile -> campaigns)."""

# Built-in imports
import base64
import gzip
import importlib
import importlib.util
import json
import sys
from pathlib import Path

# External imports
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CDK_JSON = json.loads((REPO_ROOT / "cdk.json").read_text(encoding="utf-8"))
CAMPAIGNS = CDK_JSON["context"]["app_config"]["dev"]["campaigns"]


@pytest.fixture(scope="module")
def api():
    import os

    os.environ.update(
        {
            "USERS_TABLE": "users",
            "CATALOG_TABLE": "catalog",
            "CAMPAIGNS": json.dumps(CAMPAIGNS),
            "IMAGES_CDN_URL": "https://example.cloudfront.net",
            "IMAGES_CONFIG": json.dumps({"widths": [320, 640]}),
            "AWS_DEFAULT_REGION": "us-east-1",
        }
    )
    # Both Lambdas name their entry point handler.py: load this one by path under a unique module name
    spec = importlib.util.spec_from_file_location(
        "profile_api_handler", REPO_ROOT / "backend" / "lambdas" / "profile_api" / "handler.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["profile_api_handler"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("risk_profile", "expected"),
    [
        ("LOW", ["telefonia-rufus", "rufus-bolsillos-rentables"]),
        ("MEDIUM", ["telefonia-rufus", "creditos-rufus"]),
        ("HIGH", ["telefonia-rufus", "cryptomonedas-rufus"]),
    ],
)
def test_every_profile_gets_telefonia_plus_its_risk_campaign(api, risk_profile, expected):
    assert api.campaigns_for(risk_profile) == expected


def test_personalized_responses_are_never_cacheable_and_are_gzipped(api):
    event = {"headers": {"accept-encoding": "gzip, br"}}
    response = api.response(200, {"data": "x" * 5000}, event)
    assert response["headers"]["Cache-Control"] == "private, no-store"
    assert response["headers"]["Content-Encoding"] == "gzip"
    body = json.loads(gzip.decompress(base64.b64decode(response["body"])))
    assert body["data"] == "x" * 5000


def test_requests_without_email_claim_are_rejected(api):
    response = api.handler({"requestContext": {"authorizer": {"jwt": {"claims": {}}}}}, None)
    assert response["statusCode"] == 401
