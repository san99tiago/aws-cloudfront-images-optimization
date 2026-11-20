import { useState } from "react";

import { login } from "../lib/auth";
import type { AppConfig } from "../lib/config";

interface Props {
  config: AppConfig;
  onLoggedIn: () => Promise<void>;
}

const DEMO_PROFILES: Record<string, string> = {
  "santigrc@amazon.com": "HIGH",
  "danilopera@example.com": "LOW",
  "juanca@example.com": "MEDIUM",
};

function friendlyError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (/incorrect username or password|NotAuthorized/i.test(message)) {
    return "Correo o contraseña incorrectos. Revisa los datos e intenta de nuevo.";
  }
  return `No pudimos iniciar sesión: ${message}`;
}

export function Login({ config, onLoggedIn }: Props) {
  const [email, setEmail] = useState(config.demoUsers[0] ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      await onLoggedIn();
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <section className="login__statement" aria-label="Rufus Bank">
        <div className="brand brand--light">
          <span className="brand__mark" aria-hidden="true">
            R
          </span>
          <span className="brand__name">
            Rufus Bank <span>Portal de campañas</span>
          </span>
        </div>
        <p className="login__thesis">Cada byte que no viaja, no se paga.</p>
        <p className="login__support">
          Un pop-up diseñado como PNG de 1,9 MB llega a tu pantalla como un AVIF de unos 40 KB, se guarda 30 minutos en
          tu dispositivo y solo vuelve a pedirse a CloudFront cuando expira.
        </p>
        <ol className="login__route" aria-label="Ruta de una imagen">
          <li>S3 original</li>
          <li>Lambda optimizadora</li>
          <li>S3 optimizado</li>
          <li>CloudFront</li>
          <li>Tu dispositivo</li>
        </ol>
      </section>

      <section className="login__panel">
        <form className="login__form" onSubmit={submit}>
          <h1 className="login__title">Entra al portal</h1>
          <p className="muted">Usa un usuario demo. Tus pop-ups dependen de tu perfil de riesgo.</p>

          <div className="login__users" role="group" aria-label="Usuarios demo">
            {config.demoUsers.map((user) => (
              <button
                key={user}
                type="button"
                className={`chip${user === email ? " is-active" : ""}`}
                onClick={() => setEmail(user)}
              >
                <span>{user}</span>
                <span className={`risk risk--${DEMO_PROFILES[user] ?? "LOW"}`}>{DEMO_PROFILES[user] ?? ""}</span>
              </button>
            ))}
          </div>

          <label className="field">
            <span>Correo</span>
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label className="field">
            <span>Contraseña</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && (
            <p className="login__error" role="alert">
              {error}
            </p>
          )}
          <button className="button button--wide" type="submit" disabled={busy}>
            {busy ? "Entrando" : "Entrar"}
          </button>
          <p className="login__fine muted">
            Autenticación con Amazon Cognito (SRP: la contraseña nunca viaja). Sin registro público: solo existen los
            usuarios creados por la infraestructura.
          </p>
        </form>
      </section>
    </main>
  );
}
