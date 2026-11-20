const numberFormat = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 1 });
const integerFormat = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });

export function formatBytes(bytes: number | undefined | null): string {
  if (bytes === undefined || bytes === null || Number.isNaN(bytes)) return "n/d";
  if (bytes === 0) return "0 B";
  if (bytes < 1000) return `${integerFormat.format(bytes)} B`;
  if (bytes < 1_000_000) return `${numberFormat.format(bytes / 1000)} KB`;
  if (bytes < 1_000_000_000) return `${numberFormat.format(bytes / 1_000_000)} MB`;
  if (bytes < 1_000_000_000_000) return `${numberFormat.format(bytes / 1_000_000_000)} GB`;
  return `${numberFormat.format(bytes / 1_000_000_000_000)} TB`;
}

export function formatPercent(value: number): string {
  return `${numberFormat.format(value * 100)}%`;
}

export function savings(original: number, delivered: number): number {
  if (!original) return 0;
  return Math.max(0, 1 - delivered / original);
}

export function formatCountdown(ms: number): string {
  if (ms <= 0) return "00:00";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function formatClock(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatSeconds(seconds: number): string {
  if (seconds >= 86400 && seconds % 86400 === 0) return `${seconds / 86400} d`;
  if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

/** CloudFront POP codes start with the nearest airport code (BOG50-P1 is Bogotá). */
const POP_CITIES: Record<string, string> = {
  BOG: "Bogotá",
  MIA: "Miami",
  IAD: "Washington DC",
  ATL: "Atlanta",
  DFW: "Dallas",
  JFK: "Nueva York",
  EWR: "Nueva York",
  LAX: "Los Ángeles",
  SFO: "San Francisco",
  SEA: "Seattle",
  ORD: "Chicago",
  QRO: "Querétaro",
  MEX: "Ciudad de México",
  GRU: "São Paulo",
  GIG: "Río de Janeiro",
  SCL: "Santiago",
  LIM: "Lima",
  EZE: "Buenos Aires",
  MAD: "Madrid",
  FRA: "Frankfurt",
  LHR: "Londres",
  CDG: "París",
};

export function popCity(pop: string | undefined): string {
  if (!pop) return "";
  return POP_CITIES[pop.slice(0, 3).toUpperCase()] ?? pop.slice(0, 3).toUpperCase();
}

export function claimDate(value: unknown): string {
  const seconds = Number(value);
  if (!seconds) return String(value ?? "");
  return new Date(seconds * 1000).toLocaleString("es-CO");
}
