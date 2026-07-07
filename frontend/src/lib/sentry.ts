// Sentry init — opt-in via VITE_SENTRY_DSN.
//
// Dev runs always start with DSN unset, so the SDK is never initialised
// and no events leave the browser. In CI/prod we set VITE_SENTRY_DSN at
// build time (Vite inlines it).

import * as Sentry from "@sentry/react";

const DSN = (import.meta.env.VITE_SENTRY_DSN as string | undefined)?.trim();
const ENV = (import.meta.env.VITE_SENTRY_ENVIRONMENT as string | undefined) || import.meta.env.MODE;
const RELEASE = import.meta.env.VITE_SENTRY_RELEASE as string | undefined;

export const sentryEnabled = Boolean(DSN);

export function initSentry(): void {
  if (!DSN) return;
  Sentry.init({
    dsn: DSN,
    environment: ENV,
    release: RELEASE,
    // No performance tracing by default — opt in via env when we need it.
    tracesSampleRate: 0,
    // Session replay disabled in v1 to keep PII surface minimal.
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    // Don't auto-attach the Authorization header; redact it if it leaks.
    sendDefaultPii: false,
    beforeSend(event) {
      const headers = event.request?.headers;
      if (headers && typeof headers === "object") {
        for (const key of Object.keys(headers)) {
          if (key.toLowerCase() === "authorization") {
            (headers as Record<string, string>)[key] = "[REDACTED]";
          }
        }
      }
      return event;
    },
  });
}

// Attach the authenticated user to Sentry events. Called from App.tsx when
// auth resolves; Phase 6 (login screen) wires this up properly.
export function setSentryUser(user: { id: string; email?: string } | null): void {
  if (!sentryEnabled) return;
  if (user) {
    Sentry.setUser({ id: user.id, email: user.email });
  } else {
    Sentry.setUser(null);
  }
}

// Re-export the ErrorBoundary so App.tsx can wrap the tree with it.
export const SentryErrorBoundary = Sentry.ErrorBoundary;
