import { useEffect, useMemo, useRef, useState } from "react";

import type { CatalogImage, CdnSettings } from "../lib/api";
import { getDelivery, loadImage, registerActive } from "../lib/deviceCache";
import { SOURCE_STAMP } from "../lib/deliveryView";
import { formatBytes, formatPercent, savings } from "../lib/format";
import { useDeliveryVersion, useElementWidth, useNearViewport } from "../lib/hooks";
import { planRequest, type Preferences } from "../lib/variants";
import { Receipt } from "./Receipt";

interface Props {
  image: CatalogImage;
  campaignName: string;
  cdn: CdnSettings;
  preferences: Preferences;
  onSelect?: (image: CatalogImage) => void;
  eager?: boolean;
}

/** One campaign pop-up: LQIP blur-up, lazy load near the viewport, and the delivery receipt on hover/focus. */
export function PopupCard({ image, campaignName, cdn, preferences, onSelect, eager = false }: Props) {
  const mediaRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLElement>(null);
  const cssWidth = useElementWidth(mediaRef);
  const near = useNearViewport(cardRef);
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState<"right" | "left">("right");
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useDeliveryVersion();

  const plan = useMemo(
    () => (cssWidth ? planRequest(cdn.base_url, image, cssWidth, cdn.widths, preferences) : null),
    [cdn.base_url, cdn.widths, image, cssWidth, preferences],
  );
  const delivery = plan ? getDelivery(plan.url) : undefined;

  useEffect(() => {
    if (!plan || !(near || eager)) return;
    setError(null);
    const unregister = registerActive(plan.url);
    loadImage(plan.url, { bypassDevice: preferences.bypassDevice }).catch((reason: Error) => setError(reason.message));
    return unregister;
  }, [plan, near, eager, preferences.bypassDevice]);

  const loaded = Boolean(delivery && loadedUrl === delivery.objectUrl);

  const showReceipt = () => {
    const rect = cardRef.current?.getBoundingClientRect();
    if (rect) setSide(rect.right + 380 > window.innerWidth ? "left" : "right");
    setOpen(true);
  };

  const ratio = `${image.original.width || 2} / ${image.original.height || 3}`;
  const delivered = delivery?.bodyBytes ?? 0;

  return (
    <figure
      ref={cardRef}
      className={`card${open ? " is-open" : ""}`}
      style={{ "--dominant": image.dominant_color ?? "#1b2a4a" } as React.CSSProperties}
      tabIndex={0}
      onMouseEnter={showReceipt}
      onMouseLeave={() => setOpen(false)}
      onFocus={showReceipt}
      onBlur={() => setOpen(false)}
      onClick={() => onSelect?.(image)}
      aria-describedby={`receipt-${image.id}`}
    >
      <div ref={mediaRef} className="card__media" style={{ aspectRatio: ratio }}>
        {image.lqip && <img className="card__lqip" src={image.lqip} alt="" aria-hidden="true" />}
        {delivery && (
          <img
            className={`card__image${loaded ? " is-loaded" : ""}`}
            src={delivery.objectUrl}
            alt={image.alt}
            decoding="async"
            onLoad={() => setLoadedUrl(delivery.objectUrl)}
          />
        )}
        {delivery && (
          <span className={`card__badge card__badge--${delivery.source}`}>{SOURCE_STAMP[delivery.source]}</span>
        )}
        {error && <span className="card__error">{error}</span>}
      </div>
      <figcaption className="card__caption">
        <span className="card__title">{image.title}</span>
        <span className="card__weight">
          {delivery ? (
            <>
              {formatBytes(delivered)} <span className="muted">de {formatBytes(image.original.bytes)}</span>{" "}
              <span className="saving">−{formatPercent(savings(image.original.bytes, delivered))}</span>
            </>
          ) : (
            <span className="muted">{formatBytes(image.original.bytes)} en el diseño original</span>
          )}
        </span>
      </figcaption>
      {open && plan && (
        <div id={`receipt-${image.id}`} className={`card__receipt card__receipt--${side}`}>
          <Receipt image={image} campaignName={campaignName} plan={plan} delivery={delivery} cdn={cdn} />
        </div>
      )}
    </figure>
  );
}
