import { useCallback, useEffect, useState } from "react";

import { fetchMe, type ApiCall, type CatalogImage, type MeResponse } from "../lib/api";
import type { Session } from "../lib/auth";
import { getConfig } from "../lib/config";
import { purgeExpired, resetSession } from "../lib/deviceCache";
import { DEFAULT_PREFERENCES, type Preferences } from "../lib/variants";
import { AppPopup } from "./AppPopup";
import { CampaignSection } from "./CampaignSection";
import { DeliveryMeter } from "./DeliveryMeter";
import { DevicePanel } from "./DevicePanel";
import { IdentityPanel } from "./IdentityPanel";
import { OptimizationLab } from "./OptimizationLab";

interface Props {
  session: Session;
  onLogout: () => Promise<void>;
}

const POPUP_SEEN_KEY = "rufus-popup-seen";

export function Dashboard({ session, onLogout }: Props) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [apiCall, setApiCall] = useState<ApiCall | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preferences, setPreferences] = useState<Preferences>(DEFAULT_PREFERENCES);
  const [reloadKey, setReloadKey] = useState(0);
  const [selected, setSelected] = useState<CatalogImage | null>(null);
  const [showPopup, setShowPopup] = useState(false);
  const ttlSeconds = getConfig().deviceCacheTtlSeconds;

  useEffect(() => {
    fetchMe(session.idToken)
      .then(({ data, call }) => {
        setMe(data);
        setApiCall(call);
        let seen = false;
        try {
          seen = sessionStorage.getItem(POPUP_SEEN_KEY) === "1";
        } catch {
          seen = false;
        }
        setShowPopup(!seen);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [session.idToken]);

  // The device cache keeps images 30 minutes: purge expired entries now and every 30 seconds
  useEffect(() => {
    purgeExpired();
    const timer = window.setInterval(purgeExpired, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const reload = useCallback(() => {
    resetSession();
    setReloadKey((value) => value + 1);
  }, []);

  const closePopup = useCallback(() => {
    setShowPopup(false);
    try {
      sessionStorage.setItem(POPUP_SEEN_KEY, "1");
    } catch {
      // private mode
    }
  }, []);

  const changePreferences = (next: Preferences) => {
    setPreferences(next);
  };

  if (error) {
    return (
      <main className="boot">
        <p className="boot__error">{error}</p>
        <button type="button" className="button" onClick={onLogout}>
          Salir
        </button>
      </main>
    );
  }

  if (!me || !apiCall) {
    return (
      <main className="boot">
        <p>Leyendo tu perfil y tus campañas</p>
      </main>
    );
  }

  const riskCampaign = me.campaigns.find((campaign) => campaign.audience !== "ALL") ?? me.campaigns[0];
  const popupImage = riskCampaign?.images[0];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            R
          </span>
          <span className="brand__name">
            Rufus Bank <span>Portal de campañas</span>
          </span>
        </div>
        <nav className="topbar__nav" aria-label="Secciones">
          <a href="#campanas">Campañas</a>
          <a href="#laboratorio">Laboratorio</a>
        </nav>
        <div className="topbar__user">
          <span>{me.user.email}</span>
          <button type="button" className="button button--ghost" onClick={onLogout}>
            Salir
          </button>
        </div>
      </header>

      <main className="content">
        <section className="greeting">
          <p className="greeting__eyebrow">{me.user.role}</p>
          <h1 className="greeting__title">Hola, {me.user.name.split(" ")[0]}.</h1>
          <p className="greeting__lead">
            Estos son tus pop-ups de hoy. Pasa el cursor (o toca) cualquiera para ver su comprobante de entrega: de
            dónde vino, cuánto pesaba y cuánto viajó realmente.
          </p>
        </section>

        <div className="overview">
          <DeliveryMeter />
          <DevicePanel
            preferences={preferences}
            ttlSeconds={ttlSeconds}
            onChange={changePreferences}
            onReload={reload}
          />
        </div>

        <IdentityPanel session={session} me={me} apiCall={apiCall} />

        <div id="campanas" key={reloadKey}>
          {me.campaigns.map((campaign) => (
            <CampaignSection
              key={campaign.id}
              campaign={campaign}
              cdn={me.cdn}
              preferences={preferences}
              riskProfile={me.user.risk_profile}
              onSelect={(image) => {
                setSelected(image);
                document.getElementById("laboratorio")?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            />
          ))}
        </div>

        <div id="laboratorio">
          <OptimizationLab campaigns={me.campaigns} cdn={me.cdn} selected={selected} onSelect={setSelected} />
        </div>
      </main>

      <footer className="footer">
        <p>
          Rufus Bank es un banco ficticio para demostrar buenas prácticas de imágenes en Amazon CloudFront. Imágenes:{" "}
          {me.cdn.base_url.replace("https://", "")} · {me.cdn.price_class} · Origin Shield{" "}
          {me.cdn.origin_shield_enabled ? "activo" : "apagado"}.
        </p>
      </footer>

      {showPopup && popupImage && riskCampaign && (
        <AppPopup
          image={popupImage}
          campaignName={riskCampaign.name}
          cdn={me.cdn}
          preferences={preferences}
          onClose={closePopup}
        />
      )}
    </div>
  );
}
