import type { Delivery, DeliverySource, ServerTimingMetric } from "./deviceCache";

export const SOURCE_LABEL: Record<DeliverySource, string> = {
  device: "Tu dispositivo",
  "cdn-hit": "CloudFront · HIT",
  "cdn-refresh": "CloudFront · REFRESH",
  "cdn-miss": "CloudFront · MISS",
  network: "Red",
};

export const SOURCE_STAMP: Record<DeliverySource, string> = {
  device: "Dispositivo",
  "cdn-hit": "Hit",
  "cdn-refresh": "Refresh",
  "cdn-miss": "Miss",
  network: "Red",
};

/** The 5 places an image can come from, from the bucket to the phone (data flows left to right). */
export const ROUTE_NODES = ["S3", "Shield", "REC", "POP", "Tú"] as const;

export function metric(serverTiming: ServerTimingMetric[], name: string): ServerTimingMetric | undefined {
  return serverTiming.find((item) => item.name === name);
}

/** Index of the first node that held the bytes (the route is lit from there to the device). */
export function routeStart(delivery: Delivery): number {
  if (delivery.source === "device") return 4;
  if (delivery.source === "cdn-miss" || delivery.source === "cdn-refresh") return 0;
  const layer = (metric(delivery.serverTiming, "cdn-hit-layer")?.description ?? "EDGE").toUpperCase();
  if (layer.includes("SHIELD") || layer === "OS") return 1;
  if (layer.includes("REC")) return 2;
  return 3;
}

export function routeExplanation(delivery: Delivery): string {
  const start = routeStart(delivery);
  if (start === 4) return "No salió del dispositivo: 0 solicitudes, 0 bytes por la red.";
  if (start === 3) return "El POP de CloudFront ya la tenía en caché.";
  if (start === 2) return "La caché regional (REC) la tenía: el POP no fue al origen.";
  if (start === 1) return "Origin Shield la tenía: S3 no recibió la solicitud.";
  return "Viajó hasta S3 (primera vez para esta variante en esta ruta).";
}

export function hitLayerLabel(delivery: Delivery): string {
  const layer = metric(delivery.serverTiming, "cdn-hit-layer")?.description;
  if (layer) return layer;
  const upstream = metric(delivery.serverTiming, "cdn-upstream-layer")?.description;
  return upstream ? `upstream ${upstream}` : "";
}
