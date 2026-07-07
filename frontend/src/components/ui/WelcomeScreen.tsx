"use client";

import { useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowUp,
  Plus,
  Filter,
  BookText,
  ScrollText,
  Cog,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { VoiceInputButton } from "./VoiceInputButton";
import { DOC_IDS } from "@/types";

// Curated Italian sample questions per document — identical to the ones
// that pass the indexer smoke test.
const SUGGESTIONS: Record<string, { title: string; questions: string[] }> = {
  [DOC_IDS.SOGL]: {
    title: "Regolamento (UE) 2017/1485 — SOGL",
    questions: [
      "Quali sono gli obblighi dei TSO in materia di controllo della tensione?",
      "Come si classificano gli stati del sistema elettrico?",
      "Cosa sono le contromisure nella gestione del sistema?",
      "Quali sono i limiti di sicurezza operativa che il TSO deve specificare?",
      "Quali sono i requisiti tecnici minimi delle FCR?",
    ],
  },
  [DOC_IDS.TIAD]: {
    title: "TIAD — Autoconsumo Diffuso (ARERA)",
    questions: [
      "Cosa si intende per autoconsumo diffuso?",
      "Quali sono i requisiti per accedere al servizio per l'autoconsumo diffuso?",
      "Quali sono gli adempimenti in capo al GSE?",
      "Come avviene la regolazione delle partite economiche per l'autoconsumo?",
      "Qual è la procedura per l'accesso al servizio?",
    ],
  },
  [DOC_IDS.SDM]: {
    title: "Allegato A.43 — Sistema di Misura",
    questions: [
      "Quali protocolli di comunicazione usa il SAPR?",
      "Che cos'è un'apparecchiatura di misura?",
      "Come funziona il sistema di telecomunicazioni del Sistema di Misura?",
      "Quali sono le anomalie di acquisizione gestite dal SAPR?",
      "Come avviene la ricostruzione e stima dei dati di misura?",
    ],
  },
};

const DOC_FILTER_OPTIONS: Array<{ id: string | null; label: string }> = [
  { id: null, label: "Tutti i documenti" },
  { id: DOC_IDS.SOGL, label: "SOGL (UE 2017/1485)" },
  { id: DOC_IDS.TIAD, label: "TIAD — Autoconsumo" },
  { id: DOC_IDS.SDM, label: "Sistema di Misura" },
];

interface WelcomeScreenProps {
  onSend: (text: string) => void;
  docFilter: string | null;
  onDocFilterChange: (value: string | null) => void;
  onVoiceBeforeFirstUse?: () => Promise<boolean>;
}

export function WelcomeScreen({
  onSend,
  docFilter,
  onDocFilterChange,
  onVoiceBeforeFirstUse,
}: WelcomeScreenProps) {
  const [inputValue, setInputValue] = useState("");
  const [activeDoc, setActiveDoc] = useState<string | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    const text = inputValue.trim();
    if (!text) return;
    onSend(text);
    setInputValue("");
  };

  const handleSuggestionClick = (q: string) => {
    setInputValue(q);
    setActiveDoc(null);
    inputRef.current?.focus();
  };

  const activeFilterLabel =
    DOC_FILTER_OPTIONS.find((o) => o.id === docFilter)?.label ?? "Tutti i documenti";

  return (
    <div className="min-h-screen flex flex-col bg-background relative">
      {/* Subtle dotted-grid backdrop, faded toward bottom */}
      <div
        aria-hidden
        className="absolute inset-0 bg-grid-dots opacity-60 [mask-image:linear-gradient(to_bottom,white_0%,white_55%,transparent_100%)]"
      />

      {/* Brand strip across the top */}
      <div aria-hidden className="h-[3px] bg-brand-strip relative z-10" />

      {/* Top label bar — brand lives in the sidebar; this just names the
          current scope on the right edge. */}
      <header className="relative z-10 px-6 py-4 flex items-center justify-end">
        <span className="text-[11px] tracking-wide uppercase text-muted-foreground">
          Assistente normativo
        </span>
      </header>

      {/* Hero + input */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 py-10">
        <div className="w-full max-w-3xl mx-auto flex flex-col items-center">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="mb-10 text-center flex flex-col items-center gap-3"
          >
            <h1 className="text-4xl md:text-5xl font-semibold tracking-tight text-foreground">
              Pronto ad aiutarti<span className="text-primary">.</span>
            </h1>
            <p className="text-muted-foreground max-w-lg text-base">
              Fai una domanda sui regolamenti elettrici italiani ed europei.
              Risposte fondate sulle fonti, con citazione di articolo e pagina.
            </p>
          </motion.div>

          {/* Input card */}
          <div className="w-full bg-card border border-border rounded-2xl shadow-sm mb-4 transition-shadow focus-within:shadow-md focus-within:border-primary/40">
            <div className="p-5">
              <input
                ref={inputRef}
                type="text"
                placeholder="Fai una domanda…"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                className="w-full text-foreground text-base outline-none placeholder:text-muted-foreground bg-transparent"
              />
            </div>

            {/* Filter chip + send actions */}
            <div className="px-4 py-3 flex items-center justify-between border-t border-border/60">
              <div className="flex items-center gap-2 relative">
                <button
                  type="button"
                  onClick={() => setFilterOpen((v) => !v)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-colors",
                    docFilter
                      ? "bg-primary/10 text-primary hover:bg-primary/15"
                      : "bg-secondary text-muted-foreground hover:bg-secondary/80",
                  )}
                >
                  <Filter className="w-4 h-4" />
                  <span>{activeFilterLabel}</span>
                </button>
                <AnimatePresence>
                  {filterOpen && (
                    <motion.div
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: 4 }}
                      className="absolute top-full mt-2 left-0 bg-card border border-border rounded-md shadow-lg z-20 min-w-[220px] overflow-hidden"
                    >
                      {DOC_FILTER_OPTIONS.map((opt) => (
                        <button
                          key={opt.id ?? "all"}
                          type="button"
                          onClick={() => {
                            onDocFilterChange(opt.id);
                            setFilterOpen(false);
                          }}
                          className={cn(
                            "block w-full text-left px-3 py-2 text-sm hover:bg-secondary transition-colors",
                            opt.id === docFilter && "text-primary font-medium",
                          )}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
              <div className="flex items-center gap-2">
                <VoiceInputButton
                  onBeforeFirstUse={onVoiceBeforeFirstUse}
                  onTranscribed={(text) =>
                    setInputValue((v) => (v ? `${v.trim()} ${text}` : text))
                  }
                />
                <button
                  type="button"
                  onClick={handleSend}
                  disabled={!inputValue.trim()}
                  className={cn(
                    "w-9 h-9 flex items-center justify-center rounded-full transition-all",
                    inputValue.trim()
                      ? "bg-primary text-primary-foreground hover:opacity-90 shadow-sm"
                      : "bg-secondary text-muted-foreground cursor-not-allowed",
                  )}
                >
                  <ArrowUp className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="px-4 py-2 border-t border-border/60">
              <button
                type="button"
                disabled
                title="Caricamento file (presto disponibile)"
                className="flex items-center gap-2 text-muted-foreground/50 text-sm cursor-not-allowed"
              >
                <Plus className="w-4 h-4" />
                <span>Carica file (presto disponibile)</span>
              </button>
            </div>
          </div>

          {/* Doc category cards */}
          <div className="w-full grid grid-cols-3 gap-3 mb-4">
            <DocCard
              icon={<ScrollText className="w-5 h-5" />}
              label="SOGL"
              sublabel="Reg. UE 2017/1485"
              accent="brand-blue"
              isActive={activeDoc === DOC_IDS.SOGL}
              onClick={() => setActiveDoc(activeDoc === DOC_IDS.SOGL ? null : DOC_IDS.SOGL)}
            />
            <DocCard
              icon={<BookText className="w-5 h-5" />}
              label="TIAD"
              sublabel="Autoconsumo Diffuso"
              accent="brand-green"
              isActive={activeDoc === DOC_IDS.TIAD}
              onClick={() => setActiveDoc(activeDoc === DOC_IDS.TIAD ? null : DOC_IDS.TIAD)}
            />
            <DocCard
              icon={<Cog className="w-5 h-5" />}
              label="Sistema di Misura"
              sublabel="Allegato A.43"
              accent="brand-orange"
              isActive={activeDoc === DOC_IDS.SDM}
              onClick={() => setActiveDoc(activeDoc === DOC_IDS.SDM ? null : DOC_IDS.SDM)}
            />
          </div>

          {/* Suggestions */}
          <AnimatePresence>
            {activeDoc && SUGGESTIONS[activeDoc] && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="w-full mb-6 overflow-hidden"
              >
                <div className="bg-card rounded-2xl border border-border shadow-sm overflow-hidden">
                  <div className="p-3 border-b border-border/60">
                    <h3 className="text-sm font-medium text-foreground">
                      {SUGGESTIONS[activeDoc].title}
                    </h3>
                  </div>
                  <ul className="divide-y divide-border/60">
                    {SUGGESTIONS[activeDoc].questions.map((q, i) => (
                      <motion.li
                        key={q}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: i * 0.03 }}
                        onClick={() => handleSuggestionClick(q)}
                        className="p-3 hover:bg-secondary cursor-pointer transition-colors duration-75"
                      >
                        <div className="flex items-center gap-3">
                          <span className="w-1 h-1 rounded-full bg-primary" />
                          <span className="text-sm text-foreground">{q}</span>
                        </div>
                      </motion.li>
                    ))}
                  </ul>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>

    </div>
  );
}

interface DocCardProps {
  icon: React.ReactNode;
  label: string;
  sublabel: string;
  // CSS var name (without `--`) to tint the card's active border + icon.
  accent: "brand-green" | "brand-blue" | "brand-orange" | "brand-purple" | "brand-red" | "brand-yellow";
  isActive: boolean;
  onClick: () => void;
}

function DocCard({ icon, label, sublabel, accent, isActive, onClick }: DocCardProps) {
  const accentColor = `hsl(var(--${accent}))`;
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ y: -1 }}
      className={cn(
        "group relative flex flex-col items-start gap-1.5 p-4 rounded-2xl border bg-card transition-all text-left",
        isActive ? "shadow-md border-transparent" : "border-border hover:border-foreground/20",
      )}
      style={isActive ? { borderColor: accentColor, boxShadow: `0 1px 0 0 ${accentColor}33` } : undefined}
    >
      {/* Accent dot top-right */}
      <span
        className="absolute top-3 right-3 w-2 h-2 rounded-full"
        style={{ backgroundColor: accentColor }}
      />
      <div
        className="transition-colors"
        style={{ color: isActive ? accentColor : undefined }}
      >
        {icon}
      </div>
      <span className="text-sm font-medium text-foreground">{label}</span>
      <span className="text-xs text-muted-foreground">{sublabel}</span>
    </motion.button>
  );
}
