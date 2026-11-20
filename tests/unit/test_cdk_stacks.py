"""CDK assertions: the guardrails of the project (private buckets, no Lambda URLs, cache key, headers, auth)."""

# Built-in imports
import json
from pathlib import Path

# External imports
import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from stacks.cdk_backend_stack import BackendStack
from stacks.cdk_frontend_stack import FrontendStack
from stacks.cdk_images_stack import ImagesStack

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_CONFIG = json.loads((REPO_ROOT / "cdk.json").read_text(encoding="utf-8"))["context"]["app_config"]["dev"]
ENV = cdk.Environment(account="111111111111", region="us-east-1")


@pytest.fixture(scope="module")
def templates() -> dict[str, Template]:
    app = cdk.App()
    images = ImagesStack(app, "images", "cio", APP_CONFIG, env=ENV)
    backend = BackendStack(
        app,
        "backend",
        "cio",
        APP_CONFIG,
        catalog_table=images.catalog_table,
        images_cdn_url=f"https://{images.images_domain_name}",
        env=ENV,
    )
    frontend = FrontendStack(
        app,
        "frontend",
        "cio",
        APP_CONFIG,
        user_pool_id=backend.user_pool.user_pool_id,
        user_pool_client_id=backend.user_pool_client.user_pool_client_id,
        http_api_domain=backend.http_api_domain,
        images_cdn_domain=images.images_domain_name,
        env=ENV,
    )
    return {name: Template.from_stack(stack) for name, stack in (("images", images), ("backend", backend), ("frontend", frontend))}


def test_three_private_buckets(templates):
    private = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }
    }
    templates["images"].resource_count_is("AWS::S3::Bucket", 2)
    templates["frontend"].resource_count_is("AWS::S3::Bucket", 1)
    for name in ("images", "frontend"):
        templates[name].all_resources_properties("AWS::S3::Bucket", Match.object_like(private))
        # No S3 static website hosting anywhere
        for bucket in templates[name].find_resources("AWS::S3::Bucket").values():
            assert "WebsiteConfiguration" not in bucket["Properties"]


def test_no_lambda_function_urls(templates):
    for template in templates.values():
        template.resource_count_is("AWS::Lambda::Url", 0)


def test_images_cache_key_is_uri_only_without_compression(templates):
    templates["images"].has_resource_properties(
        "AWS::CloudFront::CachePolicy",
        {
            "CachePolicyConfig": Match.object_like(
                {
                    "ParametersInCacheKeyAndForwardedToOrigin": {
                        "CookiesConfig": {"CookieBehavior": "none"},
                        "HeadersConfig": {"HeaderBehavior": "none"},
                        "QueryStringsConfig": {"QueryStringBehavior": "none"},
                        "EnableAcceptEncodingGzip": False,
                        "EnableAcceptEncodingBrotli": False,
                    }
                }
            )
        },
    )


def test_images_distribution_best_practices(templates):
    templates["images"].has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "HttpVersion": "http2and3",
                    "IPV6Enabled": True,
                    "WebACLId": Match.any_value(),
                    "DefaultCacheBehavior": Match.object_like(
                        {
                            "Compress": False,
                            "ViewerProtocolPolicy": "redirect-to-https",
                            "FunctionAssociations": [Match.object_like({"EventType": "viewer-request"})],
                        }
                    ),
                    "Origins": [Match.object_like({"OriginShield": {"Enabled": True, "OriginShieldRegion": Match.any_value()}})],
                }
            )
        },
    )
    templates["images"].has_resource_properties(
        "AWS::CloudFront::ResponseHeadersPolicy",
        {
            "ResponseHeadersPolicyConfig": Match.object_like(
                {"ServerTimingHeadersConfig": {"Enabled": True, "SamplingRate": APP_CONFIG["images"]["server_timing_sampling_rate"]}}
            )
        },
    )
    templates["images"].has_resource_properties("AWS::WAFv2::WebACL", {"Scope": "CLOUDFRONT"})


def test_optimizer_lambda_runs_on_graviton_with_a_dlq(templates):
    templates["images"].has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Architectures": ["arm64"],
            "Runtime": "python3.14",
            "Handler": "handler.handler",
            "DeadLetterConfig": Match.any_value(),
        },
    )


def _local_demo_password() -> str | None:
    """Read DEMO_USERS_PASSWORD from the local .env (never hardcode it in the repository)."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEMO_USERS_PASSWORD="):
            return line.split("=", 1)[1].strip() or None
    return None


def test_cognito_has_no_self_sign_up_and_password_is_not_in_the_template(templates):
    backend = templates["backend"]
    backend.has_resource_properties(
        "AWS::Cognito::UserPool", {"AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True}}
    )
    backend.has_parameter("DemoUsersPassword", {"NoEcho": True, "Type": "String"})
    # The secret value is a reference to the NoEcho parameter, never a literal
    backend.has_resource_properties("AWS::SecretsManager::Secret", {"SecretString": {"Ref": "DemoUsersPassword"}})
    password = _local_demo_password()
    if password:
        assert password not in json.dumps(backend.to_json())


def test_portal_routes_the_api_through_cloudfront_without_cache(templates):
    templates["frontend"].has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CacheBehaviors": [
                        Match.object_like(
                            {
                                "PathPattern": "/api/*",
                                "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
                                "ViewerProtocolPolicy": "https-only",
                            }
                        )
                    ],
                    "WebACLId": Match.any_value(),
                }
            )
        },
    )
    templates["frontend"].has_resource_properties(
        "AWS::CloudFront::ResponseHeadersPolicy",
        {
            "ResponseHeadersPolicyConfig": Match.object_like(
                {
                    "SecurityHeadersConfig": Match.object_like(
                        {"ContentSecurityPolicy": Match.object_like({"Override": True})}
                    )
                }
            )
        },
    )
