"use client";

import { Info } from "lucide-react";

interface AIDisclaimerFooterProps {
  onOpenPrivacy: () => void;
}

/**
 * Always-visible footer on chat views — small, non-intrusive reminder of the
 * AI nature of responses and link to the privacy page. Required by EU AI Act
 * for chatbots and reinforces user expectations after the first-load modal
 * is dismissed.
 */
export function AIDisclaimerFooter({ onOpenPrivacy }: AIDisclaimerFooterProps) {
  return (
    <div className="bg-background px-4 py-2 flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
      <div className="flex items-center gap-1.5 min-w-0">
        <Info className="w-3 h-3 flex-shrink-0" />
        <span className="truncate">
          Risposte generate da AI · verifica sempre con le fonti citate prima di assumere decisioni.
        </span>
      </div>
      <button
        type="button"
        onClick={onOpenPrivacy}
        className="underline hover:text-foreground transition-colors flex-shrink-0"
      >
        Privacy
      </button>
    </div>
  );
}
