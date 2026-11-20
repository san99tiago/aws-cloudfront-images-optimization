"""
Rufus Bank image optimizer (AWS Lambda, Python 3.14, arm64).

Trigger: S3 event notifications from the ORIGINAL bucket.
- ObjectCreated  campaigns/<campaign>/<image_id>.png|jpg|jpeg|webp  -> build every variant into the OPTIMIZED bucket
- ObjectCreated  campaigns/<campaign>/<image_id>.json               -> upsert the marketing copy in the catalog
- ObjectRemoved  campaigns/<campaign>/<image_id>.<image ext>        -> delete the variants and the catalog item

Optimized key layout (immutable, versioned by content hash, so no CloudFront invalidations are needed):
    <campaign>/<image_id>/<version>/<width>w-<quality_tier>.<ext>
    <campaign>/<image_id>/<version>/original.<ext>
"""

# Built-in imports
import json
import logging
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

# External imports
import boto3
from botocore.config import Config

# Own imports
from optimizer import DEFAULT_QUALITY_PROFILES, FORMAT_SETTINGS, content_version, optimize_image

LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

OPTIMIZED_BUCKET = os.environ["OPTIMIZED_BUCKET"]
CATALOG_TABLE = os.environ["CATALOG_TABLE"]
WIDTHS = [int(value) for value in os.environ.get("WIDTHS", "320,480,640,768,1024").split(",")]
FORMATS = os.environ.get("FORMATS", "avif,webp,jpeg").split(",")
QUALITY_PROFILES = json.loads(os.environ.get("QUALITY_PROFILES", json.dumps(DEFAULT_QUALITY_PROFILES)))
CACHE_CONTROL = os.environ.get("CACHE_CONTROL", "public, max-age=1800, s-maxage=31536000, immutable")
METRICS_NAMESPACE = os.environ.get("METRICS_NAMESPACE", "RufusBank/ImageOptimizer")
IMAGE_EXTENSIONS = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}

_config = Config(retries={"max_attempts": 8, "mode": "adaptive"}, max_pool_connections=32)
S3 = boto3.client("s3", config=_config)
TABLE = boto3.resource("dynamodb", config=_config).Table(CATALOG_TABLE)


def log(message: str, **fields) -> None:
    """Structured JSON logs (easy to query with CloudWatch Logs Insights)."""
    LOGGER.info(json.dumps({"message": message, **fields}, default=str))


def emit_metrics(campaign: str, original_bytes: int, optimized_bytes: int, processing_ms: int) -> None:
    """CloudWatch Embedded Metric Format: custom metrics from a log line, without PutMetricData calls."""
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": METRICS_NAMESPACE,
                            "Dimensions": [["Service"]],
                            "Metrics": [
                                {"Name": "ProcessingTime", "Unit": "Milliseconds"},
                                {"Name": "OriginalBytes", "Unit": "Bytes"},
                                {"Name": "OptimizedBytes640Avif", "Unit": "Bytes"},
                            ],
                        }
                    ],
                },
                "Service": "image-optimizer",
                "Campaign": campaign,
                "ProcessingTime": processing_ms,
                "OriginalBytes": original_bytes,
                "OptimizedBytes640Avif": optimized_bytes,
            }
        )
    )


def parse_key(key: str) -> tuple[str, str, str] | None:
    """campaigns/<campaign>/<image_id>.<ext> -> (campaign, image_id, ext)."""
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "campaigns" or "." not in parts[2]:
        return None
    image_id, ext = parts[2].rsplit(".", 1)
    return parts[1], image_id, ext.lower()


def delete_prefix(prefix: str, keep_prefix: str | None = None) -> int:
    """Delete every optimized object under a prefix (optionally keeping the current version)."""
    deleted = 0
    paginator = S3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=OPTIMIZED_BUCKET, Prefix=prefix):
        keys = [
            {"Key": item["Key"]}
            for item in page.get("Contents", [])
            if not (keep_prefix and item["Key"].startswith(keep_prefix))
        ]
        for start in range(0, len(keys), 1000):
            batch = keys[start : start + 1000]
            if batch:
                S3.delete_objects(Bucket=OPTIMIZED_BUCKET, Delete={"Objects": batch, "Quiet": True})
                deleted += len(batch)
    return deleted


def process_image(bucket: str, key: str, campaign: str, image_id: str, ext: str) -> dict:
    """Download the original, build the variants, upload them and update the catalog."""
    started = time.perf_counter()
    original = S3.get_object(Bucket=bucket, Key=key)
    data = original["Body"].read()

    # Idempotency: S3 can deliver the same event more than once, and a re-upload of identical bytes
    # keeps the same content hash, so there is nothing new to encode
    version = content_version(data)
    current = TABLE.get_item(Key={"campaign": campaign, "image_id": image_id}).get("Item") or {}
    if current.get("version") == version and current.get("status") == "READY":
        log("skip: version already optimized", key=key, version=version)
        return {"key": key, "skipped": True}

    result = optimize_image(
        data,
        widths=WIDTHS,
        formats=FORMATS,
        quality_profiles=QUALITY_PROFILES,
        max_workers=max(2, (os.cpu_count() or 2) * 2),
    )

    base_prefix = f"{campaign}/{image_id}/"
    version_prefix = f"{base_prefix}{result.version}/"
    common_metadata = {
        "rufus-campaign": campaign,
        "rufus-image-id": image_id,
        "rufus-version": result.version,
        "rufus-original-bytes": str(result.original_bytes),
        "rufus-original-size": f"{result.original_width}x{result.original_height}",
    }

    uploads = [
        {
            "Key": f"{version_prefix}{variant.name}",
            "Body": variant.data,
            "ContentType": variant.content_type,
            "Metadata": {
                **common_metadata,
                "rufus-variant": variant.name,
                "rufus-format": variant.format,
                "rufus-width": str(variant.width),
                "rufus-height": str(variant.height),
                "rufus-quality": f"{variant.quality_tier}:{variant.quality_value}",
            },
        }
        for variant in result.variants
    ]
    uploads.append(
        {
            "Key": f"{version_prefix}original.{ext}",
            "Body": data,
            "ContentType": IMAGE_EXTENSIONS.get(ext, "application/octet-stream"),
            "Metadata": {
                **common_metadata,
                "rufus-variant": f"original.{ext}",
                "rufus-format": result.original_format,
                "rufus-width": str(result.original_width),
                "rufus-height": str(result.original_height),
                "rufus-quality": "original",
            },
        }
    )

    def put(item: dict) -> None:
        S3.put_object(Bucket=OPTIMIZED_BUCKET, CacheControl=CACHE_CONTROL, **item)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(put, uploads))

    variants_map = {variant.name: variant.size for variant in result.variants}
    variants_map[f"original.{ext}"] = result.original_bytes
    processing_ms = round((time.perf_counter() - started) * 1000)

    TABLE.update_item(
        Key={"campaign": campaign, "image_id": image_id},
        UpdateExpression=(
            "SET #status = :status, version = :version, original_key = :original_key, original_bytes = :ob, "
            "original_width = :ow, original_height = :oh, original_format = :of, original_ext = :oe, "
            "variants = :variants, widths = :widths, formats = :formats, quality_tiers = :tiers, "
            "lqip = :lqip, dominant_color = :color, cache_control = :cc, optimized_at = :at, "
            "processing_ms = :pms"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "READY",
            ":version": result.version,
            ":original_key": key,
            ":ob": result.original_bytes,
            ":ow": result.original_width,
            ":oh": result.original_height,
            ":of": result.original_format,
            ":oe": ext,
            ":variants": variants_map,
            ":widths": sorted({variant.width for variant in result.variants}),
            ":formats": FORMATS,
            ":tiers": list(QUALITY_PROFILES.keys()),
            ":lqip": result.lqip,
            ":color": result.dominant_color,
            ":cc": CACHE_CONTROL,
            ":at": datetime.now(timezone.utc).isoformat(),
            ":pms": Decimal(processing_ms),
        },
    )

    # Old versions are never requested again (new URLs), so they can be removed from the bucket
    removed = delete_prefix(base_prefix, keep_prefix=version_prefix)

    reference = next(
        (v.size for v in result.variants if v.width == 640 and v.format == "avif" and v.quality_tier == "standard"),
        0,
    )
    emit_metrics(campaign, result.original_bytes, reference, processing_ms)
    log(
        "optimized",
        key=key,
        version=result.version,
        variants=len(uploads),
        original_bytes=result.original_bytes,
        bytes_640w_avif=reference,
        old_objects_removed=removed,
        processing_ms=processing_ms,
        encode_ms=result.processing_ms,
    )
    return {"key": key, "version": result.version, "variants": len(uploads)}


def process_sidecar(bucket: str, key: str, campaign: str, image_id: str) -> dict:
    """Upsert the marketing copy (title, subtitle, CTA, alt) of one image."""
    body = json.loads(S3.get_object(Bucket=bucket, Key=key)["Body"].read())
    fields = {name: body[name] for name in ("title", "subtitle", "cta", "alt", "campaign_name") if body.get(name)}
    if not fields:
        return {"key": key, "skipped": True}
    names = {f"#{name}": name for name in fields}
    values = {f":{name}": value for name, value in fields.items()}
    TABLE.update_item(
        Key={"campaign": campaign, "image_id": image_id},
        UpdateExpression="SET " + ", ".join(f"#{name} = :{name}" for name in fields),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    log("sidecar upserted", key=key, fields=list(fields))
    return {"key": key, "metadata": list(fields)}


def remove_image(campaign: str, image_id: str) -> dict:
    deleted = delete_prefix(f"{campaign}/{image_id}/")
    TABLE.delete_item(Key={"campaign": campaign, "image_id": image_id})
    log("removed", campaign=campaign, image_id=image_id, deleted=deleted)
    return {"removed": image_id, "deleted": deleted}


def handler(event, context):
    """Entry point for S3 event notifications (one or more records)."""
    results = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        parsed = parse_key(key)
        if not parsed:
            log("ignored key", key=key)
            continue
        campaign, image_id, ext = parsed
        event_name = record.get("eventName", "")

        if event_name.startswith("ObjectRemoved"):
            if ext in IMAGE_EXTENSIONS:
                results.append(remove_image(campaign, image_id))
        elif ext == "json":
            results.append(process_sidecar(bucket, key, campaign, image_id))
        elif ext in IMAGE_EXTENSIONS:
            results.append(process_image(bucket, key, campaign, image_id, ext))
        else:
            log("ignored extension", key=key)

    return {"processed": results}


__all__ = ["handler", "parse_key", "FORMAT_SETTINGS"]
