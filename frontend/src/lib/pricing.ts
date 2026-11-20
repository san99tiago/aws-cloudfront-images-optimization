/**
 * CloudFront pay-as-you-go list prices (AWS Price List API, read on 2026-11-20) and flat-rate plans.
 * Same numbers as scripts/cost_model.py. Tiers count GB per month and per region (1 TB = 1,024 GB).
 */
export interface Tier {
  upToGb: number;
  usdPerGb: number;
}

export const DATA_TRANSFER_TIERS: Record<"SA" | "US", Tier[]> = {
  SA: [
    { upToGb: 10_240, usdPerGb: 0.11 },
    { upToGb: 51_200, usdPerGb: 0.105 },
    { upToGb: 153_600, usdPerGb: 0.09 },
    { upToGb: 512_000, usdPerGb: 0.08 },
    { upToGb: 1_048_576, usdPerGb: 0.06 },
    { upToGb: 5_242_880, usdPerGb: 0.05 },
    { upToGb: Number.POSITIVE_INFINITY, usdPerGb: 0.04 },
  ],
  US: [
    { upToGb: 10_240, usdPerGb: 0.085 },
    { upToGb: 51_200, usdPerGb: 0.08 },
    { upToGb: 153_600, usdPerGb: 0.06 },
    { upToGb: 512_000, usdPerGb: 0.04 },
    { upToGb: 1_048_576, usdPerGb: 0.03 },
    { upToGb: 5_242_880, usdPerGb: 0.025 },
    { upToGb: Number.POSITIVE_INFINITY, usdPerGb: 0.02 },
  ],
};

export const HTTPS_PER_10K = { SA: 0.022, US: 0.01 };

export const FLAT_RATE_PLANS = [
  { name: "Pro", usd: 15, requests: 10_000_000, dataGb: 51_200 },
  { name: "Business", usd: 200, requests: 125_000_000, dataGb: 51_200 },
  { name: "Premium", usd: 1_000, requests: 500_000_000, dataGb: 51_200 },
  { name: "Premium L2", usd: 1_450, requests: 750_000_000, dataGb: 76_800 },
  { name: "Premium L3", usd: 2_250, requests: 1_250_000_000, dataGb: 128_000 },
];

export function dataTransferCost(gb: number, region: "SA" | "US"): number {
  let remaining = gb;
  let previousLimit = 0;
  let cost = 0;
  for (const tier of DATA_TRANSFER_TIERS[region]) {
    const inTier = Math.min(remaining, tier.upToGb - previousLimit);
    if (inTier <= 0) break;
    cost += inTier * tier.usdPerGb;
    remaining -= inTier;
    previousLimit = tier.upToGb;
  }
  return cost;
}

export function monthlyPayAsYouGo(requests: number, bytesPerRequest: number, region: "SA" | "US") {
  const gb = (requests * bytesPerRequest) / 1024 ** 3;
  const transfer = dataTransferCost(gb, region);
  const requestCost = (requests / 10_000) * HTTPS_PER_10K[region];
  return { gb, transfer, requestCost, total: transfer + requestCost };
}

export function cheapestPlan(requests: number, gb: number) {
  return FLAT_RATE_PLANS.find((plan) => requests <= plan.requests && gb <= plan.dataGb) ?? null;
}

export function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}
