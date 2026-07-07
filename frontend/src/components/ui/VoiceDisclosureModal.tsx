"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Mic } from "lucide-react";

interface VoiceDisclosureModalProps {
  open: boolean;
  onAllow: () => void;
  onCancel: () => void;
  onOpenPrivacy: () => void;
}

/**
 * Shown once before the user's first mic recording. We disclose that the
 * audio leaves the browser for transcription via OpenAI, matching the
 * existing chat-content disclosure pattern and what the privacy informativa
 * states.
 */
export function VoiceDisclosureModal({
  open,
  onAllow,
  onCancel,
  onOpenPrivacy,
}: VoiceDisclosureModalProps) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 bg-foreground/40 backdrop-blur-sm flex items-center justify-center p-6"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.2 }}
            role="dialog"
            aria-modal="true"
            aria-labelledby="voice-disclosure-title"
            className="bg-card border border-border rounded-2xl shadow-xl max-w-md w-full p-6 space-y-4"
          >
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-full bg-primary/10 text-primary flex-shrink-0">
                <Mic className="w-5 h-5" />
              </div>
              <div className="flex-1 min-w-0">
                <h2
                  id="voice-disclosure-title"
                  className="text-lg font-semibold text-foreground leading-snug"
                >
                  Trascrizione vocale
                </h2>
                <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                  Quando registri un messaggio vocale, l'audio viene inviato a
                  OpenAI per la trascrizione in testo. Non conserviamo la
                  registrazione una volta ottenuto il testo.
                </p>
              </div>
            </div>

            <div className="rounded-lg bg-secondary/60 border border-border p-3 text-xs text-foreground/80 space-y-1.5">
              <p>
                Avrai modo di rivedere e modificare la trascrizione prima di
                inviarla all'assistente.
              </p>
              <p>
                Maggiori dettagli nella{" "}
                <button
                  type="button"
                  onClick={onOpenPrivacy}
                  className="text-primary underline hover:no-underline"
                >
                  informativa privacy
                </button>
                .
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={onCancel}
                className="px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              >
                Annulla
              </button>
              <button
                type="button"
                onClick={onAllow}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 shadow-sm transition-all"
              >
                Continua
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
