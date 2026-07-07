// Client for POST /api/transcribe.
//
// Wraps the audio Blob in a FormData (multipart) request and lets
// authedFetch attach the Authorization header / refresh-on-401 for us.

import { authedFetch } from "./auth";
import { API_BASE } from "./config";

export interface TranscribeResponse {
  text: string;
  language: string;
  duration_ms: number;
  model: string;
}

export class TranscribeError extends Error {}

export async function transcribeAudio(audio: Blob): Promise<TranscribeResponse> {
  // The server only looks at the content_type on the part, not the name,
  // but giving it a sensible extension keeps server-side logs readable.
  const ext = audio.type.includes("webm")
    ? "webm"
    : audio.type.includes("ogg")
      ? "ogg"
      : audio.type.includes("mp4")
        ? "m4a"
        : audio.type.includes("mpeg") || audio.type.includes("mp3")
          ? "mp3"
          : "audio";
  const form = new FormData();
  form.append("audio", audio, `recording.${ext}`);

  const resp = await authedFetch(`${API_BASE}/transcribe`, {
    method: "POST",
    body: form,
  });

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const json = (await resp.json()) as { detail?: string };
      if (json?.detail) detail = json.detail;
    } catch {
      // body wasn't JSON — fall through with the HTTP code
    }
    if (resp.status === 429) {
      throw new TranscribeError("Troppe richieste vocali. Riprova fra un po'.");
    }
    if (resp.status === 413) {
      throw new TranscribeError("Audio troppo lungo.");
    }
    if (resp.status === 415) {
      throw new TranscribeError("Formato audio non supportato.");
    }
    throw new TranscribeError(detail);
  }

  return (await resp.json()) as TranscribeResponse;
}
