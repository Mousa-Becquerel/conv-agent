/**
 * Runtime config, resolved once at module load.
 *
 * Single source of truth for `API_BASE` (and anything else derived from
 * Vite env vars). Vite's `import.meta.env.BASE_URL` reflects whatever
 * `base:` was set in `vite.config.ts` at build time (defaults to "/",
 * becomes "/conv-agent/" when the SPA is served under a path prefix on
 * a parent domain). API calls at `${API_BASE}/foo` therefore hit the
 * correct absolute path in both single-origin-root and path-prefix
 * deployments, with no per-file conditionals.
 */

// `import.meta.env.BASE_URL` is guaranteed to end with `/` — strip it so
// we can safely append `/foo` without producing `//foo`.
const _base = (import.meta.env.BASE_URL || "/").replace(/\/+$/, "");

export const API_BASE = `${_base}/api`;
