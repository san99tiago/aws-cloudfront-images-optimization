/**
 * Device cache for campaign images (the browser equivalent of the mobile app disk cache).
 *
 * - Storage: Cache Storage API ("rufus-images-v1"), a file store of the browser. NOT cookies: a cookie holds
 *   about 4 KB and travels in every request, so it would make each image request heavier.
 * - Key: the full image URL (stable and versioned, so the same image never downloads twice inside the TTL).
 * - TTL: config.deviceCacheTtlSeconds (30 minutes). Expired entries are purged every 30 seconds and on load.
 * - Network fetches use cache: "no-store" so this store is the only device layer (no hidden HTTP cache copy):
 *   what you see in the receipt is exactly what traveled.
 */
import { getConfig } from "./config";
import { imageAcceptHeader } from "./variants";

const CACHE_NAME = "rufus-images-v1";
const CACHED_AT_HEADER = "x-rufus-device-cached-at";
const NETWORK_META_HEADER = "x-rufus-network-meta";

export type DeliverySource = "device" | "cdn-hit" | "cdn-refresh" | "cdn-miss" | "network";

export interface ServerTimingMetric {
  name: string;
  description?: string;
  duration?: number;
}

export interface NetworkMeta {
  source: DeliverySource;
  accept: string;
  transferBytes: number;
  durationMs: number;
  protocol?: string;
  serverTiming: ServerTimingMetric[];
  fetchedAt: number;
}

export interface Delivery {
  url: string;
  objectUrl: string;
  source: DeliverySource;
  status: number;
  headers: Record<string, string>;
  contentType: string;
  bodyBytes: number;
  /** Bytes on the wire for THIS load (0 when the device served it). */
  transferBytes: number;
  durationMs: number;
  protocol?: string;
  serverTiming: ServerTimingMetric[];
  /** How the image traveled the first time (kept with the cached copy). */
  firstDelivery?: NetworkMeta;
  cachedAt: number;
  expiresAt: number;
  loadedAt: number;
}

export interface DeviceCacheSummary {
  entries: number;
  bytes: number;
  oldestCachedAt: number | null;
  nextExpiryAt: number | null;
}

type Listener = () => void;

const deliveries = new Map<string, Delivery>();
const inFlight = new Map<string, Promise<Delivery>>();
const listeners = new Set<Listener>();
const activeUrls = new Map<string, number>();
let version = 0;

export interface SessionStats {
  cdnRequests: number;
  deviceHits: number;
  cdnHits: number;
  cdnMisses: number;
  transferredBytes: number;
}

const sessionStats: SessionStats = { cdnRequests: 0, deviceHits: 0, cdnHits: 0, cdnMisses: 0, transferredBytes: 0 };

export function getSessionStats(): SessionStats {
  return { ...sessionStats };
}

/** Cards register the URL they display, so the meter only counts what is on screen. */
export function registerActive(url: string): () => void {
  activeUrls.set(url, (activeUrls.get(url) ?? 0) + 1);
  emit();
  return () => {
    const count = (activeUrls.get(url) ?? 1) - 1;
    if (count <= 0) activeUrls.delete(url);
    else activeUrls.set(url, count);
    emit();
  };
}

export function activeDeliveries(): Delivery[] {
  return [...activeUrls.keys()].map((url) => deliveries.get(url)).filter((value): value is Delivery => Boolean(value));
}

function emit(): void {
  version += 1;
  listeners.forEach((listener) => listener());
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getVersion(): number {
  return version;
}

export function getDelivery(url: string): Delivery | undefined {
  return deliveries.get(url);
}

export function allDeliveries(): Delivery[] {
  return [...deliveries.values()];
}

function ttlMs(): number {
  return (getConfig().deviceCacheTtlSeconds || 1800) * 1000;
}

async function openCache(): Promise<Cache | null> {
  if (!("caches" in window)) {
    return null;
  }
  try {
    return await caches.open(CACHE_NAME);
  } catch {
    return null;
  }
}

function headersToObject(headers: Headers): Record<string, string> {
  const result: Record<string, string> = {};
  headers.forEach((value, key) => {
    if (key !== CACHED_AT_HEADER && key !== NETWORK_META_HEADER) {
      result[key] = value;
    }
  });
  return result;
}

export function parseServerTiming(header: string | undefined): ServerTimingMetric[] {
  if (!header) {
    return [];
  }
  return header.split(",").map((part) => {
    const [name, ...params] = part.trim().split(";");
    const metric: ServerTimingMetric = { name: name.trim() };
    params.forEach((param) => {
      const [key, raw] = param.split("=");
      const value = (raw ?? "").trim().replace(/^"|"$/g, "");
      if (key.trim() === "desc") metric.description = value;
      if (key.trim() === "dur") metric.duration = Number(value);
    });
    return metric;
  });
}

function classify(xCache: string | undefined): DeliverySource {
  const value = (xCache ?? "").toLowerCase();
  if (value.startsWith("hit")) return "cdn-hit";
  if (value.startsWith("refreshhit")) return "cdn-refresh";
  if (value.startsWith("miss")) return "cdn-miss";
  return "network";
}

function lastResourceTiming(url: string): PerformanceResourceTiming | undefined {
  const entries = performance.getEntriesByName(url, "resource") as PerformanceResourceTiming[];
  return entries[entries.length - 1];
}

function record(delivery: Delivery): Delivery {
  if (delivery.source === "device") {
    sessionStats.deviceHits += 1;
  } else {
    sessionStats.cdnRequests += 1;
    sessionStats.transferredBytes += delivery.transferBytes;
    if (delivery.source === "cdn-miss") sessionStats.cdnMisses += 1;
    if (delivery.source === "cdn-hit" || delivery.source === "cdn-refresh") sessionStats.cdnHits += 1;
  }
  const previous = deliveries.get(delivery.url);
  if (previous && previous.objectUrl !== delivery.objectUrl) {
    URL.revokeObjectURL(previous.objectUrl);
  }
  deliveries.set(delivery.url, delivery);
  emit();
  return delivery;
}

async function loadFromDevice(cache: Cache, url: string, started: number): Promise<Delivery | null> {
  const cached = await cache.match(url, { ignoreVary: true });
  if (!cached) {
    return null;
  }
  const cachedAt = Number(cached.headers.get(CACHED_AT_HEADER) ?? 0);
  if (Date.now() - cachedAt >= ttlMs()) {
    await cache.delete(url, { ignoreVary: true });
    return null;
  }
  const blob = await cached.blob();
  let firstDelivery: NetworkMeta | undefined;
  try {
    firstDelivery = JSON.parse(decodeURIComponent(cached.headers.get(NETWORK_META_HEADER) ?? "")) as NetworkMeta;
  } catch {
    firstDelivery = undefined;
  }
  return {
    url,
    objectUrl: URL.createObjectURL(blob),
    source: "device",
    status: 200,
    headers: headersToObject(cached.headers),
    contentType: blob.type,
    bodyBytes: blob.size,
    transferBytes: 0,
    durationMs: Math.round(performance.now() - started),
    protocol: "cache-storage",
    serverTiming: firstDelivery?.serverTiming ?? [],
    firstDelivery,
    cachedAt,
    expiresAt: cachedAt + ttlMs(),
    loadedAt: Date.now(),
  };
}

async function loadFromNetwork(cache: Cache | null, url: string, started: number): Promise<Delivery> {
  const accept = await imageAcceptHeader();
  const response = await fetch(url, {
    mode: "cors",
    credentials: "omit",
    cache: "no-store",
    headers: { Accept: accept },
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} en ${url}`);
  }
  const blob = await response.blob();
  const durationMs = Math.round(performance.now() - started);
  const headers = headersToObject(response.headers);
  const timing = lastResourceTiming(url);
  const serverTiming =
    timing && timing.serverTiming.length > 0
      ? timing.serverTiming.map((metric) => ({
          name: metric.name,
          description: metric.description || undefined,
          duration: metric.duration || undefined,
        }))
      : parseServerTiming(headers["server-timing"]);
  // transferSize needs Timing-Allow-Origin (set by the response headers policy); fall back to the body size
  const transferBytes = timing && timing.transferSize > 0 ? timing.transferSize : blob.size;
  const now = Date.now();
  const meta: NetworkMeta = {
    source: classify(headers["x-cache"]),
    accept,
    transferBytes,
    durationMs,
    protocol: timing?.nextHopProtocol || undefined,
    serverTiming,
    fetchedAt: now,
  };

  if (cache) {
    const stored = new Response(blob, {
      status: 200,
      headers: {
        ...headers,
        [CACHED_AT_HEADER]: String(now),
        [NETWORK_META_HEADER]: encodeURIComponent(JSON.stringify(meta)),
      },
    });
    try {
      await cache.put(url, stored);
    } catch {
      // quota or private mode: the page still works without the device layer
    }
  }

  return {
    url,
    objectUrl: URL.createObjectURL(blob),
    source: meta.source,
    status: response.status,
    headers,
    contentType: blob.type,
    bodyBytes: blob.size,
    transferBytes,
    durationMs,
    protocol: meta.protocol,
    serverTiming,
    firstDelivery: meta,
    cachedAt: now,
    expiresAt: now + ttlMs(),
    loadedAt: now,
  };
}

/** Device first (if fresh), then CloudFront. Concurrent calls for the same URL share one request. */
export function loadImage(url: string, options: { bypassDevice?: boolean } = {}): Promise<Delivery> {
  const key = `${options.bypassDevice ? "bypass:" : ""}${url}`;
  const pending = inFlight.get(key);
  if (pending) {
    return pending;
  }
  const started = performance.now();
  const promise = (async () => {
    const cache = await openCache();
    if (cache && !options.bypassDevice) {
      const fromDevice = await loadFromDevice(cache, url, started);
      if (fromDevice) {
        return record(fromDevice);
      }
    }
    return record(await loadFromNetwork(cache, url, started));
  })().finally(() => inFlight.delete(key));
  inFlight.set(key, promise);
  return promise;
}

export async function purgeExpired(): Promise<number> {
  const cache = await openCache();
  if (!cache) {
    return 0;
  }
  let removed = 0;
  for (const request of await cache.keys()) {
    const response = await cache.match(request, { ignoreVary: true });
    const cachedAt = Number(response?.headers.get(CACHED_AT_HEADER) ?? 0);
    if (Date.now() - cachedAt >= ttlMs()) {
      await cache.delete(request, { ignoreVary: true });
      removed += 1;
    }
  }
  if (removed > 0) {
    emit();
  }
  return removed;
}

export async function purgeAll(): Promise<void> {
  if ("caches" in window) {
    await caches.delete(CACHE_NAME);
  }
  emit();
}

export async function summarize(): Promise<DeviceCacheSummary> {
  const cache = await openCache();
  const summary: DeviceCacheSummary = { entries: 0, bytes: 0, oldestCachedAt: null, nextExpiryAt: null };
  if (!cache) {
    return summary;
  }
  for (const request of await cache.keys()) {
    const response = await cache.match(request, { ignoreVary: true });
    if (!response) continue;
    const cachedAt = Number(response.headers.get(CACHED_AT_HEADER) ?? 0);
    summary.entries += 1;
    summary.bytes += Number(response.headers.get("content-length") ?? 0);
    summary.oldestCachedAt = summary.oldestCachedAt === null ? cachedAt : Math.min(summary.oldestCachedAt, cachedAt);
  }
  summary.nextExpiryAt = summary.oldestCachedAt === null ? null : summary.oldestCachedAt + ttlMs();
  return summary;
}

/** Forget what this page rendered (the device cache stays intact). */
export function resetSession(): void {
  deliveries.forEach((delivery) => URL.revokeObjectURL(delivery.objectUrl));
  deliveries.clear();
  emit();
}
