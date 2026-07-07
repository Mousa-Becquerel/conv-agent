// Token storage + login/logout/refresh flows.
//
// Tokens live in localStorage. That's a deliberate tradeoff for invite-only,
// single-tenant v1 — it survives refresh and is trivially testable.
// We accept the XSS-exposure tradeoff because the app has no third-party
// scripts (no analytics, no ad networks) and a strong CSP would be the
// follow-up rather than moving to httpOnly cookies right now.
//
// On any 401 from a normal API call, callers can attempt `refreshAccess()`
// once; on its failure we fire a `conv-agent:auth-expired` window event
// that App.tsx listens for and uses to log out + show the login screen.

import type { User } from "@/types";
import { API_BASE } from "./config";

const ACCESS_KEY = "conv-agent.auth.access.v1";
const REFRESH_KEY = "conv-agent.auth.refresh.v1";

// ---------- token storage ----------
export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(ACCESS_KEY);
  } catch {
    return null;
  }
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setTokens(access: string, refresh: string): void {
  try {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  } catch {
    // localStorage unavailable (private mode etc) — auth will fail next call.
  }
}

export function clearTokens(): void {
  try {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  } catch {
    // ignore
  }
}

// ---------- HTTP ----------
interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export class AuthError extends Error {}

/** POST /auth/login → stash tokens → return the user profile. */
export async function login(email: string, password: string): Promise<User> {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
  if (resp.status === 401) {
    throw new AuthError("Email o password non validi.");
  }
  if (resp.status === 429) {
    throw new AuthError("Troppi tentativi. Riprova fra un minuto.");
  }
  if (!resp.ok) {
    throw new AuthError(`Errore login (${resp.status}).`);
  }
  const data = (await resp.json()) as LoginResponse;
  setTokens(data.access_token, data.refresh_token);
  return await getMe();
}

/** GET /auth/me — validates the current access token. */
export async function getMe(): Promise<User> {
  const access = getAccessToken();
  if (!access) throw new AuthError("not authenticated");
  const resp = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${access}` },
  });
  if (resp.status === 401) {
    // Try refresh-then-retry once before giving up.
    const fresh = await refreshAccess();
    if (!fresh) throw new AuthError("session expired");
    const r2 = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${fresh}` },
    });
    if (!r2.ok) throw new AuthError("session expired");
    return (await r2.json()) as User;
  }
  if (!resp.ok) throw new AuthError(`HTTP ${resp.status}`);
  return (await resp.json()) as User;
}

/** POST /auth/refresh. Returns the new access token on success, null on failure. */
export async function refreshAccess(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  try {
    const resp = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!resp.ok) {
      clearTokens();
      return null;
    }
    const data = (await resp.json()) as { access_token: string };
    try {
      localStorage.setItem(ACCESS_KEY, data.access_token);
    } catch {
      // ignore
    }
    return data.access_token;
  } catch {
    return null;
  }
}

export function logout(): void {
  clearTokens();
}

// ---------- shared wrapper used by every authenticated API call ----------
/**
 * fetch() with Authorization header attached and one auto-retry on 401
 * (via refresh). On final 401, fires a window event so App.tsx can route
 * back to the login screen.
 */
export async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const access = getAccessToken();
  if (!access) {
    window.dispatchEvent(new CustomEvent("conv-agent:auth-expired"));
    throw new AuthError("not authenticated");
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${access}`);

  let resp = await fetch(input, { ...init, headers });

  if (resp.status === 401) {
    const fresh = await refreshAccess();
    if (!fresh) {
      window.dispatchEvent(new CustomEvent("conv-agent:auth-expired"));
      throw new AuthError("session expired");
    }
    headers.set("Authorization", `Bearer ${fresh}`);
    resp = await fetch(input, { ...init, headers });
  }

  return resp;
}
