"""
Compose a Rufus Bank in-app pop-up (1024x1536) from a text-free artwork: brand mark, close icon,
campaign label, headline, subtitle and call to action, with exact Spanish spelling (accents included).

Used by scripts/generate_images.py --provider bedrock (image models that do not render text reliably).
"""

# Built-in imports
from pathlib import Path

# External imports
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1024, 1536

FONT_CANDIDATES = [
    ("/System/Library/Fonts/Avenir Next.ttc", {"heavy": 8, "bold": 0, "demi": 2, "medium": 5}),
    ("/System/Library/Fonts/HelveticaNeue.ttc", {"heavy": 9, "bold": 1, "demi": 1, "medium": 10}),
]

THEMES = {
    "creditos-rufus": {"accent": (255, 176, 32), "accent_2": (255, 209, 102), "base": (10, 26, 63), "cta_text": (10, 26, 63)},
    "cryptomonedas-rufus": {"accent": (139, 92, 246), "accent_2": (236, 72, 153), "base": (11, 8, 32), "cta_text": (255, 255, 255)},
    "rufus-bolsillos-rentables": {"accent": (16, 185, 129), "accent_2": (110, 231, 183), "base": (4, 47, 35), "cta_text": (4, 47, 35)},
    "telefonia-rufus": {"accent": (0, 209, 255), "accent_2": (125, 232, 255), "base": (10, 26, 63), "cta_text": (10, 26, 63)},
}


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path, indexes in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size, index=indexes[weight])
    return ImageFont.load_default(size=size)


def _cover(image: Image.Image) -> Image.Image:
    """Resize and center crop the artwork to exactly 1024x1536."""
    scale = max(WIDTH / image.width, HEIGHT / image.height)
    resized = image.convert("RGB").resize(
        (round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS
    )
    left = (resized.width - WIDTH) // 2
    top = (resized.height - HEIGHT) // 2
    return resized.crop((left, top, left + WIDTH, top + HEIGHT))


def _vertical_gradient(color: tuple, start_y: int, end_y: int, start_alpha: int, end_alpha: int) -> Image.Image:
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    span = max(1, end_y - start_y)
    for y in range(min(start_y, end_y), max(start_y, end_y) + 1):
        progress = (y - start_y) / span
        alpha = round(start_alpha + (end_alpha - start_alpha) * max(0.0, min(1.0, progress)))
        draw.line([(0, y), (WIDTH, y)], fill=(*color, alpha))
    return layer


def _horizontal_gradient(size: tuple, left: tuple, right: tuple) -> Image.Image:
    width, height = size
    gradient = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(gradient)
    for x in range(width):
        t = x / max(1, width - 1)
        draw.line([(x, 0), (x, height)], fill=tuple(round(a + (b - a) * t) for a, b in zip(left, right)))
    return gradient


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _centered(draw, y: int, text: str, font, fill, shadow: tuple | None = None) -> int:
    width = draw.textlength(text, font=font)
    x = (WIDTH - width) / 2
    if shadow:
        draw.text((x + 3, y + 4), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)
    bbox = font.getbbox(text)
    return bbox[3] - bbox[1]


def _rounded_mask(size: tuple, radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return mask


def _cover_to(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / image.width, height / image.height)
    resized = image.convert("RGB").resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    left, top = (resized.width - width) // 2, (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def compose_popup(artwork: Image.Image, campaign: str, campaign_name: str, title: str, subtitle: str, cta: str) -> Image.Image:
    """Modern in-app pop-up: blurred artwork backdrop, framed hero artwork, brand, texts and CTA."""
    theme = THEMES[campaign]
    accent, accent_2, base = theme["accent"], theme["accent_2"], theme["base"]

    # 1) Backdrop: the same artwork, blurred and tinted with the campaign base color
    backdrop = _cover_to(artwork, WIDTH, HEIGHT).filter(ImageFilter.GaussianBlur(48))
    backdrop = Image.blend(backdrop, Image.new("RGB", (WIDTH, HEIGHT), base), 0.72).convert("RGBA")
    backdrop = Image.alpha_composite(backdrop, _vertical_gradient(base, 0, 520, 200, 0))
    canvas = Image.alpha_composite(backdrop, _vertical_gradient(base, 1150, HEIGHT, 0, 230))

    # 2) Hero artwork in a rounded frame with an accent glow
    hero_box = (72, 548, 952, 1176)
    hero_w, hero_h = hero_box[2] - hero_box[0], hero_box[3] - hero_box[1]
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        [hero_box[0] - 6, hero_box[1] - 6, hero_box[2] + 6, hero_box[3] + 6], radius=52, fill=(*accent, 150)
    )
    canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(26)))
    hero = _cover_to(artwork, hero_w, hero_h)
    canvas.paste(hero, hero_box[:2], _rounded_mask((hero_w, hero_h), 44))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(hero_box, radius=44, outline=(*accent_2, 210), width=3)

    # 3) Brand mark: gradient rounded square with the R monogram + wordmark
    monogram_size, brand_y = 76, 58
    word_font, bank_font, mono_font = _font("bold", 50), _font("demi", 28), _font("heavy", 54)
    group_width = monogram_size + 18 + max(draw.textlength("Rufus", font=word_font), draw.textlength("Bank", font=bank_font))
    start_x = round((WIDTH - group_width) / 2)
    canvas.paste(
        _horizontal_gradient((monogram_size, monogram_size), accent, accent_2),
        (start_x, brand_y),
        _rounded_mask((monogram_size, monogram_size), 20),
    )
    draw = ImageDraw.Draw(canvas)
    r_width = draw.textlength("R", font=mono_font)
    draw.text((start_x + (monogram_size - r_width) / 2, brand_y + 2), "R", font=mono_font, fill=base)
    draw.text((start_x + monogram_size + 18, brand_y - 8), "Rufus", font=word_font, fill=(255, 255, 255))
    draw.text((start_x + monogram_size + 20, brand_y + 46), "Bank", font=bank_font, fill=accent_2)

    # 4) Close icon (in-app pop-up affordance)
    cx, cy, radius = 948, 86, 34
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(255, 255, 255, 150), width=3, fill=(0, 0, 0, 70))
    draw.line([(cx - 12, cy - 12), (cx + 12, cy + 12)], fill=(255, 255, 255), width=4)
    draw.line([(cx - 12, cy + 12), (cx + 12, cy - 12)], fill=(255, 255, 255), width=4)

    # 5) Campaign label (manual letter spacing) with side rules
    label_font = _font("demi", 27)
    label = campaign_name.upper()
    tracking = 6
    label_width = sum(draw.textlength(char, font=label_font) for char in label) + tracking * (len(label) - 1)
    label_x, label_y = (WIDTH - label_width) / 2, 196
    for char in label:
        draw.text((label_x, label_y), char, font=label_font, fill=accent_2)
        label_x += draw.textlength(char, font=label_font) + tracking
    rule_y, rule_len = label_y + 18, max(30, min(90, (WIDTH - label_width) / 2 - 60))
    left_edge, right_edge = (WIDTH - label_width) / 2, (WIDTH + label_width) / 2
    draw.line([(left_edge - 22 - rule_len, rule_y), (left_edge - 22, rule_y)], fill=accent, width=3)
    draw.line([(right_edge + 22, rule_y), (right_edge + 22 + rule_len, rule_y)], fill=accent, width=3)

    # 6) Headline (auto-fit: up to 2 lines between the label and the hero frame)
    size = 104
    while True:
        headline_font = _font("heavy", size)
        lines = _wrap(draw, title.upper(), headline_font, 880)
        if len(lines) <= 2 or size <= 60:
            break
        size -= 6
    line_height = round(size * 1.06)
    block_height = line_height * len(lines)
    y = 262 + max(0, (2 * round(104 * 1.06) - block_height) // 2)
    text_glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(text_glow)
    for index, line in enumerate(lines):
        _centered(glow_draw, y + index * line_height, line, headline_font, (*accent, 230))
    canvas = Image.alpha_composite(canvas, text_glow.filter(ImageFilter.GaussianBlur(16)))
    draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(lines):
        _centered(draw, y + index * line_height, line, headline_font, (255, 255, 255), shadow=(0, 0, 0, 90))

    # 7) Subtitle
    subtitle_font = _font("medium", 40)
    y = 1212
    for line in _wrap(draw, subtitle, subtitle_font, 860)[:2]:
        _centered(draw, y, line, subtitle_font, (255, 255, 255, 240))
        y += 52

    # 8) Call to action pill with chevron
    cta_font = _font("heavy", 46)
    pill_w, pill_h = 620, 112
    pill_x, pill_y = (WIDTH - pill_w) // 2, 1360
    canvas.paste(_horizontal_gradient((pill_w, pill_h), accent, accent_2), (pill_x, pill_y), _rounded_mask((pill_w, pill_h), pill_h // 2))
    draw = ImageDraw.Draw(canvas)
    cta_text = cta.upper()
    text_w = draw.textlength(cta_text, font=cta_font)
    draw.text((pill_x + (pill_w - 90 - text_w) / 2 + 20, pill_y + 26), cta_text, font=cta_font, fill=theme["cta_text"])
    chevron_cx, chevron_cy, chevron_r = pill_x + pill_w - 64, pill_y + pill_h // 2, 34
    draw.ellipse([chevron_cx - chevron_r, chevron_cy - chevron_r, chevron_cx + chevron_r, chevron_cy + chevron_r], fill=base)
    draw.line(
        [(chevron_cx - 7, chevron_cy - 14), (chevron_cx + 9, chevron_cy), (chevron_cx - 7, chevron_cy + 14)],
        fill=accent_2, width=6, joint="curve",
    )
    return canvas.convert("RGB")
