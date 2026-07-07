"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  createRecorder,
  RecorderPermissionError,
  RecorderUnsupportedError,
  type RecorderInstance,
} from "@/lib/recorder";
import { transcribeAudio, TranscribeError } from "@/lib/transcribe";

const MAX_DURATION_MS = 60_000; // 60s — see also frontend/Phase 6 design notes
const SHOW_ERROR_MS = 4_000;

type State = "idle" | "permission" | "recording" | "transcribing";

interface VoiceInputButtonProps {
  /** Called with the transcript when transcription succeeds. */
  onTranscribed: (text: string) => void;
  /** Disable the button (e.g. during chat streaming). */
  disabled?: boolean;
  /**
   * Called once when the user starts a recording attempt for the first
   * time. The parent can use this to show a disclosure modal — return
   * `true` to allow the recording to proceed, `false` to abort.
   */
  onBeforeFirstUse?: () => Promise<boolean>;
}

function formatElapsed(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function VoiceInputButton({
  onTranscribed,
  disabled,
  onBeforeFirstUse,
}: VoiceInputButtonProps) {
  const [state, setState] = useState<State>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  // Peak level seen during this recording — used after stop to decide if the
  // mic was actually capturing anything. Lets us surface a useful error
  // ("mic seems muted") instead of a generic transcription failure.
  const peakLevelRef = useRef(0);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<RecorderInstance | null>(null);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearError = useCallback(() => {
    setError(null);
    if (errorTimerRef.current) {
      clearTimeout(errorTimerRef.current);
      errorTimerRef.current = null;
    }
  }, []);

  const showError = useCallback(
    (msg: string) => {
      setError(msg);
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
      errorTimerRef.current = setTimeout(() => setError(null), SHOW_ERROR_MS);
    },
    [],
  );

  const stopElapsedTimer = useCallback(() => {
    if (elapsedTimerRef.current) {
      clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }
  }, []);

  // Cleanup on unmount: release mic, kill timers.
  useEffect(() => {
    return () => {
      recorderRef.current?.abort();
      recorderRef.current = null;
      stopElapsedTimer();
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    };
  }, [stopElapsedTimer]);

  const handleStop = useCallback(async () => {
    const rec = recorderRef.current;
    if (!rec) return;
    recorderRef.current = null;
    stopElapsedTimer();
    setState("transcribing");
    try {
      const blob = await rec.stop();
      if (blob.size < 1000) {
        // Too short to mean anything — quietly drop.
        setState("idle");
        return;
      }
      // Log the peak level + blob size so we have a paper trail in the
      // browser console when transcription comes back empty. Useful for
      // distinguishing "mic silent" from "model failed to recognize".
      // eslint-disable-next-line no-console
      console.info("[voice] recording finished", {
        bytes: blob.size,
        peakLevel: peakLevelRef.current.toFixed(3),
      });
      const result = await transcribeAudio(blob);
      const text = result.text.trim();
      if (!text) {
        showError("Nessun parlato riconosciuto. Parla più chiaramente o più a lungo.");
      } else {
        onTranscribed(text);
      }
      setState("idle");
    } catch (e) {
      const msg =
        e instanceof TranscribeError
          ? e.message
          : "Errore durante la trascrizione.";
      showError(msg);
      setState("idle");
    }
  }, [onTranscribed, showError, stopElapsedTimer]);

  const handleStart = useCallback(async () => {
    clearError();
    if (onBeforeFirstUse) {
      const ok = await onBeforeFirstUse();
      if (!ok) return;
    }

    setState("permission");
    peakLevelRef.current = 0;
    try {
      const rec = await createRecorder({
        maxDurationMs: MAX_DURATION_MS,
        onMaxDuration: () => {
          // Auto-stop fires; the recorder's own onstop -> the recorder.stop()
          // promise inside handleStop resolves. We just need to surface
          // that the cap was hit so the user knows.
          showError("Durata massima raggiunta (60s).");
        },
        onLevel: (lvl) => {
          setLevel(lvl);
          if (lvl > peakLevelRef.current) peakLevelRef.current = lvl;
        },
      });
      recorderRef.current = rec;
      await rec.start();
      setState("recording");
      setElapsed(0);
      setLevel(0);
      elapsedTimerRef.current = setInterval(() => {
        setElapsed((e) => e + 1);
      }, 1000);
    } catch (e) {
      if (e instanceof RecorderPermissionError) {
        showError("Permesso microfono negato. Abilita il microfono nel browser.");
      } else if (e instanceof RecorderUnsupportedError) {
        showError("Il browser non supporta la registrazione audio.");
      } else {
        showError("Impossibile avviare il microfono.");
      }
      setState("idle");
    }
  }, [clearError, onBeforeFirstUse, showError]);

  const handleClick = useCallback(() => {
    if (disabled) return;
    if (state === "recording") {
      void handleStop();
    } else if (state === "idle") {
      void handleStart();
    }
    // permission + transcribing → no-op (button is disabled below)
  }, [disabled, state, handleStart, handleStop]);

  const isRecording = state === "recording";
  const isTranscribing = state === "transcribing";
  const isWaitingForPermission = state === "permission";
  const isBusy = isTranscribing || isWaitingForPermission;

  return (
    <div className="flex items-center gap-2">
      {/* Live mic-level meter — visible while recording so the user can
          confirm their voice is actually being captured. Width animates
          from 0 to ~24px. If this stays flat while you speak, the mic
          isn't working. */}
      {isRecording && (
        <div
          aria-hidden
          className="h-1.5 w-6 rounded-full bg-destructive/15 overflow-hidden"
          title="Livello microfono"
        >
          <div
            className="h-full bg-destructive transition-[width] duration-75"
            style={{ width: `${Math.round(level * 100)}%` }}
          />
        </div>
      )}

      {/* Elapsed-time pill, visible while recording */}
      {isRecording && (
        <span
          className="text-xs font-mono tabular-nums text-destructive"
          aria-live="polite"
        >
          {formatElapsed(elapsed)}
        </span>
      )}

      {/* Error pill, visible briefly when something goes wrong */}
      {error && !isRecording && (
        <span
          role="alert"
          className="text-[11px] text-destructive max-w-[180px] truncate"
          title={error}
        >
          {error}
        </span>
      )}

      <button
        type="button"
        onClick={handleClick}
        disabled={disabled || isBusy}
        title={
          isRecording
            ? "Ferma registrazione"
            : isTranscribing
              ? "Trascrizione in corso…"
              : "Registra messaggio vocale"
        }
        aria-pressed={isRecording}
        className={cn(
          "p-2 rounded-md transition-all flex items-center justify-center",
          isRecording
            ? "bg-destructive/10 text-destructive hover:bg-destructive/15"
            : isBusy
              ? "text-muted-foreground/60 cursor-not-allowed"
              : disabled
                ? "text-muted-foreground/40 cursor-not-allowed"
                : "text-muted-foreground hover:text-foreground hover:bg-secondary",
        )}
      >
        {isTranscribing || isWaitingForPermission ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : isRecording ? (
          <Square className="w-4 h-4 fill-current" />
        ) : (
          <Mic className="w-4 h-4" />
        )}
      </button>
    </div>
  );
}
