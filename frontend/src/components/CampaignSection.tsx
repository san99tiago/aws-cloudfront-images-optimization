import type { Campaign, CatalogImage, CdnSettings } from "../lib/api";
import type { Preferences } from "../lib/variants";
import { PopupCard } from "./PopupCard";

interface Props {
  campaign: Campaign;
  cdn: CdnSettings;
  preferences: Preferences;
  riskProfile: string;
  onSelect: (image: CatalogImage) => void;
}

export function CampaignSection({ campaign, cdn, preferences, riskProfile, onSelect }: Props) {
  const reason =
    campaign.audience === "ALL" ? "Para todos los perfiles" : `Por tu perfil de riesgo ${riskProfile}`;
  return (
    <section className={`campaign campaign--${campaign.id}`} aria-labelledby={`campaign-${campaign.id}`}>
      <header className="campaign__head">
        <h2 id={`campaign-${campaign.id}`} className="campaign__title">
          {campaign.name}
        </h2>
        <p className="campaign__reason">
          {reason} · {campaign.images.length} pop-ups
        </p>
      </header>
      <div className="campaign__grid">
        {campaign.images.map((image) => (
          <PopupCard
            key={image.id}
            image={image}
            campaignName={campaign.name}
            cdn={cdn}
            preferences={preferences}
            onSelect={onSelect}
          />
        ))}
      </div>
    </section>
  );
}
