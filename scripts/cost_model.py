#!/usr/bin/env python3
"""
Rufus Bank cost model: monthly cost of serving campaign pop-ups with CloudFront, WITHOUT and WITH each
optimization, for 10 M, 60 M and 100 M image requests per month, on pay-as-you-go and on flat-rate plans.

- Prices: AWS Price List API (AmazonCloudFront, read on 2026-11-20) and the CloudFront flat-rate plans page.
- Image sizes: MEASURED on the 40 demo images (outputs/e2e-report.json written by scripts/e2e_test.py),
  scaled to the 1.5 MB average original of the brief. Falls back to the values below if the report is missing.
- Output: docs/COSTS.md (tables) + docs/costs.json (raw numbers).

Usage: python scripts/cost_model.py
"""

# Built-in imports
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT = REPO_ROOT / "outputs" / "e2e-report.json"
GIB = 1024**3
MIB = 1024**2

VOLUMES = [10_000_000, 60_000_000, 100_000_000]
BASELINE_IMAGE_MB = 1.5  # brief: 1.5 MB average weight per image (MB = 1,048,576 bytes, like the Price List GB)

# ------------------------------------------------------------------ prices (USD, list, pay-as-you-go)
DTO_TIERS = {  # (upper bound in GB per month, USD per GB)
    "SA": [(10_240, 0.110), (51_200, 0.105), (153_600, 0.090), (512_000, 0.080), (1_048_576, 0.060), (5_242_880, 0.050), (float("inf"), 0.040)],
    "US": [(10_240, 0.085), (51_200, 0.080), (153_600, 0.060), (512_000, 0.040), (1_048_576, 0.030), (5_242_880, 0.025), (float("inf"), 0.020)],
}
HTTPS_PER_10K = {"SA": 0.0220, "US": 0.0100}
FUNCTIONS_PER_MILLION, FUNCTIONS_FREE = 0.10, 2_000_000
ORIGIN_SHIELD_PER_10K = 0.0075  # Origin Shield in us-east-1 (US rate)
WAF_WEB_ACL, WAF_RULE, WAF_PER_MILLION, WAF_RULES = 5.00, 1.00, 0.60, 3
EDGE_MISS_RATIO = 0.02  # 98% hit ratio at the regional caches (versioned, long TTL, normalized cache key)

FLAT_RATE_PLANS = [  # name, USD per month, requests, data transfer GB (1 TB = 1,024 GB)
    ("Business", 200, 125_000_000, 51_200),
    ("Premium", 1_000, 500_000_000, 51_200),
    ("Premium L2", 1_450, 750_000_000, 76_800),
    ("Premium L3", 2_250, 1_250_000_000, 128_000),
    ("Premium L4", 3_500, 2_000_000_000, 204_800),
    ("Premium L5", 6_000, 3_500_000_000, 358_400),
    ("Premium L6", 10_000, 6_000_000_000, 614_400),
]

# ------------------------------------------------------------------ device and network mix (assumptions)
# Physical width a phone needs for a pop-up at ~85% of the screen (360-430 CSS px x DPR 2-3)
WIDTH_MIX = {1024: 0.45, 768: 0.35, 640: 0.20}
# Format support of the app install base (AVIF: Android 12+ / iOS 16+; WebP: Android 4+ / iOS 14+)
FORMAT_MIX = {"avif": 0.85, "webp": 0.13, "jpg": 0.02}
LITE_SHARE = 0.15  # requests with Save-Data or slow networks that get the "lite" quality tier
DEVICE_CACHE_30_MIN_SAVING = 0.35  # app re-opens inside 30 minutes served by the device cache
IMMUTABLE_1_YEAR_SAVING = 0.80  # versioned URLs + 1 year immutable: download once per phone per campaign version

# Fallback measured ratios (variant bytes / original bytes) from the demo catalog
FALLBACK_RATIOS = {
    "1024w-standard.jpg": 0.105, "768w-standard.jpg": 0.068, "640w-standard.jpg": 0.050,
    "1024w-standard.avif": 0.047, "768w-standard.avif": 0.031, "640w-standard.avif": 0.023,
    "1024w-standard.webp": 0.060, "768w-standard.webp": 0.040, "640w-standard.webp": 0.030,
    "1024w-lite.avif": 0.025, "768w-lite.avif": 0.016, "640w-lite.avif": 0.012,
    "1024w-lite.webp": 0.043, "768w-lite.webp": 0.028, "640w-lite.webp": 0.022,
    "1024w-lite.jpg": 0.072, "768w-lite.jpg": 0.046, "640w-lite.jpg": 0.036,
}


def load_ratios() -> tuple[dict[str, float], str]:
    if REPORT.exists():
        metrics = json.loads(REPORT.read_text(encoding="utf-8")).get("metrics", {})
        variants = metrics.get("avg_bytes_by_variant_from_catalog")
        original = metrics.get("original_avg_bytes")
        if variants and original:
            return {name: size / original for name, size in variants.items()}, f"medido en 40 imágenes (original promedio {original / 1e6:.2f} MB)"
    return FALLBACK_RATIOS, "valores de referencia (correr make e2e para medir)"


def tiered(gb: float, region: str) -> float:
    cost, previous, remaining = 0.0, 0.0, gb
    for upper, price in DTO_TIERS[region]:
        portion = min(remaining, upper - previous)
        if portion <= 0:
            break
        cost += portion * price
        remaining -= portion
        previous = upper
    return cost


def weighted_bytes(ratios: dict[str, float], formats: dict[str, float], lite_share: float) -> float:
    """Average bytes per request for a width mix, a format mix and a share of the lite tier."""
    original = BASELINE_IMAGE_MB * MIB
    total = 0.0
    for width, width_share in WIDTH_MIX.items():
        for fmt, fmt_share in formats.items():
            standard = ratios[f"{width}w-standard.{fmt}"]
            lite = ratios.get(f"{width}w-lite.{fmt}", standard)
            ratio = (1 - lite_share) * standard + lite_share * lite
            total += width_share * fmt_share * ratio * original
    return total


def scenarios(ratios: dict[str, float]) -> list[dict]:
    original = BASELINE_IMAGE_MB * MIB
    return [
        {
            "id": "S0",
            "name": "Sin optimización",
            "detail": "PNG/JPG original de 1,5 MB, sin caché en el dispositivo: cada apertura de la app descarga de nuevo",
            "bytes": original,
            "request_factor": 1.0,
            "function": False,
        },
        {
            "id": "S1",
            "name": "+ Ancho del dispositivo (JPEG)",
            "detail": "Redimensionado a 640/768/1024w según pantalla y DPR, todavía JPEG q80",
            "bytes": weighted_bytes(ratios, {"jpg": 1.0}, 0.0),
            "request_factor": 1.0,
            "function": True,
        },
        {
            "id": "S2",
            "name": "+ AVIF / WebP por Accept",
            "detail": "CloudFront Function elige AVIF (85%), WebP (13%) o JPEG (2%) según el cliente",
            "bytes": weighted_bytes(ratios, FORMAT_MIX, 0.0),
            "request_factor": 1.0,
            "function": True,
        },
        {
            "id": "S3",
            "name": "+ Calidad adaptativa",
            "detail": "15% de las solicitudes (Save-Data, 3G) reciben el tier lite",
            "bytes": weighted_bytes(ratios, FORMAT_MIX, LITE_SHARE),
            "request_factor": 1.0,
            "function": True,
        },
        {
            "id": "S4",
            "name": "+ Caché en dispositivo 30 min",
            "detail": "Cache-Control max-age=1800 + caché de la app: 35% de las aperturas no salen del teléfono",
            "bytes": weighted_bytes(ratios, FORMAT_MIX, LITE_SHARE),
            "request_factor": 1 - DEVICE_CACHE_30_MIN_SAVING,
            "function": True,
        },
        {
            "id": "S5",
            "name": "Alternativa: URL versionada + 1 año immutable",
            "detail": "Una descarga por teléfono por versión de campaña: 80% menos solicitudes que hoy",
            "bytes": weighted_bytes(ratios, FORMAT_MIX, LITE_SHARE),
            "request_factor": 1 - IMMUTABLE_1_YEAR_SAVING,
            "function": True,
        },
    ]


def best_plan(requests: float, gb: float) -> tuple[str, int] | None:
    for name, price, max_requests, max_gb in FLAT_RATE_PLANS:
        if requests <= max_requests and gb <= max_gb:
            return name, price
    return None


def compute(volume: int, scenario: dict) -> dict:
    requests = volume * scenario["request_factor"]
    gb = requests * scenario["bytes"] / GIB
    functions = max(0.0, requests - FUNCTIONS_FREE) / 1e6 * FUNCTIONS_PER_MILLION if scenario["function"] else 0.0
    waf = WAF_WEB_ACL + WAF_RULES * WAF_RULE + requests / 1e6 * WAF_PER_MILLION
    origin_shield = requests * EDGE_MISS_RATIO / 10_000 * ORIGIN_SHIELD_PER_10K
    row = {
        "volume": volume,
        "scenario": scenario["id"],
        "requests_to_cloudfront": requests,
        "kb_per_request": scenario["bytes"] / 1024,
        "gb": gb,
        "tb": gb / 1024,
        "functions": functions,
        "waf": waf,
        "origin_shield": origin_shield,
    }
    for region in ("SA", "US"):
        transfer = tiered(gb, region)
        request_cost = requests / 10_000 * HTTPS_PER_10K[region]
        row[f"dto_{region}"] = transfer
        row[f"requests_{region}"] = request_cost
        row[f"payg_{region}"] = transfer + request_cost + functions + waf + origin_shield
    plan = best_plan(requests, gb)
    row["plan"] = plan[0] if plan else "Custom"
    row["plan_usd"] = plan[1] if plan else None
    return row


def es_number(value: float, decimals: int = 0) -> str:
    """Spanish (es-CO) number format: 1.234.567,89."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def usd(value: float | None, decimals: int = 0) -> str:
    return "consultar" if value is None else f"US$ {es_number(value, decimals)}"


def render(ratios_source: str, ratios: dict[str, float]) -> tuple[str, dict]:
    all_scenarios = scenarios(ratios)
    rows = {volume: [compute(volume, scenario) for scenario in all_scenarios] for volume in VOLUMES}
    lines = [
        "# Modelo de costos: Rufus Bank App Images Optimization",
        "",
        "> Generado por `scripts/cost_model.py` (`make costs`). Precios de lista de CloudFront tomados de la AWS Price "
        "List API el 2026-11-20 y planes flat-rate de la página oficial. Tamaños de imagen: "
        f"{ratios_source}, escalados al promedio de 1,5 MB del caso. Es un escenario, no una cotización: mide tus números reales primero.",
        "",
        "## Supuestos",
        "",
        "| Supuesto | Valor |",
        "|---|---|",
        "| Peso promedio original | 1,5 MB por imagen (1 MB = 1.048.576 bytes, 1 TB = 1.024 GB como en la Price List) |",
        f"| Mezcla de anchos | {', '.join(f'{int(share * 100)}% {width}w' for width, share in WIDTH_MIX.items())} |",
        f"| Mezcla de formatos | {', '.join(f'{int(share * 100)}% {fmt.upper()}' for fmt, share in FORMAT_MIX.items())} |",
        f"| Tier lite | {int(LITE_SHARE * 100)}% de las solicitudes (Save-Data o red lenta) |",
        f"| Caché en dispositivo 30 min | {int(DEVICE_CACHE_30_MIN_SAVING * 100)}% menos solicitudes a CloudFront |",
        f"| URL versionada + 1 año immutable | {int(IMMUTABLE_1_YEAR_SAVING * 100)}% menos solicitudes a CloudFront |",
        "| Región de entrega | Suramérica (Price Class All, POP Bogotá) y, como referencia, US/EU (Price Class 100) |",
        f"| Hit ratio regional | {int((1 - EDGE_MISS_RATIO) * 100)}% (Origin Shield cobra solo los misses) |",
        "| WAF pay-as-you-go | 1 web ACL (US$ 5) + 3 reglas (US$ 1 c/u) + US$ 0,60 por millón de solicitudes |",
        "| Formato | Cifras en USD con formato es-CO (1.234,56). Precios de lista, sin EDP/PPA ni Savings Bundle |",
        "| Free tier | No se descuenta (1 TB y 10 M solicitudes al mes por organización, normalmente ya consumidos) |",
        "",
        "## Peso por solicitud según la optimización",
        "",
        "| # | Escenario | Qué cambia | KB por solicitud | vs. original |",
        "|---|---|---|---:|---:|",
    ]
    for scenario in all_scenarios:
        kb = scenario["bytes"] / 1024
        reduction = (1 - scenario["bytes"] / (BASELINE_IMAGE_MB * MIB)) * 100
        lines.append(
            f"| {scenario['id']} | {scenario['name']} | {scenario['detail']} | {es_number(kb, 1)} | "
            f"{'-' if scenario['id'] == 'S0' else f'−{es_number(reduction, 1)}%'} |"
        )

    for volume in VOLUMES:
        label = f"{volume // 1_000_000} M"
        lines += [
            "",
            f"## {label} solicitudes de imágenes al mes",
            "",
            "| # | Escenario | Solicitudes a CloudFront | Transferencia | PAYG Suramérica | PAYG US/EU (PC100) | Mejor plan flat-rate |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
        for row, scenario in zip(rows[volume], all_scenarios):
            transfer = f"{es_number(row['tb'], 2)} TB" if row["tb"] >= 1 else f"{es_number(row['gb'])} GB"
            plan = f"{row['plan']} {usd(row['plan_usd'])}"
            lines.append(
                f"| {scenario['id']} | {scenario['name']} | {es_number(row['requests_to_cloudfront'] / 1e6, 1)} M | {transfer} | "
                f"{usd(row['payg_SA'])} | {usd(row['payg_US'])} | {plan} |"
            )

    detail = {row["scenario"]: row for row in rows[60_000_000]}
    lines += [
        "",
        "## Desglose a 60 M solicitudes (Suramérica, pay-as-you-go)",
        "",
        "| Concepto | S0 sin optimizar | S4 optimizado (30 min) | S5 optimizado (1 año) |",
        "|---|---:|---:|---:|",
    ]
    for key, label in (
        ("dto_SA", "Data transfer out (por GB, por niveles)"),
        ("requests_SA", "Solicitudes HTTPS (US$ 0,0220 por 10.000)"),
        ("functions", "CloudFront Functions (US$ 0,10 por millón, 2 M gratis)"),
        ("origin_shield", "Origin Shield (solo misses, US$ 0,0075 por 10.000)"),
        ("waf", "AWS WAF (web ACL + reglas + solicitudes)"),
        ("payg_SA", "**Total mensual**"),
    ):
        values = [detail[scenario][key] for scenario in ("S0", "S4", "S5")]
        lines.append(f"| {label} | " + " | ".join(usd(value, 2) for value in values) + " |")

    lines += [
        "",
        "## Costos que normalmente no se ven",
        "",
        "| Costo | Cuándo aparece | Cómo se evita o se controla |",
        "|---|---|---|",
        "| Data transfer en cache HIT | Siempre: el byte entregado al teléfono se cobra aunque venga del edge | Menos bytes por imagen (formato + ancho) y menos descargas (caché en el dispositivo) |",
        "| Solicitudes HTTPS en Suramérica | US$ 0,0220 por 10.000, 2,2x la tarifa de US | Caché en el dispositivo; con plan flat-rate no se cobran aparte |",
        "| Price Class | Price Class All usa el POP de Bogotá con tarifa SA (hasta 2x US en niveles altos) | Price Class 100/200 sirve desde US/EU: más barato, más latencia; en flat-rate no hay diferencia regional |",
        "| Cache busters en la URL | Tokens o timestamps cambian la URL en cada login: el teléfono vuelve a descargar | URLs estables y versionadas por hash de contenido |",
        "| Compresión Gzip/Brotli en imágenes | No reduce JPEG/PNG/WebP/AVIF y duplica entradas de caché por Accept-Encoding | Política de caché de imágenes sin compresión (como en este repo) |",
        "| Invalidaciones | 1.000 rutas gratis al mes, luego US$ 0,005 por ruta | Nombres versionados: nunca se invalida una imagen |",
        "| Lambda@Edge | US$ 0,60 por millón + cómputo, también en planes flat-rate | CloudFront Functions (US$ 0,10 por millón, incluidas en flat-rate) |",
        "| Real-time logs | US$ 0,01 por millón de líneas + Kinesis, y bloquean los planes flat-rate | Standard logs v2 a CloudWatch Logs (incluidos en flat-rate) |",
        "| Métricas adicionales de CloudFront | 8 métricas de CloudWatch por distribución, precio fijo mensual | Activarlas solo donde se necesita el CacheHitRate |",
        "| Origin Shield | Solo en Premium dentro de flat-rate; en PAYG por cada miss que llega al shield | Útil con muchos REC y orígenes costosos; con S3 y alto hit ratio es opcional |",
        "| WAF | PAYG: US$ 5 por ACL + US$ 1 por regla + US$ 0,60 por millón | Incluido en flat-rate (y obligatorio en el plan) |",
        "| Descuentos empresariales | Los planes flat-rate no se combinan con EDP/PPA, Savings Bundle ni otros descuentos | Comparar el plan contra el PAYG ya descontado de la organización |",
        "| Exceso sostenido en flat-rate | Sin cargo extra, pero la entrega puede degradarse (menos POPs o más lejanos) | Dimensionar con holgura y vigilar los avisos de 50%, 80% y 100% |",
        "| Datos móviles del cliente | No está en la factura de AWS, pero un pop-up de 1,5 MB consume el plan de datos del usuario | Las mismas optimizaciones: AVIF a 640-1024w pesa entre 2% y 5% del original |",
        "",
        "## Lectura rápida",
        "",
        f"- A 60 M solicitudes, sin optimizar se transfieren {es_number(detail['S0']['tb'], 1)} TB al mes: PAYG Suramérica "
        f"{usd(detail['S0']['payg_SA'])} y en flat-rate solo cabe en {detail['S0']['plan']} ({usd(detail['S0']['plan_usd'])}), "
        "porque Business llega hasta 50 TB.",
        f"- Con ancho correcto + AVIF/WebP + calidad adaptativa + caché de 30 min: {es_number(detail['S4']['gb'])} GB al mes, "
        f"PAYG {usd(detail['S4']['payg_SA'])} (WAF incluido) y cabe holgado en Business ({usd(200)}, WAF incluido).",
        f"- Con URL versionada + 1 año immutable el PAYG baja a {usd(detail['S5']['payg_SA'])}: por debajo de Business. "
        "Optimiza primero y decide el modelo de precio después, con tus números medidos.",
        "- El plan Business no incluye Origin Shield (solo Premium): en este repo se puede apagar con `origin_shield_enabled: false`.",
        "- Si la organización tiene descuentos PAYG (EDP/PPA), compara contra ese precio: el plan flat-rate no los suma.",
        "",
    ]
    return "\n".join(lines), {str(volume): rows[volume] for volume in VOLUMES}


def main() -> None:
    ratios, source = load_ratios()
    markdown, data = render(source, ratios)
    docs = REPO_ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "COSTS.md").write_text(markdown, encoding="utf-8")
    (docs / "costs.json").write_text(json.dumps({"ratios_source": source, "rows": data}, indent=2) + "\n", encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
