import { useCallback, useEffect, useState } from "react";

import { Dashboard } from "./components/Dashboard";
import { Login } from "./components/Login";
import { currentSession, logout, type Session } from "./lib/auth";
import type { AppConfig } from "./lib/config";
import { resetSession } from "./lib/deviceCache";

export default function App({ config }: { config: AppConfig }) {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    currentSession().then((value) => {
      setSession(value);
      setChecking(false);
    });
  }, []);

  const handleLogout = useCallback(async () => {
    await logout();
    resetSession();
    try {
      sessionStorage.clear();
    } catch {
      // private mode
    }
    setSession(null);
  }, []);

  if (checking) {
    return (
      <main className="boot">
        <p>Validando tu sesión</p>
      </main>
    );
  }

  return session ? (
    <Dashboard session={session} onLogout={handleLogout} />
  ) : (
    <Login config={config} onLoggedIn={async () => setSession(await currentSession())} />
  );
}
