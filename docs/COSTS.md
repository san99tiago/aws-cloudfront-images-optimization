# Modelo de costos: Rufus Bank App Images Optimization

> Generado por `scripts/cost_model.py` (`make costs`). Precios de lista de CloudFront tomados de la AWS Price List API el 2026-11-20 y planes flat-rate de la página oficial. Tamaños de imagen: medido en 40 imágenes (original promedio 1.66 MB), escalados al promedio de 1,5 MB del caso. Es un escenario, no una cotización: mide tus números reales primero.

## Supuestos

| Supuesto | Valor |
|---|---|
| Peso promedio original | 1,5 MB por imagen (1 MB = 1.048.576 bytes, 1 TB = 1.024 GB como en la Price List) |
| Mezcla de anchos | 45% 1024w, 35% 768w, 20% 640w |
| Mezcla de formatos | 85% AVIF, 13% WEBP, 2% JPG |
| Tier lite | 15% de las solicitudes (Save-Data o red lenta) |
| Caché en dispositivo 30 min | 35% menos solicitudes a CloudFront |
| URL versionada + 1 año immutable | 80% menos solicitudes a CloudFront |
| Región de entrega | Suramérica (Price Class All, POP Bogotá) y, como referencia, US/EU (Price Class 100) |
| Hit ratio regional | 98% (Origin Shield cobra solo los misses) |
| WAF pay-as-you-go | 1 web ACL (US$ 5) + 3 reglas (US$ 1 c/u) + US$ 0,60 por millón de solicitudes |
| Formato | Cifras en USD con formato es-CO (1.234,56). Precios de lista, sin EDP/PPA ni Savings Bundle |
| Free tier | No se descuenta (1 TB y 10 M solicitudes al mes por organización, normalmente ya consumidos) |

## Peso por solicitud según la optimización

| # | Escenario | Qué cambia | KB por solicitud | vs. original |
|---|---|---|---:|---:|
| S0 | Sin optimización | PNG/JPG original de 1,5 MB, sin caché en el dispositivo: cada apertura de la app descarga de nuevo | 1.536,0 | - |
| S1 | + Ancho del dispositivo (JPEG) | Redimensionado a 640/768/1024w según pantalla y DPR, todavía JPEG q80 | 102,6 | −93,3% |
| S2 | + AVIF / WebP por Accept | CloudFront Function elige AVIF (85%), WebP (13%) o JPEG (2%) según el cliente | 45,2 | −97,1% |
| S3 | + Calidad adaptativa | 15% de las solicitudes (Save-Data, 3G) reciben el tier lite | 42,5 | −97,2% |
| S4 | + Caché en dispositivo 30 min | Cache-Control max-age=1800 + caché de la app: 35% de las aperturas no salen del teléfono | 42,5 | −97,2% |
| S5 | Alternativa: URL versionada + 1 año immutable | Una descarga por teléfono por versión de campaña: 80% menos solicitudes que hoy | 42,5 | −97,2% |

## 10 M solicitudes de imágenes al mes

| # | Escenario | Solicitudes a CloudFront | Transferencia | PAYG Suramérica | PAYG US/EU (PC100) | Mejor plan flat-rate |
|---|---|---:|---:|---:|---:|---|
| S0 | Sin optimización | 10,0 M | 14,31 TB | US$ 1.625 | US$ 1.247 | Business US$ 200 |
| S1 | + Ancho del dispositivo (JPEG) | 10,0 M | 979 GB | US$ 145 | US$ 108 | Business US$ 200 |
| S2 | + AVIF / WebP por Accept | 10,0 M | 431 GB | US$ 84 | US$ 62 | Business US$ 200 |
| S3 | + Calidad adaptativa | 10,0 M | 405 GB | US$ 82 | US$ 59 | Business US$ 200 |
| S4 | + Caché en dispositivo 30 min | 6,5 M | 264 GB | US$ 56 | US$ 41 | Business US$ 200 |
| S5 | Alternativa: URL versionada + 1 año immutable | 2,0 M | 81 GB | US$ 23 | US$ 18 | Business US$ 200 |

## 60 M solicitudes de imágenes al mes

| # | Escenario | Solicitudes a CloudFront | Transferencia | PAYG Suramérica | PAYG US/EU (PC100) | Mejor plan flat-rate |
|---|---|---:|---:|---:|---:|---|
| S0 | Sin optimización | 60,0 M | 85,83 TB | US$ 8.906 | US$ 6.454 | Premium L3 US$ 2.250 |
| S1 | + Ancho del dispositivo (JPEG) | 60,0 M | 5,74 TB | US$ 829 | US$ 610 | Business US$ 200 |
| S2 | + AVIF / WebP por Accept | 60,0 M | 2,53 TB | US$ 467 | US$ 331 | Business US$ 200 |
| S3 | + Calidad adaptativa | 60,0 M | 2,38 TB | US$ 450 | US$ 317 | Business US$ 200 |
| S4 | + Caché en dispositivo 30 min | 39,0 M | 1,54 TB | US$ 295 | US$ 209 | Business US$ 200 |
| S5 | Alternativa: URL versionada + 1 año immutable | 12,0 M | 486 GB | US$ 96 | US$ 70 | Business US$ 200 |

## 100 M solicitudes de imágenes al mes

| # | Escenario | Solicitudes a CloudFront | Transferencia | PAYG Suramérica | PAYG US/EU (PC100) | Mejor plan flat-rate |
|---|---|---:|---:|---:|---:|---|
| S0 | Sin optimización | 100,0 M | 143,05 TB | US$ 14.292 | US$ 10.034 | Premium L4 US$ 3.500 |
| S1 | + Ancho del dispositivo (JPEG) | 100,0 M | 9,56 TB | US$ 1.376 | US$ 1.011 | Business US$ 200 |
| S2 | + AVIF / WebP por Accept | 100,0 M | 4,21 TB | US$ 774 | US$ 546 | Business US$ 200 |
| S3 | + Calidad adaptativa | 100,0 M | 3,96 TB | US$ 745 | US$ 524 | Business US$ 200 |
| S4 | + Caché en dispositivo 30 min | 65,0 M | 2,57 TB | US$ 487 | US$ 343 | Business US$ 200 |
| S5 | Alternativa: URL versionada + 1 año immutable | 20,0 M | 811 GB | US$ 155 | US$ 111 | Business US$ 200 |

## Desglose a 60 M solicitudes (Suramérica, pay-as-you-go)

| Concepto | S0 sin optimizar | S4 optimizado (30 min) | S5 optimizado (1 año) |
|---|---:|---:|---:|
| Data transfer out (por GB, por niveles) | US$ 8.729,36 | US$ 173,92 | US$ 53,51 |
| Solicitudes HTTPS (US$ 0,0220 por 10.000) | US$ 132,00 | US$ 85,80 | US$ 26,40 |
| CloudFront Functions (US$ 0,10 por millón, 2 M gratis) | US$ 0,00 | US$ 3,70 | US$ 1,00 |
| Origin Shield (solo misses, US$ 0,0075 por 10.000) | US$ 0,90 | US$ 0,58 | US$ 0,18 |
| AWS WAF (web ACL + reglas + solicitudes) | US$ 44,00 | US$ 31,40 | US$ 15,20 |
| **Total mensual** | US$ 8.906,26 | US$ 295,40 | US$ 96,29 |

## Costos que normalmente no se ven

| Costo | Cuándo aparece | Cómo se evita o se controla |
|---|---|---|
| Data transfer en cache HIT | Siempre: el byte entregado al teléfono se cobra aunque venga del edge | Menos bytes por imagen (formato + ancho) y menos descargas (caché en el dispositivo) |
| Solicitudes HTTPS en Suramérica | US$ 0,0220 por 10.000, 2,2x la tarifa de US | Caché en el dispositivo; con plan flat-rate no se cobran aparte |
| Price Class | Price Class All usa el POP de Bogotá con tarifa SA (hasta 2x US en niveles altos) | Price Class 100/200 sirve desde US/EU: más barato, más latencia; en flat-rate no hay diferencia regional |
| Cache busters en la URL | Tokens o timestamps cambian la URL en cada login: el teléfono vuelve a descargar | URLs estables y versionadas por hash de contenido |
| Compresión Gzip/Brotli en imágenes | No reduce JPEG/PNG/WebP/AVIF y duplica entradas de caché por Accept-Encoding | Política de caché de imágenes sin compresión (como en este repo) |
| Invalidaciones | 1.000 rutas gratis al mes, luego US$ 0,005 por ruta | Nombres versionados: nunca se invalida una imagen |
| Lambda@Edge | US$ 0,60 por millón + cómputo, también en planes flat-rate | CloudFront Functions (US$ 0,10 por millón, incluidas en flat-rate) |
| Real-time logs | US$ 0,01 por millón de líneas + Kinesis, y bloquean los planes flat-rate | Standard logs v2 a CloudWatch Logs (incluidos en flat-rate) |
| Métricas adicionales de CloudFront | 8 métricas de CloudWatch por distribución, precio fijo mensual | Activarlas solo donde se necesita el CacheHitRate |
| Origin Shield | Solo en Premium dentro de flat-rate; en PAYG por cada miss que llega al shield | Útil con muchos REC y orígenes costosos; con S3 y alto hit ratio es opcional |
| WAF | PAYG: US$ 5 por ACL + US$ 1 por regla + US$ 0,60 por millón | Incluido en flat-rate (y obligatorio en el plan) |
| Descuentos empresariales | Los planes flat-rate no se combinan con EDP/PPA, Savings Bundle ni otros descuentos | Comparar el plan contra el PAYG ya descontado de la organización |
| Exceso sostenido en flat-rate | Sin cargo extra, pero la entrega puede degradarse (menos POPs o más lejanos) | Dimensionar con holgura y vigilar los avisos de 50%, 80% y 100% |
| Datos móviles del cliente | No está en la factura de AWS, pero un pop-up de 1,5 MB consume el plan de datos del usuario | Las mismas optimizaciones: AVIF a 640-1024w pesa entre 2% y 5% del original |

## Lectura rápida

- A 60 M solicitudes, sin optimizar se transfieren 85,8 TB al mes: PAYG Suramérica US$ 8.906 y en flat-rate solo cabe en Premium L3 (US$ 2.250), porque Business llega hasta 50 TB.
- Con ancho correcto + AVIF/WebP + calidad adaptativa + caché de 30 min: 1.581 GB al mes, PAYG US$ 295 (WAF incluido) y cabe holgado en Business (US$ 200, WAF incluido).
- Con URL versionada + 1 año immutable el PAYG baja a US$ 96: por debajo de Business. Optimiza primero y decide el modelo de precio después, con tus números medidos.
- El plan Business no incluye Origin Shield (solo Premium): en este repo se puede apagar con `origin_shield_enabled: false`.
- Si la organización tiene descuentos PAYG (EDP/PPA), compara contra ese precio: el plan flat-rate no los suma.
