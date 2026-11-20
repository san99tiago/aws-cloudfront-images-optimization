import type { ApiCall, MeResponse } from "../lib/api";
import type { Session } from "../lib/auth";
import { claimDate } from "../lib/format";

interface Props {
  session: Session;
  me: MeResponse;
  apiCall: ApiCall;
}

const SHOWN_CLAIMS = ["sub", "email", "email_verified", "aud", "iss", "token_use", "auth_time", "iat", "exp"];

/** What travels in the JWT (identity) versus what the API reads from DynamoDB (business profile). */
export function IdentityPanel({ session, me, apiCall }: Props) {
  const claims = session.idClaims;
  return (
    <section className="identity" aria-labelledby="identity-title">
      <h2 id="identity-title" className="panel__title">
        Identidad y perfil
      </h2>
      <div className="identity__columns">
        <div className="identity__col">
          <p className="identity__label">
            En el JWT <span className="muted">(ID token de Cognito, {String(session.idHeader.alg ?? "RS256")})</span>
          </p>
          <dl className="claims">
            {SHOWN_CLAIMS.filter((name) => claims[name] !== undefined).map((name) => (
              <div key={name} className="claims__row">
                <dt>{name}</dt>
                <dd>
                  {["auth_time", "iat", "exp"].includes(name)
                    ? claimDate(claims[name])
                    : String(claims[name]).replace("https://cognito-idp.", "").slice(0, 64)}
                </dd>
              </div>
            ))}
          </dl>
          <p className="identity__hint">
            Sin rol, score ni perfil de riesgo: el token solo prueba quién eres y caduca en 60 minutos.
          </p>
        </div>
        <div className="identity__col">
          <p className="identity__label">
            En DynamoDB <span className="muted">(PK user_email, leído por GET /api/me)</span>
          </p>
          <dl className="claims">
            <div className="claims__row">
              <dt>user_email</dt>
              <dd>{me.user.email}</dd>
            </div>
            <div className="claims__row">
              <dt>name</dt>
              <dd>{me.user.name}</dd>
            </div>
            <div className="claims__row">
              <dt>role</dt>
              <dd>{me.user.role}</dd>
            </div>
            <div className="claims__row">
              <dt>score</dt>
              <dd>{me.user.score}</dd>
            </div>
            <div className="claims__row">
              <dt>risk_profile</dt>
              <dd>
                <span className={`risk risk--${me.user.risk_profile}`}>{me.user.risk_profile}</span>
              </dd>
            </div>
          </dl>
          <p className="identity__hint">
            Campañas asignadas: {me.segmentation.selected.join(" + ")}. GET /api/me respondió {apiCall.status} en{" "}
            {apiCall.durationMs} ms · {apiCall.cacheControl || "sin Cache-Control"}
            {apiCall.contentEncoding ? ` · ${apiCall.contentEncoding}` : ""} · nunca se cachea en CloudFront.
          </p>
        </div>
      </div>
    </section>
  );
}
