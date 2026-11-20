import type { CatalogImage, CdnSettings } from "../lib/api";
import type { Delivery } from "../lib/deviceCache";
import { SOURCE_LABEL, SOURCE_STAMP, hitLayerLabel, metric, routeExplanation } from "../lib/deliveryView";
import { formatBytes, formatClock, formatCountdown, formatPercent, formatSeconds, popCity, savings } from "../lib/format";
import { useNow } from "../lib/hooks";
import type { RequestPlan } from "../lib/variants";
import { RouteStrip } from "./RouteStrip";

interface Props {
  image: CatalogImage;
  campaignName: string;
  plan: RequestPlan;
  delivery?: Delivery;
  cdn: CdnSettings;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="receipt__row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** "Comprobante de entrega": everything that happened to deliver this image to this device. */
export function Receipt({ image, campaignName, plan, delivery, cdn }: Props) {
  const now = useNow();

  if (!delivery) {
    return (
      <div className="receipt" role="status">
        <p className="receipt__eyebrow">Comprobante de entrega</p>
        <p className="receipt__pending">Pidiendo {plan.width}w a CloudFront…</p>
      </div>
    );
  }

  const headers = delivery.headers;
  const first = delivery.firstDelivery;
  const pop = headers["x-amz-cf-pop"];
  const variant = headers["x-amz-meta-rufus-variant"] ?? "n/d";
  const quality = headers["x-amz-meta-rufus-quality"] ?? "";
  const originalBytes = Number(headers["x-amz-meta-rufus-original-bytes"] ?? image.original.bytes);
  const deliveredBytes = delivery.bodyBytes;
  const fromDevice = delivery.source === "device";
  const downstream = metric(delivery.serverTiming, "cdn-downstream-fbl")?.duration;
  const upstream = metric(delivery.serverTiming, "cdn-upstream-fbl")?.duration;
  const layer = hitLayerLabel(delivery);
  const remaining = delivery.expiresAt - now;
  const cfId = headers["x-amz-cf-id"];

  return (
    <div className={`receipt receipt--${delivery.source}`} role="dialog" aria-label={`Comprobante de entrega de ${image.title}`}>
      <header className="receipt__head">
        <div>
          <p className="receipt__eyebrow">Comprobante de entrega</p>
          <p className="receipt__title">{image.title}</p>
          <p className="receipt__meta">
            {campaignName} · v{image.version.slice(0, 8)}
          </p>
        </div>
        <span className="receipt__stamp">{SOURCE_STAMP[delivery.source]}</span>
      </header>

      <RouteStrip delivery={delivery} pop={pop ?? first?.serverTiming.find((m) => m.name === "cdn-pop")?.description} />
      <p className="receipt__note">{routeExplanation(delivery)}</p>

      <dl className="receipt__rows">
        <Row label="Servida por">
          {SOURCE_LABEL[delivery.source]}
          {fromDevice && first ? ` (llegó de CloudFront ${SOURCE_STAMP[first.source].toUpperCase()})` : ""}
        </Row>
        <Row label="POP">{pop ? `${pop} · ${popCity(pop)}` : "n/d"}</Row>
        {layer && <Row label="Capa">{layer}</Row>}
        <Row label="Variante">
          {variant} {quality && <span className="muted">({quality.replace(":", " q")})</span>}
        </Row>
        <Row label="Peso">
          <strong>{formatBytes(deliveredBytes)}</strong> de {formatBytes(originalBytes)}{" "}
          <span className="saving">−{formatPercent(savings(originalBytes, deliveredBytes))}</span>
        </Row>
        <Row label="Por la red">
          {fromDevice ? "0 B (sin solicitud)" : formatBytes(delivery.transferBytes)}
          {first && fromDevice ? <span className="muted"> · 1ª vez {formatBytes(first.transferBytes)}</span> : null}
        </Row>
        <Row label="Tiempo">
          {delivery.durationMs} ms {delivery.protocol ? <span className="muted">· {delivery.protocol}</span> : null}
        </Row>
      </dl>

      <p className="receipt__section">Por qué esta variante</p>
      <dl className="receipt__rows">
        <Row label="Ancho">
          {plan.cssWidth} px × DPR {plan.dpr} = {plan.physicalWidth} px → {plan.width}w
        </Row>
        <Row label="Formato">
          {plan.format === "auto"
            ? `${(headers["x-amz-meta-rufus-format"] ?? "").toUpperCase()} elegido en el edge por el Accept`
            : `forzado con f=${plan.format}`}
        </Row>
        {first?.accept && (
          <Row label="Accept">
            <span className="muted">{first.accept}</span>
          </Row>
        )}
        <Row label="Calidad">
          {plan.quality} · {plan.qualityReason}
        </Row>
      </dl>

      <p className="receipt__section">Caché</p>
      <dl className="receipt__rows">
        <Row label="Dispositivo">
          {remaining > 0 ? `expira en ${formatCountdown(remaining)}` : "expirada (se borra en la próxima limpieza)"}
          <span className="muted"> · guardada {formatClock(delivery.cachedAt)}</span>
        </Row>
        <Row label="Navegador">max-age {formatSeconds(cdn.browser_max_age_seconds)}</Row>
        <Row label="Edge">
          s-maxage {formatSeconds(cdn.edge_s_maxage_seconds)} · TTL mín {formatSeconds(cdn.edge_min_ttl_seconds)}
        </Row>
        <Row label="Age">{headers["age"] ? `${headers["age"]} s en el edge` : "0 s (recién traída)"}</Row>
        <Row label="ETag">{(headers["etag"] ?? "n/d").replace(/"/g, "").slice(0, 18)}</Row>
      </dl>

      <p className="receipt__section">Server-Timing</p>
      <p className="receipt__mono">
        {delivery.serverTiming
          .filter((item) => !["cdn-rid"].includes(item.name))
          .map((item) => `${item.name.replace("cdn-", "")}${item.description ? `=${item.description}` : ""}${item.duration ? ` ${item.duration}ms` : ""}`)
          .join(" · ") || "n/d"}
      </p>
      {(downstream || upstream) && (
        <p className="receipt__mono muted">
          {upstream ? `origen ${upstream} ms · ` : ""}
          {downstream ? `primer byte al cliente ${downstream} ms` : ""}
        </p>
      )}

      <footer className="receipt__foot">
        <p className="receipt__mono" title={delivery.url}>
          {delivery.url.replace(/^https:\/\//, "").replace(/\/img\/[^?]+/, "/img/…")}
        </p>
        {cfId && <p className="receipt__mono muted">ref {cfId.slice(0, 22)}…</p>}
      </footer>
    </div>
  );
}
