import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/instrument-sans";
import "@fontsource/dm-mono/400.css";
import "@fontsource/dm-mono/500.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { configureAuth } from "./lib/auth";
import { loadConfig } from "./lib/config";

// Keep enough Resource Timing entries for every image of the session (default buffer is 250)
performance.setResourceTimingBufferSize(1000);

const root = document.getElementById("root")!;

loadConfig()
  .then((config) => {
    configureAuth(config);
    createRoot(root).render(
      <StrictMode>
        <App config={config} />
      </StrictMode>,
    );
  })
  .catch((error: Error) => {
    root.innerHTML = `<main class="boot"><p class="boot__error">No se pudo cargar la configuración (${error.message}).</p></main>`;
  });
