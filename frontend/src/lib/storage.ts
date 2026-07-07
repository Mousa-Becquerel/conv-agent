// Local UI preferences (NOT conversation data — that lives server-side now).
// Two tiny things we still want to persist across reloads:
//   - whether the sidebar is open or collapsed
//   - whether the user has acknowledged the AI disclaimer modal

const SIDEBAR_KEY = "conv-agent.sidebar.open.v1";
const DISCLAIMER_KEY = "conv-agent.disclaimer.ack.v1";
const VOICE_DISCLOSURE_KEY = "conv-agent.voice.disclosure.ack.v1";

// Older v1/v2 keys that we want to clean up if they're still hanging around
// from before the server-state migration. Quiet best-effort removal.
const STALE_KEYS = [
  "conv-agent.conversation.v1",
  "conv-agent.conversations.v2",
];

export function pruneLegacyStorage(): void {
  for (const key of STALE_KEYS) {
    try {
      localStorage.removeItem(key);
    } catch {
      // ignore
    }
  }
}

// ---------- Sidebar collapsed state ----------
export function loadSidebarOpen(): boolean {
  try {
    const raw = localStorage.getItem(SIDEBAR_KEY);
    if (raw === null) return true; // default open
    return raw === "true";
  } catch {
    return true;
  }
}

export function saveSidebarOpen(open: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_KEY, String(open));
  } catch {
    // ignore
  }
}

// ---------- AI disclaimer acknowledgment ----------
export function loadDisclaimerAck(): boolean {
  try {
    return localStorage.getItem(DISCLAIMER_KEY) === "true";
  } catch {
    return false;
  }
}

export function saveDisclaimerAck(): void {
  try {
    localStorage.setItem(DISCLAIMER_KEY, "true");
  } catch {
    // ignore
  }
}

// ---------- Voice transcription disclosure (separate from chat disclaimer) ----------
export function loadVoiceDisclosureAck(): boolean {
  try {
    return localStorage.getItem(VOICE_DISCLOSURE_KEY) === "true";
  } catch {
    return false;
  }
}

export function saveVoiceDisclosureAck(): void {
  try {
    localStorage.setItem(VOICE_DISCLOSURE_KEY, "true");
  } catch {
    // ignore
  }
}
