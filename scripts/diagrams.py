#!/usr/bin/env python3
"""
Generate the draw.io diagrams of the repository (house style of the diagram-generator skill):
- assets/architecture.drawio   AWS architecture of Rufus Bank App Images Optimization
- assets/cache-layers.drawio   the cache layers an image goes through (device -> edge -> REC -> shield -> S3)

Render with:  "/Applications/draw.io.app/Contents/MacOS/draw.io" -x -f png -s 4.17 -b 15 -o assets/<name>.png assets/<name>.drawio
"""

# Built-in imports
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"

POINTS = (
    "points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],[0,1,0],[0.25,1,0],[0.5,1,0],[0.75,1,0],[1,1,0],"
    "[0,0.25,0],[0,0.5,0],[0,0.75,0],[1,0.25,0],[1,0.5,0],[1,0.75,0]];"
)
COLORS = {
    "networking": "#8C4FFF",
    "compute": "#ED7100",
    "integration": "#E7157B",
    "database": "#C925D1",
    "storage": "#7AA116",
    "security": "#DD344C",
    "management": "#E7157B",
}
GROUPS = {
    "aws": ("#ffe6cc", "#d79b00", 3),
    "green": ("#d5e8d4", "#82b366", 6),
    "purple": ("#e1d5e7", "#9673a6", 6),
    "blue": ("#dae8fc", "#6c8ebf", 6),
    "red": ("#f8cecc", "#b85450", 6),
}
TEXT = "text;html=1;align=center;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;"


class Diagram:
    def __init__(self, name: str, width: int, height: int):
        self.name = name
        self.width = width
        self.height = height
        self.cells: list[str] = []
        self.counter = 0

    def _id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter}"

    def _vertex(self, style: str, x: float, y: float, w: float, h: float, value: str = "", cell_id: str | None = None) -> str:
        cell_id = cell_id or self._id("v")
        self.cells.append(
            f'<mxCell id="{cell_id}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        return cell_id

    def title(self, text: str, x: float, y: float, w: float = 900):
        self._vertex(TEXT + "fontSize=18;fontStyle=1;fontColor=#232F3E;", x, y, w, 30, text)

    def group(self, kind: str, x: float, y: float, w: float, h: float, label: str, label_w: float = 220):
        fill, stroke, arc = GROUPS[kind]
        self._vertex(f"rounded=1;whiteSpace=wrap;html=1;arcSize={arc};fillColor={fill};strokeColor={stroke};", x, y, w, h)
        self._vertex(TEXT + "fontSize=14;fontStyle=1;align=left;", x + 12, y + 4, label_w, 26, label)

    def icon(self, domain: str, res_icon: str, x: float, y: float, label: str, label_w: float = 150, size: int = 78) -> str:
        cell_id = self._vertex(
            "sketch=0;" + POINTS + f"outlineConnect=0;fontColor=#232F3E;fillColor={COLORS[domain]};strokeColor=#ffffff;"
            "dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=12;fontStyle=0;"
            f"aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res_icon};",
            x,
            y,
            size,
            size,
        )
        self.label(x + size / 2 - label_w / 2, y + size + 2, label, label_w)
        return cell_id

    def label(self, x: float, y: float, text: str, w: float = 150, size: int = 12, bold: bool = False, align: str = "center"):
        style = TEXT + f"fontSize={size};" + ("fontStyle=1;" if bold else "")
        if align != "center":
            style = style.replace("align=center;", f"align={align};").replace("autosize=1;", "autosize=0;")
        self._vertex(style, x, y, w, 20 * (text.count("\n") + 1), text.replace("\n", "<br>"))

    def note(self, x: float, y: float, text: str, w: float = 140):
        """Red bold flow annotation (separate text cell, never an edge label)."""
        self._vertex(TEXT + "fontColor=#FF0000;fontSize=12;fontStyle=1;", x, y, w, 20 * (text.count("\n") + 1), text.replace("\n", "<br>"))

    def actor(self, x: float, y: float, label: str) -> str:
        cell_id = self._vertex("shape=actor;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;", x, y, 40, 60)
        self.label(x - 25, y + 62, label, 90)
        return cell_id

    def browser(self, x: float, y: float, label: str) -> str:
        cell_id = self._vertex(
            "image;aspect=fixed;html=1;points=[];align=center;fontSize=12;image=img/lib/azure2/general/Browser.svg;",
            x,
            y,
            77.5,
            62,
        )
        self.label(x + 38.75 - 60, y + 64, label, 120)
        return cell_id

    def edge(self, source: str, target: str, exit_xy: tuple, entry_xy: tuple, points: list[tuple] | None = None, dashed: bool = False):
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
            f"exitX={exit_xy[0]};exitY={exit_xy[1]};exitDx=0;exitDy=0;entryX={entry_xy[0]};entryY={entry_xy[1]};entryDx=0;entryDy=0;"
            + ("dashed=1;" if dashed else "")
        )
        geometry = '<mxGeometry relative="1" as="geometry">'
        if points:
            geometry += '<Array as="points">' + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points) + "</Array>"
        geometry += "</mxGeometry>"
        self.cells.append(
            f'<mxCell id="{self._id("e")}" style="{style}" edge="1" parent="1" source="{source}" target="{target}">{geometry}</mxCell>'
        )

    def save(self) -> Path:
        ASSETS.mkdir(exist_ok=True)
        xml = (
            '<mxfile host="app.diagrams.net" agent="Rufus Bank diagrams.py">'
            f'<diagram name="{self.name}" id="{self.name}">'
            f'<mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
            f'page="1" pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0"><root>'
            '<mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(self.cells) + "</root></mxGraphModel></diagram></mxfile>\n"
        )
        path = ASSETS / f"{self.name}.drawio"
        path.write_text(xml, encoding="utf-8")
        return path


def architecture() -> Path:
    d = Diagram("architecture", 1560, 880)
    d.title("Rufus Bank App Images Optimization · Arquitectura AWS (us-east-1)", 330, 14, 900)

    # Containers first (z-order)
    d.group("aws", 215, 60, 1265, 780, "AWS Cloud · us-east-1", 200)
    d.group("green", 245, 100, 495, 205, "Portal web (S3 + CloudFront)", 260)
    d.group("red", 780, 100, 670, 205, "Autenticación y API", 220)
    d.group("purple", 245, 350, 495, 215, "CDN de imágenes", 200)
    d.group("blue", 780, 350, 430, 450, "Pipeline de optimización", 230)

    user = d.actor(40, 300, "Usuario")
    browser = d.browser(100, 300, "Portal web\no app móvil")

    # Row 1: portal and API
    cf_web = d.icon("networking", "cloudfront", 275, 170, "CloudFront web\n/ y /api/*", 130)
    spa_fn = d.icon("networking", "cloudfront_functions", 445, 170, "Function\nspa-rewrite", 120)
    s3_web = d.icon("storage", "s3", 615, 170, "S3 frontend\n(privado, OAC)", 120)
    cognito = d.icon("security", "cognito", 810, 170, "Cognito User Pool\n(sin self sign-up)", 140)
    api = d.icon("integration", "api_gateway", 980, 170, "API Gateway\nHTTP API + JWT", 130)
    profile = d.icon("compute", "lambda", 1150, 170, "Lambda\nprofile-api", 110)
    users = d.icon("database", "dynamodb", 1320, 170, "DynamoDB users\n(PK user_email)", 130)

    # Row 2: images CDN and pipeline
    cf_img = d.icon("networking", "cloudfront", 275, 420, "CloudFront imágenes\nHTTP/3 · Origin Shield", 160)
    neg_fn = d.icon("networking", "cloudfront_functions", 445, 420, "Function\nancho·formato·calidad", 150)
    s3_opt = d.icon("storage", "s3", 615, 420, "S3 optimized\n(privado, OAC)", 120)
    optimizer = d.icon("compute", "lambda", 850, 420, "Lambda optimizer\nPillow · arm64", 130)
    catalog = d.icon("database", "dynamodb", 1071, 420, "DynamoDB catalog\n(versión, LQIP)", 130)
    s3_orig = d.icon("storage", "s3", 850, 660, "S3 original\n(privado, versionado)", 140)
    cdk = d.icon("management", "cloud_development_kit", 1071, 660, "CDK BucketDeployment\nassets/images (40 PNG)", 170)

    # Legend: security and observability
    d.label(245, 610, "Seguridad y observabilidad", 260, 14, True)
    d.icon("security", "waf", 265, 650, "AWS WAF\n(ambas distribuciones)", 140)
    d.icon("security", "secrets_manager", 385, 650, "Secrets Manager\n(clave demo)", 120)
    d.icon("management", "cloudwatch_2", 505, 650, "CloudWatch\nlogs v2 · métricas", 120)
    d.icon("integration", "sqs", 625, 650, "SQS DLQ\noptimizer", 110)

    # Edges
    d.edge(user, browser, (1, 0.5), (0, 0.5))
    d.edge(browser, cf_web, (1, 0.2), (0, 0.5), [(225, 312.4), (225, 209)])
    d.edge(browser, cognito, (1, 0.5), (0, 0.5), [(760, 331), (760, 209)])
    d.edge(browser, cf_img, (1, 0.8), (0, 0.5), [(225, 349.6), (225, 459)])
    d.edge(cf_web, spa_fn, (1, 0.5), (0, 0.5))
    d.edge(spa_fn, s3_web, (1, 0.5), (0, 0.5))
    d.edge(cf_web, api, (0.5, 0), (0.5, 0), [(314, 145), (1019, 145)])
    d.edge(api, profile, (1, 0.5), (0, 0.5))
    d.edge(profile, users, (1, 0.5), (0, 0.5))
    d.edge(profile, catalog, (0, 0.8), (0.5, 0), [(1110, 232.4)])
    d.edge(cf_img, neg_fn, (1, 0.5), (0, 0.5))
    d.edge(neg_fn, s3_opt, (1, 0.5), (0, 0.5))
    d.edge(optimizer, s3_opt, (0, 0.3), (1, 0.3))
    d.edge(optimizer, catalog, (1, 0.5), (0, 0.5))
    d.edge(s3_orig, optimizer, (0, 0.5), (0, 0.75), [(798, 699), (798, 478.5)])
    d.edge(cdk, s3_orig, (0, 0.5), (1, 0.5))

    # Red flow annotations
    d.note(530, 120, "/api/* sin caché", 120)
    d.note(522, 186, "OAC", 40)
    d.note(560, 312, "SRP → JWT", 90)
    d.note(1058, 186, "JWT", 40)
    d.note(1118, 308, "segmentación\npor riesgo", 100)
    d.note(330, 388, "?w=640 + Accept", 120)
    d.note(522, 436, "OAC", 40)
    d.note(782, 388, "30\nvariantes", 66)
    d.note(940, 436, "upsert", 60)
    d.note(806, 580, "S3 event", 70)
    d.note(952, 676, "40 PNG", 60)
    return d.save()


def cache_layers() -> Path:
    d = Diagram("cache-layers", 1340, 620)
    d.title("Rufus Bank · Capas de caché de una imagen de campaña", 290, 14, 760)

    d.group("green", 30, 70, 240, 330, "Dispositivo", 140)
    d.group("purple", 300, 70, 690, 330, "Amazon CloudFront", 200)
    d.group("blue", 1020, 70, 280, 330, "Origen", 120)

    phone = d.browser(110, 163, "App o navegador\ncaché local 30 min")
    pop = d.icon("networking", "cloudfront", 345, 155, "Edge POP Bogotá\n(BOG) + Function", 150)
    rec = d.icon("networking", "cloudfront", 575, 155, "Regional Edge Cache\nSão Paulo (GRU)", 150)
    shield = d.icon("networking", "cloudfront", 800, 155, "Origin Shield\nus-east-1", 130)
    s3 = d.icon("storage", "s3", 1120, 155, "S3 optimized\n(privado, OAC)", 130)

    d.edge(phone, pop, (1, 0.5), (0, 0.5))
    d.edge(pop, rec, (1, 0.5), (0, 0.5))
    d.edge(rec, shield, (1, 0.5), (0, 0.5))
    d.edge(shield, s3, (1, 0.5), (0, 0.5))

    d.note(50, 290, "Cache-Control\nmax-age=1800\n0 solicitudes", 200)
    d.note(320, 290, "llave = URI normalizada\ns-maxage 1 año\nTTL mín 1 día", 200)
    d.note(560, 290, "hit compartido\npor varios POPs", 180)
    d.note(780, 290, "colapsa los misses:\nun solo pedido a S3", 180)
    d.note(1060, 290, "nombre versionado\npor hash: sin\ninvalidaciones", 200)

    d.label(30, 430, "Qué cuesta cada capa", 300, 14, True, align="left")
    d.label(30, 460, "Dispositivo: nada (ni solicitud ni bytes)", 360, 12, align="left")
    d.label(30, 485, "POP / REC / Shield: se cobra cada byte entregado al teléfono, sea hit o miss", 560, 12, align="left")
    d.label(30, 510, "Origin Shield: solo los misses que llegan a él (US$ 0,0075 por 10.000)", 520, 12, align="left")
    d.label(30, 535, "S3: GET por cada miss del shield; la transferencia S3 → CloudFront es gratis", 560, 12, align="left")
    d.label(700, 460, "Por eso el orden de las palancas es:", 340, 12, True, align="left")
    d.label(700, 485, "1. menos bytes por imagen (ancho + AVIF/WebP)", 340, 12, align="left")
    d.label(700, 510, "2. menos descargas (caché en el dispositivo)", 340, 12, align="left")
    d.label(700, 535, "3. menor precio por byte (plan o descuentos)", 340, 12, align="left")
    return d.save()


if __name__ == "__main__":
    for path in (architecture(), cache_layers()):
        print(f"--> wrote {path.relative_to(REPO_ROOT)}")
