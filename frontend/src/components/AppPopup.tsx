import { useEffect, useMemo, useRef } from "react";

import type { CatalogImage, CdnSettings } from "../lib/api";
import { getDelivery, loadImage, registerActive } from "../lib/deviceCache";
import { useDeliveryVersion } from "../lib/hooks";
import { planRequest, type Preferences } from "../lib/variants";
import { Receipt } from "./Receipt";

interface Props {
  image: CatalogImage;
  campaignName: string;
  cdn: CdnSettings;
  preferences: Preferences;
  onClose: () => void;
}

const POPUP_CSS_WIDTH = 340;

/** The moment the brief starts from: the user opens the app and a campaign pop-up appears. */
export function AppPopup({ image, campaignName, cdn, preferences, onClose }: Props) {
  useDeliveryVersion();
  const closeRef = useRef<HTMLButtonElement>(null);
  const plan = useMemo(
    () => planRequest(cdn.base_url, image, POPUP_CSS_WIDTH, cdn.widths, preferences),
    [cdn.base_url, cdn.widths, image, preferences],
  );
  const delivery = getDelivery(plan.url);

  useEffect(() => {
    const unregister = registerActive(plan.url);
    loadImage(plan.url, { bypassDevice: preferences.bypassDevice }).catch(() => undefined);
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      unregister();
      window.removeEventListener("keydown", onKey);
    };
  }, [plan.url, preferences.bypassDevice, onClose]);

  return (
    <div className="popup" role="dialog" aria-modal="true" aria-labelledby="popup-title">
      <div className="popup__backdrop" onClick={onClose} />
      <div className="popup__layout">
        <div className="popup__phone">
          <div className="popup__frame" style={{ aspectRatio: `${image.original.width} / ${image.original.height}` }}>
            {image.lqip && <img className="card__lqip" src={image.lqip} alt="" aria-hidden="true" />}
            {delivery && <img className="card__image is-loaded" src={delivery.objectUrl} alt={image.alt} />}
          </div>
        </div>
        <div className="popup__side">
          <p className="popup__eyebrow">Así llega tu pop-up</p>
          <h2 id="popup-title" className="popup__title">
            {image.title}
          </h2>
          <p className="popup__lead">
            Marketing lo diseñó como un PNG de {(image.original.bytes / 1_000_000).toFixed(2).replace(".", ",")} MB. Tu
            teléfono recibe solo la variante que cabe en su pantalla.
          </p>
          <Receipt image={image} campaignName={campaignName} plan={plan} delivery={delivery} cdn={cdn} />
          <button ref={closeRef} type="button" className="button" onClick={onClose}>
            Ver todas mis campañas
          </button>
        </div>
      </div>
    </div>
  );
}
