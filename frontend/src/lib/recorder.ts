// Tiny MediaRecorder wrapper for the mic button.
//
// Lifecycle:
//   const rec = await createRecorder({ maxDurationMs: 60_000, ... });
//   await rec.start();
//   // ... time passes ...
//   const blob = await rec.stop();   // resolves with the audio Blob
//
// Always call `rec.abort()` on unmount / cleanup so we release the mic
// and the browser's recording indicator goes away. `stop()` already does
// that on the happy path.

const PREFERRED_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
  "audio/mpeg",
];

export type RecorderState = "idle" | "recording" | "stopped";

export interface RecorderOptions {
  /** Auto-stop after this many milliseconds. Call onMaxDuration before stopping. */
  maxDurationMs?: number;
  /** Fires when maxDurationMs is hit; the recorder will then auto-stop. */
  onMaxDuration?: () => void;
  /**
   * Called ~10 times/second during recording with the current peak RMS level
   * (0.0–1.0). UI uses this to render a level meter so the user knows their
   * voice is actually being captured.
   */
  onLevel?: (level: number) => void;
}

export interface RecorderInstance {
  start: () => Promise<void>;
  stop: () => Promise<Blob>;
  abort: () => void;
  getState: () => RecorderState;
  getMimeType: () => string;
}

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "audio/webm";
  for (const t of PREFERRED_MIME_TYPES) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return "audio/webm";
}

export class RecorderUnsupportedError extends Error {}
export class RecorderPermissionError extends Error {}

/**
 * Create a recorder bound to the user's microphone. Requests permission
 * eagerly so the caller knows immediately whether mic access is available
 * — the recorder isn't yet recording, just primed.
 */
export async function createRecorder(
  options: RecorderOptions = {},
): Promise<RecorderInstance> {
  if (
    typeof navigator === "undefined" ||
    !navigator.mediaDevices?.getUserMedia ||
    typeof MediaRecorder === "undefined"
  ) {
    throw new RecorderUnsupportedError("microfono non supportato da questo browser");
  }

  let stream: MediaStream;
  try {
    // Use the browser's default audio constraints — matches the
    // earlier-working build. Explicit constraint objects have been
    // observed to silently switch device selection on some setups.
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    const name = (e as { name?: string })?.name;
    if (name === "NotAllowedError" || name === "SecurityError") {
      throw new RecorderPermissionError("permesso microfono negato");
    }
    throw new RecorderUnsupportedError("impossibile accedere al microfono");
  }

  // Log which device the browser actually gave us — when transcription comes
  // back empty, this is the single most useful diagnostic ("oh, it picked
  // the muted headset, not the laptop mic").
  try {
    const tracks = stream.getAudioTracks();
    const labels = tracks.map((t) => ({
      label: t.label,
      muted: t.muted,
      enabled: t.enabled,
      readyState: t.readyState,
      settings: t.getSettings?.(),
    }));
    // eslint-disable-next-line no-console
    console.info("[voice] active audio track(s):", labels);
  } catch {
    // ignore — purely diagnostic
  }

  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(stream, { mimeType });
  const chunks: Blob[] = [];
  let state: RecorderState = "idle";
  let stopTimer: ReturnType<typeof setTimeout> | null = null;
  let stopResolve: ((blob: Blob) => void) | null = null;

  // ---------- live audio level monitoring (for the UI meter) ----------
  // We tee the stream into an AnalyserNode and sample RMS at ~10Hz.
  // The actual recording goes through MediaRecorder unchanged.
  let audioCtx: AudioContext | null = null;
  let levelRaf: number | null = null;
  if (options.onLevel) {
    try {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      audioCtx = new Ctx();
      // Chrome creates AudioContext in "suspended" state when there hasn't
      // been a recent user gesture. createMediaStreamSource works on a
      // suspended context but getFloatTimeDomainData returns zeros — which
      // looks identical to a silent mic. Resume explicitly. The recorder
      // is being created from a click handler so the autoplay policy is
      // already satisfied, but the API call is still required.
      audioCtx.resume().catch(() => {});
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const tick = () => {
        if (!audioCtx) return;
        analyser.getFloatTimeDomainData(buf);
        let sumSq = 0;
        for (let i = 0; i < buf.length; i++) sumSq += buf[i] * buf[i];
        const rms = Math.sqrt(sumSq / buf.length);
        // Map [0,1] with a soft floor — silence is ~0.005, voice ~0.05-0.3.
        const level = Math.max(0, Math.min(1, (rms - 0.005) * 6));
        options.onLevel?.(level);
        levelRaf = requestAnimationFrame(tick);
      };
      levelRaf = requestAnimationFrame(tick);
    } catch {
      // AudioContext unavailable — silently skip the meter. Recording still works.
      audioCtx = null;
    }
  }

  const tearDown = () => {
    if (stopTimer) {
      clearTimeout(stopTimer);
      stopTimer = null;
    }
    if (levelRaf !== null) {
      cancelAnimationFrame(levelRaf);
      levelRaf = null;
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    stream.getTracks().forEach((t) => t.stop());
  };

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  recorder.onstop = () => {
    state = "stopped";
    tearDown();
    if (stopResolve) {
      const blob = new Blob(chunks, { type: mimeType });
      stopResolve(blob);
      stopResolve = null;
    }
  };

  return {
    start: async () => {
      if (state !== "idle") return;
      state = "recording";
      // Emit a dataavailable event every 250ms — lets us collect chunks
      // incrementally instead of all-at-once at stop time. Doesn't change
      // the final blob, just keeps memory pressure lower for long recordings.
      recorder.start(250);
      if (options.maxDurationMs && options.maxDurationMs > 0) {
        stopTimer = setTimeout(() => {
          if (state === "recording") {
            options.onMaxDuration?.();
            recorder.stop();
          }
        }, options.maxDurationMs);
      }
    },

    stop: () => {
      return new Promise<Blob>((resolve) => {
        if (state !== "recording") {
          resolve(new Blob(chunks, { type: mimeType }));
          return;
        }
        stopResolve = resolve;
        recorder.stop();
      });
    },

    abort: () => {
      stopResolve = null;
      if (state === "recording") {
        try {
          recorder.stop();
        } catch {
          // already stopping; ignore
        }
      }
      tearDown();
    },

    getState: () => state,
    getMimeType: () => mimeType,
  };
}
