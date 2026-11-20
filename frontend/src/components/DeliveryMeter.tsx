import { routeStart } from "../lib/deliveryView";
import { activeDeliveries, getSessionStats } from "../lib/deviceCache";
import { formatBytes, formatPercent, savings } from "../lib/format";
import { useDeliveryVersion } from "../lib/hooks";

/** The scale: what the designs weigh versus what really traveled to this device. */
export function DeliveryMeter() {
  useDeliveryVersion();
  const deliveries = activeDeliveries();

  const designBytes = deliveries.reduce(
    (total, delivery) => total + Number(delivery.headers["x-amz-meta-rufus-original-bytes"] ?? 0),
    0,
  );
  const deliveredBytes = deliveries.reduce((total, delivery) => total + delivery.bodyBytes, 0);
  const wireBytes = deliveries.reduce((total, delivery) => total + delivery.transferBytes, 0);
  const fromDevice = deliveries.filter((delivery) => delivery.source === "device").length;
  const fromCdn = deliveries.length - fromDevice;
  const stats = getSessionStats();
  const cdnCalls = stats.cdnHits + stats.cdnMisses;
  const hitRatio = cdnCalls > 0 ? formatPercent(stats.cdnHits / cdnCalls) : "n/d (sin solicitudes)";
  const layers = [
    { start: 4, label: "Tu dispositivo", hint: "caché local, 0 solicitudes" },
    { start: 3, label: "POP de CloudFront", hint: "hit en el edge" },
    { start: 2, label: "Caché regional", hint: "hit en el REC" },
    { start: 1, label: "Origin Shield", hint: "hit en el shield" },
    { start: 0, label: "S3 optimizado", hint: "miss, viajó al origen" },
  ].map((layer) => ({ ...layer, count: deliveries.filter((delivery) => routeStart(delivery) === layer.start).length }));
  const share = designBytes ? Math.max(0.004, deliveredBytes / designBytes) : 0;

  return (
    <section className="meter" aria-labelledby="meter-title">
      <div className="meter__head">
        <h2 id="meter-title" className="panel__title">
          Báscula de entrega
        </h2>
        <p className="muted">{deliveries.length} imágenes en pantalla</p>
      </div>
      {deliveries.length === 0 && (
        <p className="meter__empty">
          Baja a tus campañas: cada imagen se descarga solo cuando está por aparecer en pantalla (lazy loading).
        </p>
      )}
      <div className="meter__numbers">
        <div>
          <p className="meter__label">Peso de diseño</p>
          <p className="meter__value meter__value--heavy">{formatBytes(designBytes)}</p>
        </div>
        <div>
          <p className="meter__label">Peso entregado</p>
          <p className="meter__value">{formatBytes(deliveredBytes)}</p>
        </div>
        <div>
          <p className="meter__label">Bytes por la red</p>
          <p className="meter__value">{formatBytes(wireBytes)}</p>
        </div>
        <div>
          <p className="meter__label">Ahorro</p>
          <p className="meter__value meter__value--saving">{formatPercent(savings(designBytes, deliveredBytes))}</p>
        </div>
      </div>
      <div className="meter__bar" role="img" aria-label={`Se entregó el ${formatPercent(share)} del peso de diseño`}>
        <span className="meter__fill" style={{ width: `${share * 100}%` }} />
      </div>
      <ul className="meter__legend">
        <li>
          <span className="dot dot--device" /> {fromDevice} desde tu dispositivo (0 solicitudes)
        </li>
        <li>
          <span className="dot dot--cdn-hit" /> {fromCdn} desde CloudFront
        </li>
        <li className="muted">
          Sesión: {stats.cdnRequests} solicitudes a CloudFront, {stats.deviceHits} evitadas, hit ratio {hitRatio}
        </li>
      </ul>
      <p className="meter__label meter__layers-title">Dónde estaban los bytes de cada imagen</p>
      <ul className="layers">
        {layers.map((layer) => (
          <li key={layer.start} className={`layers__row layers__row--${layer.start}`}>
            <span className="layers__label">
              {layer.label} <span className="muted">· {layer.hint}</span>
            </span>
            <span className="layers__bar" aria-hidden="true">
              <span style={{ width: `${deliveries.length ? (layer.count / deliveries.length) * 100 : 0}%` }} />
            </span>
            <span className="layers__count">{layer.count}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
