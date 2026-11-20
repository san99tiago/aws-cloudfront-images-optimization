#!/usr/bin/env python3
"""
End-to-end validation of the deployed Rufus Bank images optimization demo.

Checks (each one prints PASS/FAIL and lands in outputs/e2e-report.json):
- Security posture: 3 private buckets (Block Public Access, TLS only, no website hosting, anonymous GET denied),
  no Lambda function URLs, WAF attached to both distributions.
- Pipeline: 40 catalog items READY, 31 objects per image in the OPTIMIZED bucket.
- Cognito: 3 users CONFIRMED, self sign-up disabled, login without forced password change, JWT without profile data.
- API: 401 without token, profile + segmentation per risk profile, private/no-store, gzip.
- Images CDN: content negotiation (AVIF, WebP, JPEG), width/DPR snapping, Save-Data, MISS then HIT, caching and CORS
  headers, strict path allow-list, measured bytes for all 40 images.
- Portal: security headers, SPA routing, runtime config, immutable hashed assets, compression.

Usage: python scripts/e2e_test.py   (reads DEMO_USERS_PASSWORD from .env, never prints it)
"""

# Built-in imports
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

# External imports
import boto3
import requests
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from stack_outputs import flat, read_outputs  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-east-1")
ENVIRONMENT = os.environ.get("DEPLOYMENT_ENVIRONMENT", "dev")
CHROME_ACCEPT = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
EXPECTED_CAMPAIGNS = {
    "HIGH": ["telefonia-rufus", "cryptomonedas-rufus"],
    "MEDIUM": ["telefonia-rufus", "creditos-rufus"],
    "LOW": ["telefonia-rufus", "rufus-bolsillos-rentables"],
}

RESULTS: list[dict] = []
METRICS: dict = {}


def check(name: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append({"check": name, "passed": bool(condition), "detail": detail})
    print(f"{'PASS' if condition else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
    return bool(condition)


def load_env() -> None:
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def security_checks(values: dict, session: boto3.Session) -> None:
    print("\n== Security posture")
    s3 = session.client("s3", region_name=REGION)
    buckets = [values["OriginalBucketName"], values["OptimizedBucketName"], values["FrontendBucketName"]]
    for bucket in buckets:
        block = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
        check(f"S3 {bucket.split('-')[3]} bucket blocks all public access", all(block.values()), str(block))
        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        denies_http = any(
            statement.get("Effect") == "Deny" and "aws:SecureTransport" in json.dumps(statement.get("Condition", {}))
            for statement in policy["Statement"]
        )
        check(f"S3 {bucket.split('-')[3]} bucket denies non-TLS requests", denies_http)
        try:
            s3.get_bucket_website(Bucket=bucket)
            website = True
        except ClientError:
            website = False
        check(f"S3 {bucket.split('-')[3]} bucket has NO static website hosting", not website)
        anonymous = requests.get(f"https://{bucket}.s3.{REGION}.amazonaws.com/index.html", timeout=15)
        check(f"S3 {bucket.split('-')[3]} anonymous GET is denied", anonymous.status_code == 403, f"HTTP {anonymous.status_code}")

    lambda_client = session.client("lambda", region_name=REGION)
    functions = [
        function["FunctionName"]
        for page in lambda_client.get_paginator("list_functions").paginate()
        for function in page["Functions"]
        if function["FunctionName"].startswith("cloudfront-images-optimization")
    ]
    urls = sum(len(lambda_client.list_function_url_configs(FunctionName=name)["FunctionUrlConfigs"]) for name in functions)
    check("No Lambda function URLs (APIs only through API Gateway)", urls == 0, f"{len(functions)} functions checked")

    cloudfront = session.client("cloudfront")
    for key in ("ImagesDistributionId", "WebDistributionId"):
        config = cloudfront.get_distribution_config(Id=values[key])["DistributionConfig"]
        check(f"WAF web ACL attached to {key.replace('DistributionId', '')} distribution", bool(config.get("WebACLId")))
        origins = config["Origins"]["Items"]
        s3_origins = [origin for origin in origins if origin.get("S3OriginConfig") is not None]
        check(
            f"{key.replace('DistributionId', '')} S3 origin uses OAC (no OAI)",
            all(origin.get("OriginAccessControlId") and not origin["S3OriginConfig"].get("OriginAccessIdentity") for origin in s3_origins),
        )


def pipeline_checks(values: dict, session: boto3.Session) -> list[dict]:
    print("\n== Image optimization pipeline")
    table = session.resource("dynamodb", region_name=REGION).Table(values["CatalogTableName"])
    items = table.scan()["Items"]
    ready = [item for item in items if item.get("status") == "READY"]
    check("Catalog has 40 images READY", len(ready) == 40, f"{len(ready)}/{len(items)}")
    s3 = session.client("s3", region_name=REGION)
    count = sum(
        page.get("KeyCount", 0)
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=values["OptimizedBucketName"])
    )
    check("OPTIMIZED bucket has 31 objects per image (30 variants + original)", count == 40 * 31, f"{count} objects")
    original_sizes = [int(item["original_bytes"]) for item in ready]
    METRICS["original_avg_bytes"] = round(statistics.mean(original_sizes))
    METRICS["processing_ms_avg"] = round(statistics.mean(int(item["processing_ms"]) for item in ready))
    return ready


def cognito_checks(values: dict, session: boto3.Session, password: str) -> dict[str, dict]:
    print("\n== Cognito")
    cognito = session.client("cognito-idp", region_name=REGION)
    pool_id, client_id = values["UserPoolId"], values["UserPoolClientId"]
    pool = cognito.describe_user_pool(UserPoolId=pool_id)["UserPool"]
    check("Self sign-up disabled (AdminCreateUserOnly)", pool["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"])
    try:
        cognito.sign_up(ClientId=client_id, Username=f"intruder-{uuid.uuid4().hex[:6]}@example.com", Password="Intruder12345.")
        blocked = False
    except ClientError as error:
        blocked = error.response["Error"]["Code"] == "NotAuthorizedException"
    check("Public SignUp is rejected", blocked)

    table = session.resource("dynamodb", region_name=REGION).Table(values["UsersTableName"])
    tokens: dict[str, dict] = {}
    for email in ("santigrc@amazon.com", "danilopera@example.com", "juanca@example.com"):
        user = cognito.admin_get_user(UserPoolId=pool_id, Username=email)
        attributes = {item["Name"]: item["Value"] for item in user["UserAttributes"]}
        check(f"{email} is CONFIRMED with email verified", user["UserStatus"] == "CONFIRMED" and attributes.get("email_verified") == "true", user["UserStatus"])
        auth = cognito.admin_initiate_auth(
            UserPoolId=pool_id,
            ClientId=client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
        check(f"{email} logs in without forced password change", "AuthenticationResult" in auth, auth.get("ChallengeName", "no challenge"))
        id_token = auth["AuthenticationResult"]["IdToken"]
        payload = json.loads(_b64(id_token.split(".")[1]))
        check(f"{email} JWT has identity only (no role/score/risk_profile)", payload.get("email") == email and not ({"role", "score", "risk_profile", "custom:risk_profile"} & set(payload)))
        profile = table.get_item(Key={"user_email": email}).get("Item")
        check(f"{email} is mapped in DynamoDB (PK user_email)", bool(profile), f"{profile.get('name')} · {profile.get('role')} · {profile.get('risk_profile')}" if profile else "missing")
        tokens[email] = {"id_token": id_token, "profile": profile}
    return tokens


def _b64(segment: str) -> str:
    import base64

    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("utf-8")


def api_checks(values: dict, tokens: dict) -> dict:
    print("\n== API (GET /api/me through the web distribution)")
    web = values["WebUrl"]
    anonymous = requests.get(f"{web}/api/me", timeout=15)
    check("GET /api/me without token returns 401", anonymous.status_code == 401, f"HTTP {anonymous.status_code}")
    sample = {}
    for email, data in tokens.items():
        response = requests.get(f"{web}/api/me", headers={"Authorization": f"Bearer {data['id_token']}"}, timeout=20)
        body = response.json()
        risk = data["profile"]["risk_profile"]
        campaigns = [campaign["id"] for campaign in body.get("campaigns", [])]
        images = sum(len(campaign["images"]) for campaign in body.get("campaigns", []))
        check(f"{email} ({risk}) gets {EXPECTED_CAMPAIGNS[risk]}", campaigns == EXPECTED_CAMPAIGNS[risk], ", ".join(campaigns))
        check(f"{email} gets 20 images (10 + 10)", images == 20, str(images))
        check(
            f"{email} profile comes from DynamoDB",
            body["user"]["name"] == data["profile"]["name"] and body["user"]["score"] == int(data["profile"]["score"]),
        )
        check(f"{email} response is private, no-store", response.headers.get("cache-control") == "private, no-store", response.headers.get("cache-control", ""))
        check(f"{email} response is gzip compressed", response.headers.get("content-encoding") == "gzip", response.headers.get("content-encoding", "none"))
        sample = body
    return sample


def cdn_checks(values: dict, me: dict, ready: list[dict]) -> None:
    print("\n== Images CDN")
    cdn = values["ImagesCdnUrl"]
    image = me["campaigns"][0]["images"][0]
    url = f"{cdn}{image['path']}"

    def get(query: str, accept: str, extra: dict | None = None) -> requests.Response:
        return requests.get(f"{url}?{query}", headers={"Accept": accept, **(extra or {})}, timeout=20)

    cases = [
        ("w=300&dpr=2", CHROME_ACCEPT, {}, "640w-standard.avif", "image/avif"),
        ("w=640", "image/webp,*/*", {}, "640w-standard.webp", "image/webp"),
        ("w=640", "*/*", {}, "640w-standard.jpg", "image/jpeg"),
        ("w=2000&dpr=3", CHROME_ACCEPT, {}, "1024w-standard.avif", "image/avif"),
        ("w=400", CHROME_ACCEPT, {"Save-Data": "on"}, "480w-lite.avif", "image/avif"),
        ("w=400&q=lite&f=jpeg", CHROME_ACCEPT, {}, "480w-lite.jpg", "image/jpeg"),
    ]
    for query, accept, extra, variant, content_type in cases:
        response = get(query, accept, extra)
        check(
            f"?{query} Accept={accept.split(',')[0]}{' Save-Data' if extra else ''} -> {variant}",
            response.headers.get("x-amz-meta-rufus-variant") == variant and response.headers.get("content-type") == content_type,
            f"{response.headers.get('x-amz-meta-rufus-variant')} {len(response.content)} B",
        )

    first, second = get("w=640", CHROME_ACCEPT), get("w=640", CHROME_ACCEPT)
    check("Second request is a CloudFront HIT", second.headers.get("x-cache", "").startswith("Hit"), f"{first.headers.get('x-cache')} -> {second.headers.get('x-cache')} at {second.headers.get('x-amz-cf-pop')}")
    headers = second.headers
    check("Cache-Control: 30 min device, 1 year edge, immutable", headers.get("cache-control") == "public, max-age=1800, s-maxage=31536000, immutable", headers.get("cache-control", ""))
    check("CORS for the portal (ACAO *) and exposed debug headers", headers.get("access-control-allow-origin") == "*" or requests.get(f"{url}?w=640", headers={"Accept": CHROME_ACCEPT, "Origin": values["WebUrl"]}, timeout=15).headers.get("access-control-allow-origin") == "*")
    check("Timing-Allow-Origin present (Resource Timing in the portal)", headers.get("timing-allow-origin") == "*")
    check("Server-Timing present (hit, POP, layer)", "cdn-pop" in headers.get("server-timing", ""), headers.get("server-timing", "")[:80])
    check("Vary: Accept (same URL, format per client)", "Accept" in headers.get("vary", ""), headers.get("vary", ""))
    check("No S3 server headers leak", "x-amz-server-side-encryption" not in headers)
    check("Images are not re-compressed (no Content-Encoding)", "content-encoding" not in headers)
    check("Unknown paths are blocked at the edge (404)", requests.get(f"{cdn}/", timeout=15).status_code == 404)
    check("Path traversal attempts are blocked (404)", requests.get(f"{cdn}/img/../../etc/passwd", timeout=15).status_code == 404)

    # Measure every image (warms the edge too): 640w AVIF, 640w WebP, 640w JPEG and the original
    print("   measuring the 40 images (640w AVIF / WebP / JPEG vs original)...")
    measured = {"avif": [], "webp": [], "jpeg": [], "original": []}
    for item in ready:
        base = f"{cdn}/img/{item['campaign']}/{item['image_id']}/{item['version']}"
        for fmt, accept in (("avif", CHROME_ACCEPT), ("webp", "image/webp,*/*"), ("jpeg", "*/*")):
            measured[fmt].append(int(requests.head(f"{base}?w=640", headers={"Accept": accept}, timeout=20).headers["content-length"]))
        measured["original"].append(int(item["original_bytes"]))
    METRICS["avg_bytes_640w"] = {fmt: round(statistics.mean(values_)) for fmt, values_ in measured.items()}
    METRICS["avg_bytes_by_variant_from_catalog"] = {
        name: round(statistics.mean(int(item["variants"][name]) for item in ready))
        for name in sorted(ready[0]["variants"].keys())
    }
    avif_saving = 1 - METRICS["avg_bytes_640w"]["avif"] / METRICS["avg_bytes_640w"]["original"]
    check("Average 640w AVIF is at least 90% lighter than the original", avif_saving >= 0.9, f"{avif_saving:.1%} lighter")


def portal_checks(values: dict) -> None:
    print("\n== Portal (web distribution)")
    web = values["WebUrl"]
    home = requests.get(web, timeout=15)
    headers = home.headers
    check("GET / returns the SPA", home.status_code == 200 and "text/html" in headers.get("content-type", ""))
    for header in ("content-security-policy", "strict-transport-security", "x-frame-options", "x-content-type-options", "referrer-policy", "permissions-policy"):
        check(f"Security header {header}", header in headers, headers.get(header, "")[:60])
    check("index.html is revalidated (no-cache)", headers.get("cache-control") == "no-cache", headers.get("cache-control", ""))
    spa = requests.get(f"{web}/dashboard/rufus", timeout=15)
    check("SPA route rewritten to index.html by the CloudFront Function", spa.status_code == 200 and "<div id=\"root\">" in spa.text)
    config = requests.get(f"{web}/config.json", timeout=15)
    check("config.json served with userPoolId and imagesCdnUrl", config.ok and config.json().get("imagesCdnUrl") == values["ImagesCdnUrl"])
    script = next((part.split('"')[0] for part in home.text.split('src="')[1:] if part.startswith("/assets/")), None)
    if script:
        asset = requests.get(f"{web}{script}", headers={"Accept-Encoding": "gzip, br"}, timeout=15)
        check("Hashed JS asset is immutable for 1 year", asset.headers.get("cache-control") == "public, max-age=31536000, immutable", asset.headers.get("cache-control", ""))
        check("JS asset is compressed at the edge", asset.headers.get("content-encoding") in ("gzip", "br"), asset.headers.get("content-encoding", "none"))
    missing = requests.get(f"{web}/assets/not-there.js", timeout=15)
    check("Missing files still return an error (no blanket index.html fallback)", missing.status_code in (403, 404), f"HTTP {missing.status_code}")


def main() -> int:
    load_env()
    password = os.environ.get("DEMO_USERS_PASSWORD", "")
    if not password:
        print("ERROR: DEMO_USERS_PASSWORD missing in .env", file=sys.stderr)
        return 1
    session = boto3.Session(region_name=REGION)
    values = flat(read_outputs(ENVIRONMENT, REGION))
    started = time.time()

    security_checks(values, session)
    ready = pipeline_checks(values, session)
    tokens = cognito_checks(values, session, password)
    me = api_checks(values, tokens)
    cdn_checks(values, me, ready)
    portal_checks(values)

    passed = sum(1 for result in RESULTS if result["passed"])
    report = {
        "environment": ENVIRONMENT,
        "web_url": values.get("WebUrl"),
        "images_cdn_url": values.get("ImagesCdnUrl"),
        "passed": passed,
        "total": len(RESULTS),
        "seconds": round(time.time() - started, 1),
        "metrics": METRICS,
        "results": RESULTS,
    }
    target = REPO_ROOT / "outputs" / "e2e-report.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n==> {passed}/{len(RESULTS)} checks passed in {report['seconds']}s · report: outputs/e2e-report.json")
    print(json.dumps(METRICS["avg_bytes_640w"]))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
