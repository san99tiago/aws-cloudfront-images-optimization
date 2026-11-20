import { useEffect, useState } from "react";

import { purgeAll, summarize, type DeviceCacheSummary } from "../lib/deviceCache";
import { formatBytes, formatCountdown } from "../lib/format";
import { useDeliveryVersion, useNow } from "../lib/hooks";
import {
  devicePixelRatioFor,
  networkInfo,
  supportedFormats,
  type DprPreference,
  type FormatPreference,
  type Preferences,
  type QualityPreference,
} from "../lib/variants";

interface Props {
  preferences: Preferences;
  ttlSeconds: number;
  onChange: (preferences: Preferences) => void;
  onReload: () => void;
}

function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <fieldset className="segmented">
      <legend>{label}</legend>
      <div className="segmented__options">
        {options.map((option) => (
          <button
            key={String(option.value)}
            type="button"
            className={option.value === value ? "is-active" : ""}
            aria-pressed={option.value === value}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

/** The device side of the story: what this browser supports, its local image store and the simulator. */
export function DevicePanel({ preferences, ttlSeconds, onChange, onReload }: Props) {
  const version = useDeliveryVersion();
  const now = useNow();
  const [summary, setSummary] = useState<DeviceCacheSummary | null>(null);
  const [formats, setFormats] = useState<{ avif: boolean; webp: boolean } | null>(null);
  const network = networkInfo();

  useEffect(() => {
    supportedFormats().then(setFormats);
  }, []);

  useEffect(() => {
    summarize().then(setSummary);
  }, [version]);

  const remaining = summary?.nextExpiryAt ? summary.nextExpiryAt - now : 0;

  return (
    <section className="device" aria-labelledby="device-title">
      <h2 id="device-title" className="panel__title">
        Tu dispositivo
      </h2>
      <dl className="device__facts">
        <div>
          <dt>Pantalla</dt>
          <dd>
            DPR {devicePixelRatioFor("auto")} · {window.innerWidth} px de ancho
          </dd>
        </div>
        <div>
          <dt>Red</dt>
          <dd>
            {network.effectiveType} · ahorro de datos {network.saveData ? "activo" : "apagado"}
          </dd>
        </div>
        <div>
          <dt>Formatos</dt>
          <dd>
            {formats ? `AVIF ${formats.avif ? "sí" : "no"} · WebP ${formats.webp ? "sí" : "no"} · JPEG sí` : "detectando"}
          </dd>
        </div>
        <div>
          <dt>Caché local</dt>
          <dd>
            {summary ? `${summary.entries} imágenes · ${formatBytes(summary.bytes)}` : "leyendo"}
            {summary?.entries ? ` · se borran en ${formatCountdown(remaining)}` : ` · TTL ${ttlSeconds / 60} min`}
          </dd>
        </div>
      </dl>

      <div className="device__actions">
        <button type="button" className="button button--ghost" onClick={onReload}>
          Recargar imágenes
        </button>
        <button
          type="button"
          className="button button--ghost"
          onClick={async () => {
            await purgeAll();
            onReload();
          }}
        >
          Vaciar caché del dispositivo
        </button>
        <label className="toggle">
          <input
            type="checkbox"
            checked={preferences.bypassDevice}
            onChange={(event) => onChange({ ...preferences, bypassDevice: event.target.checked })}
          />
          Ignorar caché local
        </label>
      </div>

      <div className="device__simulator">
        <Segmented<FormatPreference>
          label="Formato"
          value={preferences.format}
          options={[
            { value: "auto", label: "Auto" },
            { value: "avif", label: "AVIF" },
            { value: "webp", label: "WebP" },
            { value: "jpeg", label: "JPEG" },
          ]}
          onChange={(format) => onChange({ ...preferences, format })}
        />
        <Segmented<QualityPreference>
          label="Calidad"
          value={preferences.quality}
          options={[
            { value: "auto", label: "Auto" },
            { value: "standard", label: "Standard" },
            { value: "lite", label: "Lite" },
          ]}
          onChange={(quality) => onChange({ ...preferences, quality })}
        />
        <Segmented<string>
          label="Densidad"
          value={String(preferences.dpr)}
          options={[
            { value: "auto", label: "Auto" },
            { value: "1", label: "1x" },
            { value: "2", label: "2x" },
            { value: "3", label: "3x" },
          ]}
          onChange={(dpr) => onChange({ ...preferences, dpr: (dpr === "auto" ? "auto" : Number(dpr)) as DprPreference })}
        />
      </div>
      <p className="device__hint">
        Cada combinación es otra URL: la primera vez viaja a CloudFront y después sale de la caché local durante{" "}
        {ttlSeconds / 60} minutos.
      </p>
    </section>
  );
}
