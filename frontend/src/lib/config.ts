/** Runtime configuration, deployed by CDK as /config.json (Cache-Control: no-cache). */
export interface AppConfig {
  environment: string;
  region: string;
  userPoolId: string;
  userPoolClientId: string;
  apiBaseUrl: string;
  imagesCdnUrl: string;
  deviceCacheTtlSeconds: number;
  demoUsers: string[];
}

let current: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  const response = await fetch("/config.json", { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} al leer /config.json`);
  }
  current = (await response.json()) as AppConfig;
  return current;
}

export function getConfig(): AppConfig {
  if (!current) {
    throw new Error("config.json todavía no está cargado");
  }
  return current;
}
