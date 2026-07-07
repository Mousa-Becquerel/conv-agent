"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Loader2, LogIn } from "lucide-react";

import { Logo } from "./Logo";
import { cn } from "@/lib/utils";
import { AuthError, login } from "@/lib/auth";
import type { User } from "@/types";

interface LoginScreenProps {
  onLoggedIn: (user: User) => void;
  onOpenPrivacy: () => void;
}

export function LoginScreen({ onLoggedIn, onOpenPrivacy }: LoginScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      const user = await login(email, password);
      onLoggedIn(user);
    } catch (err) {
      if (err instanceof AuthError) {
        setError(err.message);
      } else {
        setError("Errore di rete. Riprova.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-background relative">
      <div
        aria-hidden
        className="absolute inset-0 bg-grid-dots opacity-60 [mask-image:linear-gradient(to_bottom,white_0%,white_55%,transparent_100%)]"
      />
      <div aria-hidden className="h-[3px] bg-brand-strip relative z-10" />

      <header className="relative z-10 px-6 py-4">
        <Logo className="h-5 w-auto" />
      </header>

      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 py-10">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="w-full max-w-md"
        >
          <div className="text-center mb-8">
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">
              Accedi<span className="text-primary">.</span>
            </h1>
            <p className="text-sm text-muted-foreground mt-2">
              Assistente normativo per i regolamenti elettrici italiani ed europei.
            </p>
          </div>

          <form
            onSubmit={handleSubmit}
            className="bg-card border border-border rounded-2xl shadow-sm p-6 space-y-4"
          >
            <label className="block">
              <span className="block text-xs uppercase tracking-wide text-muted-foreground mb-1.5">
                Email
              </span>
              <input
                type="email"
                required
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-primary/40 transition-colors disabled:opacity-50"
                placeholder="nome@regalgrid.com"
              />
            </label>

            <label className="block">
              <span className="block text-xs uppercase tracking-wide text-muted-foreground mb-1.5">
                Password
              </span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-primary/40 transition-colors disabled:opacity-50"
              />
            </label>

            {error && (
              <div
                role="alert"
                className="text-sm text-destructive bg-destructive/5 border border-destructive/20 rounded-md px-3 py-2"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting || !email || !password}
              className={cn(
                "w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all",
                submitting || !email || !password
                  ? "bg-secondary text-muted-foreground cursor-not-allowed"
                  : "bg-primary text-primary-foreground hover:opacity-90 shadow-sm",
              )}
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Accesso in corso…</span>
                </>
              ) : (
                <>
                  <LogIn className="w-4 h-4" />
                  <span>Accedi</span>
                </>
              )}
            </button>
          </form>

          <div className="text-center mt-4 text-xs text-muted-foreground">
            Accesso su invito. Per richiedere un account contatta l'amministratore.
          </div>
        </motion.div>
      </main>

      <footer className="relative z-10 px-6 py-4 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>
          Le risposte sono generate da un sistema AI. Verifica sempre con le fonti citate prima di
          prendere decisioni legali o operative.
        </span>
        <button
          type="button"
          onClick={onOpenPrivacy}
          className="underline hover:text-foreground transition-colors"
        >
          Privacy
        </button>
      </footer>
    </div>
  );
}
