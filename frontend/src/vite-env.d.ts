/// <reference types="vite/client" />

// Adds typing for our custom VITE_* env vars on top of Vite's built-in
// `MODE`, `DEV`, `PROD`. All Vite env vars are strings at runtime — the
// `string | undefined` shape reflects that they may be unset at build time.
interface ImportMetaEnv {
  readonly VITE_SENTRY_DSN?: string;
  readonly VITE_SENTRY_ENVIRONMENT?: string;
  readonly VITE_SENTRY_RELEASE?: string;
  readonly VITE_API_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
