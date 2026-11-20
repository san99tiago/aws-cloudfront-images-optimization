"""
Pure image optimization logic (no AWS calls), so it can be unit tested and benchmarked locally.

For every original it produces:
- widths x formats x quality tiers variants (for example 5 x 3 x 2 = 30 files)
- a tiny LQIP (low quality image placeholder) as a base64 data URI, for blur-up loading
- the dominant color, as a solid placeholder while the LQIP or the variant arrives
"""

# Built-in imports
import base64
import hashlib
import io
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

# External imports
from PIL import Image, ImageOps, features

FORMAT_SETTINGS = {
    # Pillow format name, content type and file extension per output format
    "avif": {"pillow": "AVIF", "content_type": "image/avif", "ext": "avif"},
    "webp": {"pillow": "WEBP", "content_type": "image/webp", "ext": "webp"},
    "jpeg": {"pillow": "JPEG", "content_type": "image/jpeg", "ext": "jpg"},
}

DEFAULT_WIDTHS = [320, 480, 640, 768, 1024]
DEFAULT_FORMATS = ["avif", "webp", "jpeg"]
# Quality per tier and format. Each codec has its own scale: AVIF 60 looks close to JPEG 80.
DEFAULT_QUALITY_PROFILES = {
    "standard": {"avif": 60, "webp": 78, "jpeg": 80},
    "lite": {"avif": 40, "webp": 55, "jpeg": 60},
}


@dataclass
class Variant:
    """One encoded output file."""

    name: str  # for example "640w-standard.avif"
    format: str
    width: int
    height: int
    quality_tier: str
    quality_value: int
    content_type: str
    data: bytes = field(repr=False)
    encode_ms: int = 0

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class OptimizationResult:
    """Everything the handler needs to upload the variants and update the catalog."""

    version: str
    original_width: int
    original_height: int
    original_format: str
    original_bytes: int
    variants: list[Variant]
    lqip: str
    dominant_color: str
    processing_ms: int


def content_version(data: bytes, length: int = 12) -> str:
    """Content hash used as the version segment of every public URL (cache busting without invalidations)."""
    return hashlib.sha256(data).hexdigest()[:length]


def variant_name(width: int, quality_tier: str, fmt: str) -> str:
    return f"{width}w-{quality_tier}.{FORMAT_SETTINGS[fmt]['ext']}"


def _prepare(image: Image.Image) -> Image.Image:
    """Apply the EXIF orientation and normalize the color mode (metadata is not copied to the outputs)."""
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        return image.convert("RGBA")
    return image.convert("RGB")


def _encode(image: Image.Image, fmt: str, quality: int) -> bytes:
    """Encode with web oriented settings. No EXIF, XMP or GPS data is written (privacy and bytes)."""
    buffer = io.BytesIO()
    if fmt == "jpeg":
        if image.mode == "RGBA":  # JPEG has no alpha channel: flatten on white
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.getchannel("A"))
            image = background
        image.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True, subsampling="4:2:0")
    elif fmt == "webp":
        image.save(buffer, "WEBP", quality=quality, method=6)
    elif fmt == "avif":
        image.save(buffer, "AVIF", quality=quality, speed=6, subsampling="4:2:0")
    else:
        raise ValueError(f"unsupported format: {fmt}")
    return buffer.getvalue()


def build_lqip(image: Image.Image, width: int = 24) -> str:
    """Tiny blurred preview (a few hundred bytes) embedded in the catalog, rendered while the real image loads."""
    height = max(1, round(image.height * width / image.width))
    tiny = image.convert("RGB").resize((width, height), Image.Resampling.BOX)
    buffer = io.BytesIO()
    tiny.save(buffer, "WEBP", quality=30, method=6)
    return "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def dominant_color(image: Image.Image) -> str:
    red, green, blue = image.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))[:3]
    return f"#{red:02x}{green:02x}{blue:02x}"


def optimize_image(
    data: bytes,
    widths: list[int] | None = None,
    formats: list[str] | None = None,
    quality_profiles: dict[str, dict[str, int]] | None = None,
    max_workers: int = 4,
) -> OptimizationResult:
    """Resize and encode one original into all the configured variants."""
    started = time.perf_counter()
    widths = sorted(set(widths or DEFAULT_WIDTHS))
    formats = formats or DEFAULT_FORMATS
    quality_profiles = quality_profiles or DEFAULT_QUALITY_PROFILES
    if "avif" in formats and not features.check("avif"):
        raise RuntimeError("Pillow was built without AVIF support")

    with Image.open(io.BytesIO(data)) as source:
        original_format = (source.format or "unknown").lower()
        image = _prepare(source)
    original_width, original_height = image.size

    # Never upscale: widths above the original collapse into the original width
    target_widths = sorted({min(width, original_width) for width in widths})
    resized = {}
    for width in target_widths:
        height = round(original_height * width / original_width)
        resized[width] = (
            image if width == original_width
            else image.resize((width, height), Image.Resampling.LANCZOS, reducing_gap=3.0)
        )

    jobs = [
        (width, tier, fmt, values[fmt])
        for width in target_widths
        for tier, values in quality_profiles.items()
        for fmt in formats
    ]

    def run(job) -> Variant:
        width, tier, fmt, quality = job
        # Image.save() stores the encoder options on the Image object (encoderinfo), so sharing one
        # object between threads mixes the quality settings. Each job encodes its own copy.
        frame = resized[width].copy()
        job_started = time.perf_counter()
        encoded = _encode(frame, fmt, quality)
        return Variant(
            name=variant_name(width, tier, fmt),
            format=fmt,
            width=frame.width,
            height=frame.height,
            quality_tier=tier,
            quality_value=quality,
            content_type=FORMAT_SETTINGS[fmt]["content_type"],
            data=encoded,
            encode_ms=round((time.perf_counter() - job_started) * 1000),
        )

    # Pillow releases the GIL while encoding, so threads use every vCPU of the Lambda
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        variants = list(pool.map(run, jobs))

    return OptimizationResult(
        version=content_version(data),
        original_width=original_width,
        original_height=original_height,
        original_format=original_format,
        original_bytes=len(data),
        variants=variants,
        lqip=build_lqip(image),
        dominant_color=dominant_color(image),
        processing_ms=round((time.perf_counter() - started) * 1000),
    )
