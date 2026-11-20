/**
 * Client side of the image negotiation: the app picks a STABLE URL per device class.
 *   physical width = CSS width x devicePixelRatio, snapped to the breakpoints of the catalog (320..1024)
 *   quality        = lite on Save-Data or slow networks, otherwise standard (decided again at the edge)
 *   format         = never in the URL by default: CloudFront picks AVIF > WebP > JPEG from the Accept header
 * Snapping on the client keeps the URL identical across sessions, so the device cache and the edge cache hit.
 */
import type { CatalogImage } from "./api";

export type FormatPreference = "auto" | "avif" | "webp" | "jpeg";
export type QualityPreference = "auto" | "standard" | "lite";
export type DprPreference = "auto" | 1 | 2 | 3;

export interface Preferences {
  format: FormatPreference;
  quality: QualityPreference;
  dpr: DprPreference;
  bypassDevice: boolean;
}

export interface NetworkInfo {
  effectiveType: string;
  saveData: boolean;
  downlink?: number;
}

export interface RequestPlan {
  url: string;
  cssWidth: number;
  dpr: number;
  physicalWidth: number;
  width: number;
  quality: "standard" | "lite";
  qualityReason: string;
  format: FormatPreference;
  network: NetworkInfo;
}

export const DEFAULT_PREFERENCES: Preferences = { format: "auto", quality: "auto", dpr: "auto", bypassDevice: false };

interface NavigatorConnection {
  effectiveType?: string;
  saveData?: boolean;
  downlink?: number;
}

export function networkInfo(): NetworkInfo {
  const connection = (navigator as Navigator & { connection?: NavigatorConnection }).connection;
  return {
    effectiveType: connection?.effectiveType ?? "desconocida",
    saveData: Boolean(connection?.saveData),
    downlink: connection?.downlink,
  };
}

export function devicePixelRatioFor(preference: DprPreference): number {
  if (preference !== "auto") {
    return preference;
  }
  return Math.min(3, Math.max(1, Math.round((window.devicePixelRatio || 1) * 100) / 100));
}

export function snapWidth(physicalWidth: number, widths: number[]): number {
  const sorted = [...widths].sort((a, b) => a - b);
  return sorted.find((width) => width >= physicalWidth) ?? sorted[sorted.length - 1];
}

export function planRequest(
  cdnBaseUrl: string,
  image: CatalogImage,
  cssWidth: number,
  widths: number[],
  preferences: Preferences,
): RequestPlan {
  const network = networkInfo();
  const dpr = devicePixelRatioFor(preferences.dpr);
  const physicalWidth = Math.ceil(Math.max(1, cssWidth) * dpr);
  const width = snapWidth(physicalWidth, widths);

  let quality: "standard" | "lite" = "standard";
  let qualityReason = "red normal";
  if (preferences.quality !== "auto") {
    quality = preferences.quality;
    qualityReason = "forzada en el laboratorio";
  } else if (network.saveData) {
    quality = "lite";
    qualityReason = "ahorro de datos activo (Save-Data)";
  } else if (["slow-2g", "2g", "3g"].includes(network.effectiveType)) {
    quality = "lite";
    qualityReason = `red lenta (${network.effectiveType})`;
  }

  const params = new URLSearchParams({ w: String(width) });
  if (quality === "lite" || preferences.quality !== "auto") params.set("q", quality);
  if (preferences.format !== "auto") params.set("f", preferences.format);

  return {
    url: `${cdnBaseUrl}${image.path}?${params.toString()}`,
    cssWidth: Math.round(cssWidth),
    dpr,
    physicalWidth,
    width,
    quality,
    qualityReason,
    format: preferences.format,
    network,
  };
}

/** Expected variant name for a plan and a negotiated format (for the size tables). */
export function variantName(width: number, quality: string, format: string): string {
  const extension = format === "jpeg" ? "jpg" : format;
  return `${width}w-${quality}.${extension}`;
}

const AVIF_PIXEL =
  "data:image/avif;base64,AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUIAAADybWV0YQAAAAAAAAAoaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAGxpYmF2aWYAAAAADnBpdG0AAAAAAAEAAAAeaWxvYwAAAABEAAABAAEAAAABAAABGgAAAB0AAAAoaWluZgAAAAAAAQAAABppbmZlAgAAAAABAABhdjAxQ29sb3IAAAAAamlwcnAAAABLaXBjbwAAABRpc3BlAAAAAAAAAAIAAAACAAAAEHBpeGkAAAAAAwgICAAAAAxhdjFDgQ0MAAAAABNjb2xybmNseAACAAIAAYAAAAAXaXBtYQAAAAAAAAABAAEEAQKDBAAAACVtZGF0EgAKCBgANogQEAwgMg8f8D///8WfhwB8+ErK42A=";
const WEBP_PIXEL = "data:image/webp;base64,UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==";

/** Decode with an <img> element: allowed by img-src data: (fetch() of a data: URI is blocked by connect-src). */
function canDecode(dataUri: string): Promise<boolean> {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image.naturalWidth > 0);
    image.onerror = () => resolve(false);
    image.src = dataUri;
  });
}

let supportPromise: Promise<{ avif: boolean; webp: boolean }> | null = null;

export function supportedFormats(): Promise<{ avif: boolean; webp: boolean }> {
  supportPromise ??= Promise.all([canDecode(AVIF_PIXEL), canDecode(WEBP_PIXEL)]).then(([avif, webp]) => ({ avif, webp }));
  return supportPromise;
}

/**
 * fetch() sends "Accept: *\/*", unlike an <img> request. An image client (this loader, OkHttp, URLSession)
 * must declare the formats it can decode, otherwise the edge falls back to JPEG.
 */
export async function imageAcceptHeader(): Promise<string> {
  const support = await supportedFormats();
  if (support.avif) return "image/avif,image/webp,image/*;q=0.8,*/*;q=0.5";
  if (support.webp) return "image/webp,image/*;q=0.8,*/*;q=0.5";
  return "image/jpeg,image/*;q=0.8,*/*;q=0.5";
}
