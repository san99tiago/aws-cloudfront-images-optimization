import { getConfig } from "./config";

export type RiskProfile = "LOW" | "MEDIUM" | "HIGH";

export interface CatalogImage {
  id: string;
  title: string;
  subtitle: string;
  cta: string;
  alt: string;
  version: string;
  path: string;
  original: { path: string; bytes: number; width: number; height: number; format: string };
  variants: Record<string, number>;
  lqip?: string;
  dominant_color?: string;
  optimized_at?: string;
  processing_ms?: number;
}

export interface Campaign {
  id: string;
  name: string;
  audience: "ALL" | RiskProfile;
  images: CatalogImage[];
}

export interface CdnSettings {
  base_url: string;
  widths: number[];
  default_width: number;
  formats: string[];
  quality_tiers: string[];
  quality_profiles: Record<string, Record<string, number>>;
  browser_max_age_seconds: number;
  edge_s_maxage_seconds: number;
  edge_min_ttl_seconds: number;
  edge_default_ttl_seconds: number;
  edge_max_ttl_seconds: number;
  price_class: string;
  origin_shield_enabled: boolean;
}

export interface MeResponse {
  user: { email: string; name: string; role: string; score: number; risk_profile: RiskProfile };
  token: { sub: string; token_use: string; issuer: string; expires_at: string };
  segmentation: { rule: string; audiences: Record<string, string>; selected: string[] };
  campaigns: Campaign[];
  cdn: CdnSettings;
  generated_at: string;
}

export interface ApiCall {
  status: number;
  durationMs: number;
  cacheControl: string;
  contentEncoding: string;
  pop: string;
  xCache: string;
}

/** GET /api/me through the same CloudFront domain (behavior /api/*, caching disabled). */
export async function fetchMe(idToken: string): Promise<{ data: MeResponse; call: ApiCall }> {
  const started = performance.now();
  const response = await fetch(`${getConfig().apiBaseUrl}/me`, {
    headers: { Authorization: `Bearer ${idToken}` },
    cache: "no-store",
  });
  const call: ApiCall = {
    status: response.status,
    durationMs: Math.round(performance.now() - started),
    cacheControl: response.headers.get("cache-control") ?? "",
    contentEncoding: response.headers.get("content-encoding") ?? "",
    pop: response.headers.get("x-amz-cf-pop") ?? "",
    xCache: response.headers.get("x-cache") ?? "",
  };
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GET /api/me respondió ${response.status}: ${detail.slice(0, 160)}`);
  }
  return { data: (await response.json()) as MeResponse, call };
}
