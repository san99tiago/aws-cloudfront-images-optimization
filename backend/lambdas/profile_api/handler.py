"""
Rufus Bank profile API (AWS Lambda behind API Gateway HTTP API + Cognito JWT authorizer).

GET /api/me
- Identity comes from the validated JWT (claims injected by the API Gateway authorizer): only the email.
- Business metadata (name, role, score, risk_profile) is NOT in the JWT: it is read from DynamoDB (PK user_email).
- The risk profile decides which campaigns (and therefore which 10 + 10 images) the portal must load.
- The response is personalized, so it is never cacheable by shared caches (Cache-Control: private, no-store).
"""

# Built-in imports
import base64
import gzip
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

# External imports
import boto3
from boto3.dynamodb.conditions import Key

LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

USERS_TABLE = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"])
CATALOG_TABLE = boto3.resource("dynamodb").Table(os.environ["CATALOG_TABLE"])
CAMPAIGNS = json.loads(os.environ["CAMPAIGNS"])  # {"telefonia-rufus": {"name": ..., "audience": "ALL"}, ...}
IMAGES_CDN_URL = os.environ["IMAGES_CDN_URL"]
IMAGES_CONFIG = json.loads(os.environ["IMAGES_CONFIG"])


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"not serializable: {type(value)}")


def response(status: int, body: dict, event: dict | None = None) -> dict:
    payload = json.dumps(body, default=_json_default, ensure_ascii=False)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        # Personalized data: browsers may keep it in memory, shared caches (CloudFront) must not store it
        "Cache-Control": "private, no-store",
        "Vary": "Authorization, Accept-Encoding",
    }
    accept_encoding = ((event or {}).get("headers") or {}).get("accept-encoding", "")
    # CloudFront does not compress when caching is disabled, so the Lambda gzips large JSON responses itself
    if "gzip" in accept_encoding and len(payload) > 1024:
        headers["Content-Encoding"] = "gzip"
        return {
            "statusCode": status,
            "headers": headers,
            "isBase64Encoded": True,
            "body": base64.b64encode(gzip.compress(payload.encode("utf-8"), compresslevel=6)).decode("ascii"),
        }
    return {"statusCode": status, "headers": headers, "body": payload}


def campaigns_for(risk_profile: str) -> list[str]:
    """Segmentation rule: every profile sees the ALL campaigns plus the one of its risk profile."""
    selected = [cid for cid, campaign in CAMPAIGNS.items() if campaign["audience"] == "ALL"]
    selected += [cid for cid, campaign in CAMPAIGNS.items() if campaign["audience"] == risk_profile]
    return selected


def load_images(campaign_id: str) -> list[dict]:
    items = CATALOG_TABLE.query(KeyConditionExpression=Key("campaign").eq(campaign_id)).get("Items", [])
    images = []
    for item in sorted(items, key=lambda value: value["image_id"]):
        if item.get("status") != "READY":
            continue
        base = f"{campaign_id}/{item['image_id']}/{item['version']}"
        images.append(
            {
                "id": item["image_id"],
                "title": item.get("title", item["image_id"]),
                "subtitle": item.get("subtitle", ""),
                "cta": item.get("cta", ""),
                "alt": item.get("alt", item.get("title", "")),
                "version": item["version"],
                # Negotiated URL (CloudFront Function picks width, format and quality)
                "path": f"/img/{base}",
                "original": {
                    "path": f"/{base}/original.{item.get('original_ext', 'png')}",
                    "bytes": item.get("original_bytes"),
                    "width": item.get("original_width"),
                    "height": item.get("original_height"),
                    "format": item.get("original_format"),
                },
                "variants": item.get("variants", {}),
                "lqip": item.get("lqip"),
                "dominant_color": item.get("dominant_color"),
                "optimized_at": item.get("optimized_at"),
                "processing_ms": item.get("processing_ms"),
            }
        )
    return images


def handler(event, context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    email = (claims.get("email") or "").lower()
    if not email:
        return response(401, {"message": "the token has no email claim (send the Cognito ID token)"}, event)

    profile = USERS_TABLE.get_item(Key={"user_email": email}).get("Item")
    if not profile:
        return response(404, {"message": f"no profile mapped in DynamoDB for {email}"}, event)

    risk_profile = str(profile.get("risk_profile", "LOW")).upper()
    selected = campaigns_for(risk_profile)
    campaigns = [
        {
            "id": campaign_id,
            "name": CAMPAIGNS[campaign_id]["name"],
            "audience": CAMPAIGNS[campaign_id]["audience"],
            "images": load_images(campaign_id),
        }
        for campaign_id in selected
    ]

    LOGGER.info(json.dumps({"message": "profile served", "risk_profile": risk_profile, "campaigns": selected}))
    return response(
        200,
        {
            "user": {
                "email": email,
                "name": profile.get("name"),
                "role": profile.get("role"),
                "score": profile.get("score"),
                "risk_profile": risk_profile,
            },
            "token": {
                "sub": claims.get("sub"),
                "token_use": claims.get("token_use"),
                "issuer": claims.get("iss"),
                "expires_at": claims.get("exp"),
            },
            "segmentation": {
                "rule": "ALL campaigns for everybody + the campaign whose audience matches risk_profile",
                "audiences": {campaign_id: value["audience"] for campaign_id, value in CAMPAIGNS.items()},
                "selected": selected,
            },
            "campaigns": campaigns,
            "cdn": {"base_url": IMAGES_CDN_URL, **IMAGES_CONFIG},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        event,
    )
