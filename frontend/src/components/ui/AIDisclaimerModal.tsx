"use client";

import { motion, AnimatePresence } from "framer-motion";
import { ShieldAlert } from "lucide-react";

interface AIDisclaimerModalProps {
  open: boolean;
  onAcknowledge: () => void;
  onOpenPrivacy: () => void;
}

/**
 * Shown once per user on first login (and after they clear localStorage).
 * Required by EU AI Act for chatbot-style "limited risk" systems — users
 * have to be told they're interacting with AI. We pair that disclosure
 * with our specific grounding-vs-fallback behaviour so the framing is
 * concrete, not generic boilerplate.
 */
export function AIDisclaimerModal({ open, onAcknowledge, onOpenPrivacy }: AIDisclaimerModalProps) {
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
            aria-labelledby="ai-disclaimer-title"
            className="bg-card border border-border rounded-2xl shadow-xl max-w-lg w-full p-6 space-y-4"
          >
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-full bg-primary/10 text-primary flex-shrink-0">
                <ShieldAlert className="w-5 h-5" />
              </div>
              <div className="flex-1 min-w-0">
                <h2
                  id="ai-disclaimer-title"
                  className="text-lg font-semibold text-foreground leading-snug"
                >
                  Le risposte sono generate da AI
                </h2>
                <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                  Questo assistente utilizza un modello linguistico per produrre risposte basate
                  sui documenti normativi indicizzati. Anche con citazioni, le risposte possono
                  contenere errori o omissioni.
                </p>
              </div>
            </div>

            <div className="rounded-lg bg-secondary/60 border border-border p-3 text-xs text-foreground/80 space-y-2">
              <p>
                <strong>Verifica sempre con le fonti citate</strong> prima di assumere decisioni
                legali, regolatorie o operative.
              </p>
              <p>
                Le conversazioni e le risposte vengono registrate per finalità di audit di
                conformità: consulta la nostra{" "}
                <button
                  type="button"
                  onClick={onOpenPrivacy}
                  className="text-primary underline hover:no-underline"
                >
                  informativa privacy
                </button>{" "}
                per i dettagli.
              </p>
            </div>

            <button
              type="button"
              onClick={onAcknowledge}
              className="w-full px-4 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 shadow-sm transition-all"
            >
              Ho capito, continua
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
