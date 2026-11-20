#!/usr/bin/env python3
"""
Generate the 40 Rufus Bank DEMO marketing pop-ups (10 per campaign) with the OpenAI Images API.

- Output: assets/images/original/campaigns/<campaign>/<image_id>.png (portrait 1024x1536, about 2 MB)
- Sidecar: assets/images/original/campaigns/<campaign>/<image_id>.json (title, subtitle, CTA, alt, prompt)
- Idempotent: existing PNG files are skipped (use --force to regenerate)
- Providers:
    openai  (default) gpt-image-2 renders the whole pop-up, text included. Reads OPENAI_API_KEY from .env.
    bedrock Amazon Bedrock (Stability AI Stable Image Ultra) renders a text-free artwork and
            scripts/popup_composer.py adds the brand, headline, subtitle and CTA with exact Spanish spelling.
            Uses your AWS credentials (boto3), region us-west-2 by default.

Usage:
    python scripts/generate_images.py                  # generate the missing images (OpenAI)
    python scripts/generate_images.py --provider bedrock
    python scripts/generate_images.py --only creditos-rufus-03 --force
    python scripts/generate_images.py --dry-run        # print prompts only
"""

# Built-in imports
import argparse
import base64
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "assets" / "images" / "original" / "campaigns"
API_URL = "https://api.openai.com/v1/images/generations"

BRAND = (
    "'Rufus Bank', a fictional, modern and friendly digital bank. Brand mark: a bold geometric letter 'R' "
    "monogram with a soft gradient next to the wordmark 'Rufus Bank'"
)

# Each image: (title, subtitle, cta, scene)
CAMPAIGNS: dict[str, dict] = {
    "telefonia-rufus": {
        "name": "Telefonía Rufus",
        "palette": "electric cyan (#00D1FF) and deep navy (#0A1A3F) palette with soft neon glows",
        "images": [
            ("5G Ilimitado", "Navega sin límites con Telefonía Rufus", "Actívalo ya",
             "Rufus, a cheerful golden retriever, wearing headphones and holding a glowing smartphone that emits 5G signal waves"),
            ("Plan Familia", "Hasta 5 líneas, una sola factura", "Únete",
             "four floating smartphones connected by glowing light trails that draw a heart around a cozy house icon"),
            ("eSIM en 1 minuto", "Activa tu línea sin salir de casa", "Pide tu eSIM",
             "a sleek smartphone with a holographic glowing eSIM chip floating above it and a small stopwatch"),
            ("Roaming sin fronteras", "Tus datos te acompañan en 120 países", "Viaja conectado",
             "a glowing globe with curved flight paths, a passport and a smartphone with full signal bars"),
            ("Recarga y gana", "Cada recarga suma Puntos Rufus", "Recarga ahora",
             "a smartphone with shiny golden coins and stars bursting out of its screen"),
            ("Equipos al 0%", "Estrena celular a 12 cuotas sin interés", "Ver equipos",
             "a premium smartphone on a glossy pedestal under a spotlight with a big floating 0% badge"),
            ("Datos que rinden", "Gigas que se acumulan mes a mes", "Ver planes",
             "a futuristic neon city skyline whose buildings are shaped like mobile signal bars"),
            ("Portabilidad fácil", "Trae tu número en 24 horas", "Cámbiate",
             "a SIM card flying from an old grey phone into a glowing new smartphone following a curved arrow"),
            ("Minutos ilimitados", "Habla todo lo que quieras", "Conoce más",
             "a stylish retro telephone transforming into a modern smartphone surrounded by colorful speech bubbles"),
            ("Fibra Rufus Hogar", "Internet de 900 Mbps para tu casa", "Instálala",
             "a modern house with glowing fiber optic light streams entering through the roof and a wifi icon"),
        ],
    },
    "creditos-rufus": {
        "name": "Créditos Rufus",
        "palette": "warm amber gold (#FFB020) and deep navy (#0A1A3F) palette, elegant and trustworthy",
        "images": [
            ("Tu casa propia", "Financiamos hasta el 70% de tu vivienda", "Simula tu crédito",
             "a beautiful modern house with a giant golden key in front and Rufus, a happy golden retriever, sitting at the door"),
            ("Crédito de vehículo", "Estrena carro con cuotas a tu medida", "Cotiza ya",
             "a shiny electric car with a big golden ribbon bow in a bright showroom"),
            ("Estudia sin límites", "Crédito educativo para tu futuro", "Solicítalo",
             "a graduation cap on top of a stack of books with glowing steps leading up to a star"),
            ("Impulsa tu negocio", "Capital de trabajo para emprendedores", "Hablemos",
             "a charming small coffee shop storefront with a rising golden growth chart behind it"),
            ("Libre inversión", "Hasta $50 millones para tus planes", "Pídelo hoy",
             "a hot air balloon lifting gift boxes, a suitcase and a guitar into a golden sunset sky"),
            ("Tasa preferencial", "Tasas que se ajustan a ti", "Ver tasas",
             "a large glossy golden percentage symbol with a downward arrow and sparkles"),
            ("Compra de cartera", "Une tus deudas en una sola cuota", "Unifícalas",
             "several colorful credit cards merging into a single premium golden card"),
            ("Remodela tu hogar", "Dale un nuevo aire a tu casa", "Conoce más",
             "a bright renovated living room with a paint roller, plants and tools floating around"),
            ("Crédito rotativo", "Dinero disponible cuando lo necesites", "Actívalo",
             "glowing circular arrows with golden coins orbiting around them"),
            ("Aprobado en minutos", "Respuesta 100% digital desde la app", "Empieza ya",
             "a smartphone showing a large check mark with a stopwatch and golden confetti"),
        ],
    },
    "cryptomonedas-rufus": {
        "name": "CryptoMonedas Rufus",
        "palette": "neon violet (#8B5CF6), magenta (#EC4899) and near black (#0B0820) palette, futuristic",
        "images": [
            ("Bitcoin en tu app", "Compra y vende desde $20.000", "Empieza",
             "a glowing golden bitcoin coin floating inside a futuristic vault with violet neon light"),
            ("Ethereum y más", "Más de 20 criptomonedas disponibles", "Explorar",
             "a floating translucent crystal diamond token surrounded by smaller orbiting crypto tokens"),
            ("Wallet Rufus", "Tus criptoactivos protegidos 24/7", "Crea tu wallet",
             "a digital wallet protected by a glowing shield and padlock with circuit patterns"),
            ("Staking Rufus", "Pon a trabajar tus criptomonedas", "Ver rendimientos",
             "stacks of glowing crypto coins growing like towers with upward arrows"),
            ("Alertas de precio", "Entérate primero de cada movimiento", "Activa alertas",
             "a smartphone with a neon candlestick chart and a ringing notification bell"),
            ("Stablecoins USD", "Ahorra en dólares digitales", "Conócelas",
             "a dollar sign coin made of digital grid light floating over a calm violet ocean"),
            ("Academia Cripto", "Aprende antes de invertir", "Aprende gratis",
             "a holographic open book projecting a glowing blockchain network"),
            ("Trading 24/7", "El mercado nunca duerme", "Opera ahora",
             "a futuristic city at night with neon trading charts in the sky and Rufus, a golden retriever, wearing a VR headset"),
            ("Envíos cripto", "Envía valor al mundo en segundos", "Envía ya",
             "glowing coins flying along light trails across a stylized globe"),
            ("Alto riesgo, alta emoción", "Invierte solo lo que estés dispuesto a perder", "Conoce los riesgos",
             "a neon rollercoaster track shaped like a volatile price chart with a small cart"),
        ],
    },
    "rufus-bolsillos-rentables": {
        "name": "Rufus Bolsillos Rentables",
        "palette": "fresh mint green (#10B981), emerald, white and soft cream palette, optimistic and calm",
        "images": [
            ("Bolsillos que crecen", "Tu ahorro genera rentabilidad diaria", "Crea tu bolsillo",
             "glass jars shaped like pockets with small plants growing golden coins"),
            ("Meta: viaje soñado", "Separa tu plata para ese viaje", "Crear meta",
             "a cute piggy bank wearing sunglasses next to a suitcase and a paper airplane"),
            ("Rentabilidad diaria", "Ganas intereses todos los días", "Ver tasa",
             "a calendar whose days sprout green leaves and coins"),
            ("Ahorro automático", "Programa y olvídate", "Prográmalo",
             "friendly gears and a conveyor belt moving coins into a green pocket"),
            ("Fondo de emergencias", "Tranquilidad para lo inesperado", "Empieza hoy",
             "a green umbrella protecting a pile of coins from a small rain cloud"),
            ("Bolsillo Navidad", "Ahorra hoy para regalar en diciembre", "Crear bolsillo",
             "a festive green pocket overflowing with wrapped gifts, snow and warm lights"),
            ("Redondeo inteligente", "Cada compra suma a tu ahorro", "Actívalo",
             "coins rounding up from a shopping receipt and dropping into a pocket"),
            ("Cero cuota de manejo", "Tus bolsillos no te cobran", "Conoce más",
             "a happy smiling wallet with a big 0 badge and confetti"),
            ("Ahorra con Rufus", "Tu mejor amigo para ahorrar", "Empieza",
             "Rufus, a cheerful golden retriever, hugging a big mint green piggy bank"),
            ("Siempre disponible", "Retira tu plata cuando quieras, 24/7", "Ver más",
             "an open green pocket with a glowing clock showing 24/7 and a set of keys"),
        ],
    },
}


def load_env(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines), so the script needs no extra dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_prompt(campaign_name: str, palette: str, title: str, subtitle: str, cta: str, scene: str) -> str:
    """Build a consistent art direction for every pop-up of the brand."""
    return (
        f"Vertical 2:3 mobile app pop-up banner for {BRAND}. "
        f"Campaign: '{campaign_name}'. Scene: {scene}. "
        f"Art direction: premium glossy 3D render, soft studio lighting, subtle depth of field, {palette}, "
        "clean and modern composition with generous negative space, high-end marketing quality. "
        f"Layout: the 'Rufus Bank' brand mark at the top center; a small campaign label '{campaign_name.upper()}'; "
        f"a big bold headline '{title}'; one short subtitle '{subtitle}'; a rounded call to action button that reads "
        f"'{cta}' at the bottom; a small close (X) icon in the top right corner like an in-app pop-up. "
        "All text in Spanish, spelled exactly as given including accents. No other text. "
        "No real brands, no real logos, no real people."
    )


BEDROCK_MODEL_ID = "stability.stable-image-ultra-v1:1"
BEDROCK_NEGATIVE_PROMPT = (
    "text, letters, words, typography, numbers, watermark, logo, signature, caption, user interface, app screen, "
    "menu, labels, blurry, low quality, distorted, deformed"
)
# Scenes with screens or written elements are replaced for text-free artwork models (they draw fake UI text)
BEDROCK_SCENE_OVERRIDES = {
    "creditos-rufus-10": "a glossy golden check mark symbol next to a classic golden stopwatch with golden confetti",
    "cryptomonedas-rufus-05": "a glowing neon candlestick chart sculpture next to a ringing golden notification bell",
    "rufus-bolsillos-rentables-03": "an elegant hourglass with green leaves and golden coins growing inside it",
    "rufus-bolsillos-rentables-07": "golden coins jumping from a shopping bag into a soft mint green pocket",
}
# Scene details that depend on written characters are simplified for text-free artwork
BEDROCK_SCENE_REPLACEMENTS = {
    "a big 0 badge": "a shiny round badge",
    "a big floating 0% badge": "a floating glossy badge",
    "a glowing clock showing 24/7": "a glowing round clock",
    "a dollar sign coin": "a glowing coin",
}


def build_artwork_prompt(scene: str, palette: str) -> str:
    """Text-free artwork prompt (the composer adds every piece of text afterwards)."""
    for source, target in BEDROCK_SCENE_REPLACEMENTS.items():
        scene = scene.replace(source, target)
    return (
        f"{scene}. Hero artwork for a mobile app marketing pop-up of a fictional modern digital bank. "
        f"Premium glossy 3D render, soft studio lighting, subtle depth of field, {palette}, "
        "single hero subject centered with breathing room around it, high-end marketing quality, no text."
    )


def call_bedrock(prompt: str, region: str) -> bytes:
    """Amazon Bedrock Stable Image Ultra, 3:2 landscape PNG (about 1216x832) for the framed hero artwork."""
    import boto3  # dev dependency, only needed for this provider

    client = boto3.client("bedrock-runtime", region_name=region)
    response = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(
            {
                "prompt": prompt,
                "negative_prompt": BEDROCK_NEGATIVE_PROMPT,
                "aspect_ratio": "3:2",
                "output_format": "png",
            }
        ),
    )
    body = json.loads(response["body"].read())
    return base64.b64decode(body["images"][0])


def iter_jobs():
    """Yield one job per image: (campaign_id, image_id, metadata)."""
    for campaign_id, campaign in CAMPAIGNS.items():
        for index, (title, subtitle, cta, scene) in enumerate(campaign["images"], start=1):
            image_id = f"{campaign_id}-{index:02d}"
            yield campaign_id, image_id, {
                "campaign": campaign_id,
                "campaign_name": campaign["name"],
                "image_id": image_id,
                "title": title,
                "subtitle": subtitle,
                "cta": cta,
                "alt": f"Pop-up de {campaign['name']}: {title}. {subtitle}.",
                "prompt": build_prompt(campaign["name"], campaign["palette"], title, subtitle, cta, scene),
                "_scene": scene,
                "_palette": campaign["palette"],
            }


def call_openai(prompt: str, model: str, quality: str, size: str, api_key: str, attempts: int = 6) -> bytes:
    """Call the Images API with retries (429 and 5xx), returning the PNG bytes."""
    payload = json.dumps(
        {"model": model, "prompt": prompt, "size": size, "quality": quality, "output_format": "png", "n": 1}
    ).encode("utf-8")
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            API_URL,
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=420) as response:
                body = json.loads(response.read())
            return base64.b64decode(body["data"][0]["b64_json"])
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            if error.code in (429, 500, 502, 503, 504) and attempt < attempts:
                wait = min(90, 2**attempt + random.random() * 3)
                print(f"   retry {attempt}/{attempts} after HTTP {error.code} ({wait:.0f}s): {detail}", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"OpenAI HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt < attempts:
                time.sleep(min(60, 2**attempt))
                continue
            raise RuntimeError(f"OpenAI network error: {error}") from error
    raise RuntimeError("unreachable")


def generate_one(job, provider: str, model: str, quality: str, size: str, api_key: str, force: bool, region: str):
    """Generate (or skip) one image and write its sidecar metadata."""
    campaign_id, image_id, metadata = job
    metadata = dict(metadata)
    scene, palette = metadata.pop("_scene"), metadata.pop("_palette")
    folder = OUTPUT_DIR / campaign_id
    folder.mkdir(parents=True, exist_ok=True)
    png_path = folder / f"{image_id}.png"
    json_path = folder / f"{image_id}.json"

    started = time.time()
    if force or not png_path.exists():
        if provider == "openai":
            png_path.write_bytes(call_openai(metadata["prompt"], model, quality, size, api_key))
            metadata["generator"] = {"provider": "openai", "model": model, "quality": quality, "size": size}
        else:
            import io

            from PIL import Image

            from popup_composer import compose_popup

            artwork_prompt = build_artwork_prompt(BEDROCK_SCENE_OVERRIDES.get(image_id, scene), palette)
            artwork = Image.open(io.BytesIO(call_bedrock(artwork_prompt, region)))
            popup = compose_popup(
                artwork, campaign_id, metadata["campaign_name"], metadata["title"], metadata["subtitle"], metadata["cta"]
            )
            # Low PNG compression, like a design tool export (heavy originals are the problem we solve)
            popup.save(png_path, "PNG", compress_level=1)
            metadata["prompt"] = artwork_prompt
            metadata["generator"] = {
                "provider": "amazon-bedrock",
                "model": BEDROCK_MODEL_ID,
                "composition": "scripts/popup_composer.py (Pillow text overlay)",
                "size": "1024x1536",
            }
    elif json_path.exists():
        # Keep the generator recorded when the image was created
        previous = json.loads(json_path.read_text(encoding="utf-8"))
        metadata["generator"] = previous.get("generator", {})
        metadata["prompt"] = previous.get("prompt", metadata["prompt"])
    json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return image_id, png_path.stat().st_size, time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="generate a single image_id (for example telefonia-rufus-03)")
    parser.add_argument("--force", action="store_true", help="regenerate even if the PNG already exists")
    parser.add_argument("--dry-run", action="store_true", help="print the prompts and exit")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--size", default="1024x1536")
    parser.add_argument("--provider", choices=["openai", "bedrock"], default="openai")
    parser.add_argument("--region", default="us-west-2", help="Amazon Bedrock region (provider bedrock)")
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
    quality = os.environ.get("OPENAI_IMAGE_QUALITY", "high")
    api_key = os.environ.get("OPENAI_API_KEY", "")

    jobs = [job for job in iter_jobs() if not args.only or job[1] == args.only]
    if args.dry_run:
        for _, image_id, metadata in jobs:
            print(f"{image_id}: {metadata['prompt']}\n")
        return 0
    if args.provider == "openai" and (not api_key or "REPLACE_ME" in api_key):
        print("ERROR: set OPENAI_API_KEY in .env (see .example.env)", file=sys.stderr)
        return 1
    if args.provider == "bedrock":
        model = BEDROCK_MODEL_ID
        sys.path.insert(0, str(Path(__file__).resolve().parent))

    print(f"--> Generating {len(jobs)} images with provider={args.provider} model={model} size={size_label(args.size)}")
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(generate_one, job, args.provider, model, quality, args.size, api_key, args.force, args.region): job
            for job in jobs
        }
        for future in as_completed(futures):
            image_id = futures[future][1]
            try:
                _, size_bytes, seconds = future.result()
                print(f"OK   {image_id:<32} {size_bytes / 1_000_000:5.2f} MB  {seconds:5.1f}s", flush=True)
            except Exception as error:  # noqa: BLE001 (report and continue with the rest)
                failures += 1
                print(f"FAIL {image_id:<32} {error}", flush=True)

    total = sum(p.stat().st_size for p in OUTPUT_DIR.rglob("*.png"))
    count = len(list(OUTPUT_DIR.rglob("*.png")))
    print(f"--> Done: {count} PNG files, {total / 1_000_000:.1f} MB total, average {total / max(count, 1) / 1_000_000:.2f} MB")
    return 1 if failures else 0


def size_label(size: str) -> str:
    return size.replace("x", " x ")


if __name__ == "__main__":
    sys.exit(main())
