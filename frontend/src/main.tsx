import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./globals.css";
import { App } from "./App";
import { initSentry, SentryErrorBoundary } from "./lib/sentry";

// Initialise Sentry before any other code runs — captures import-time errors too.
initSentry();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SentryErrorBoundary
      fallback={({ error, resetError }) => (
        <div className="min-h-screen flex items-center justify-center bg-background p-6">
          <div className="max-w-md text-center space-y-4">
            <h1 className="text-2xl font-semibold text-foreground">Si è verificato un errore</h1>
            <p className="text-sm text-muted-foreground">
              {error instanceof Error ? error.message : "Errore imprevisto"}
            </p>
            <button
              type="button"
              onClick={() => resetError()}
              className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm hover:opacity-90"
            >
              Riprova
            </button>
          </div>
        </div>
      )}
    >
      <App />
    </SentryErrorBoundary>
  </StrictMode>,
);
