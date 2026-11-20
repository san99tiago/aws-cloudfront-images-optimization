import { useEffect, useMemo, useState } from "react";

import type { Campaign, CatalogImage, CdnSettings } from "../lib/api";
import { allDeliveries, getDelivery, loadImage } from "../lib/deviceCache";
import { formatBytes, formatPercent, savings } from "../lib/format";
import { useDeliveryVersion } from "../lib/hooks";
import { cheapestPlan, formatUsd, monthlyPayAsYouGo } from "../lib/pricing";

interface Props {
  campaigns: Campaign[];
  cdn: CdnSettings;
  selected: CatalogImage | null;
  onSelect: (image: CatalogImage) => void;
}

const FORMATS: { key: string; label: string; ext: string }[] = [
  { key: "avif", label: "AVIF", ext: "avif" },
  { key: "webp", label: "WebP", ext: "webp" },
  { key: "jpeg", label: "JPEG", ext: "jpg" },
];
const VOLUMES = [10_000_000, 60_000_000, 100_000_000];

/** Variant matrix of one image (sizes measured by the optimizer Lambda) and what each choice costs per month. */
export function OptimizationLab({ campaigns, cdn, selected, onSelect }: Props) {
  useDeliveryVersion();
  const images = useMemo(() => campaigns.flatMap((campaign) => campaign.images), [campaigns]);
  const image = selected ?? images[0];
  const [volume, setVolume] = useState(60_000_000);
  const [showOriginal, setShowOriginal] = useState(false);

  const originalUrl = image ? `${cdn.base_url}${image.original.path}` : "";
  const originalDelivery = originalUrl ? getDelivery(originalUrl) : undefined;
  const deliveredVariant = allDeliveries().find(
    (delivery) =>
      delivery.headers["x-amz-meta-rufus-image-id"] === image?.id &&
      delivery.headers["x-amz-meta-rufus-quality"] !== "original",
  );
  const deliveredName = deliveredVariant?.headers["x-amz-meta-rufus-variant"];

  useEffect(() => {
    if (showOriginal && originalUrl) loadImage(originalUrl).catch(() => undefined);
  }, [showOriginal, originalUrl]);

  useEffect(() => setShowOriginal(false), [image?.id]);

  if (!image) return null;

  const variantBytes = (width: number, tier: string, ext: string) => image.variants[`${width}w-${tier}.${ext}`];
  const reference = deliveredName ? image.variants[deliveredName] : variantBytes(640, "standard", "avif");
  const before = monthlyPayAsYouGo(volume, image.original.bytes, "SA");
  const after = monthlyPayAsYouGo(volume, reference ?? image.original.bytes, "SA");
  const planBefore = cheapestPlan(volume, before.gb);
  const planAfter = cheapestPlan(volume, after.gb);

  return (
    <section className="lab" aria-labelledby="lab-title">
      <header className="lab__head">
        <div>
          <h2 id="lab-title" className="panel__title">
            Laboratorio de variantes
          </h2>
          <p className="muted">
            Medidas reales de la Lambda optimizadora para cada ancho, formato y calidad. Toca una imagen de la galería
            para analizarla.
          </p>
        </div>
        <label className="lab__select">
          Imagen
          <select value={image.id} onChange={(event) => onSelect(images.find((item) => item.id === event.target.value)!)}>
            {campaigns.map((campaign) => (
              <optgroup key={campaign.id} label={campaign.name}>
                {campaign.images.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      </header>

      <div className="lab__body">
        <div className="lab__table-wrap">
          <table className="lab__table">
            <caption>
              Original {image.original.format.toUpperCase()} {image.original.width}×{image.original.height}:{" "}
              <strong className="heavy">{formatBytes(image.original.bytes)}</strong>
            </caption>
            <thead>
              <tr>
                <th scope="col">Ancho</th>
                {FORMATS.map((format) => (
                  <th key={format.key} scope="col" colSpan={2}>
                    {format.label}
                  </th>
                ))}
              </tr>
              <tr className="lab__sub">
                <th scope="col" />
                {FORMATS.flatMap((format) => [
                  <th key={`${format.key}-s`} scope="col">
                    standard
                  </th>,
                  <th key={`${format.key}-l`} scope="col">
                    lite
                  </th>,
                ])}
              </tr>
            </thead>
            <tbody>
              {cdn.widths.map((width) => (
                <tr key={width}>
                  <th scope="row">{width}w</th>
                  {FORMATS.flatMap((format) =>
                    ["standard", "lite"].map((tier) => {
                      const name = `${width}w-${tier}.${format.ext}`;
                      const bytes = image.variants[name];
                      return (
                        <td key={name} className={name === deliveredName ? "is-delivered" : ""}>
                          <span>{formatBytes(bytes)}</span>
                          <span className="lab__pct">−{formatPercent(savings(image.original.bytes, bytes ?? 0))}</span>
                        </td>
                      );
                    }),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted lab__legend">
            Resaltada: la variante que recibió tu dispositivo{deliveredName ? ` (${deliveredName})` : ""}.
          </p>
        </div>

        <div className="lab__compare">
          <div className="lab__compare-media">
            {showOriginal && originalDelivery ? (
              <img src={originalDelivery.objectUrl} alt={`Original de ${image.title}`} />
            ) : deliveredVariant ? (
              <img src={deliveredVariant.objectUrl} alt={`Variante de ${image.title}`} />
            ) : (
              <img src={image.lqip} alt="" aria-hidden="true" />
            )}
          </div>
          <div className="lab__compare-actions">
            <button type="button" className="button button--ghost" onClick={() => setShowOriginal((value) => !value)}>
              {showOriginal ? "Ver la variante optimizada" : `Descargar el original (${formatBytes(image.original.bytes)})`}
            </button>
            {showOriginal && originalDelivery && (
              <p className="muted">
                Original: {formatBytes(originalDelivery.bodyBytes)} por {originalDelivery.source === "device" ? "caché local" : "la red"} en{" "}
                {originalDelivery.durationMs} ms. Mismo aspecto en pantalla, {Math.round(image.original.bytes / Math.max(1, reference ?? 1))}× más
                bytes.
              </p>
            )}
          </div>
        </div>

        <div className="lab__projection">
          <p className="lab__projection-title">Si esta imagen fuera tu pop-up promedio</p>
          <div className="segmented__options">
            {VOLUMES.map((value) => (
              <button
                key={value}
                type="button"
                className={value === volume ? "is-active" : ""}
                aria-pressed={value === volume}
                onClick={() => setVolume(value)}
              >
                {value / 1_000_000} M/mes
              </button>
            ))}
          </div>
          <dl className="lab__projection-rows">
            <div>
              <dt>Sin optimizar</dt>
              <dd>
                {formatBytes(volume * image.original.bytes)} al mes · {formatUsd(before.total)} PAYG Suramérica ·{" "}
                {planBefore ? `cabe en ${planBefore.name} (${formatUsd(planBefore.usd)})` : "no cabe en Business"}
              </dd>
            </div>
            <div>
              <dt>Optimizada</dt>
              <dd>
                {formatBytes(volume * (reference ?? image.original.bytes))} al mes · {formatUsd(after.total)} PAYG Suramérica ·{" "}
                {planAfter ? `cabe en ${planAfter.name} (${formatUsd(planAfter.usd)})` : "requiere Premium"}
              </dd>
            </div>
          </dl>
          <p className="muted">
            Precios de lista de CloudFront (Price List API). Detalle con y sin cada optimización en el README.
          </p>
        </div>
      </div>
    </section>
  );
}
