"use client";

import { ArrowLeft } from "lucide-react";

import { Logo } from "./Logo";

interface PrivacyPageProps {
  onBack: () => void;
}

const LAST_UPDATED = "11 giugno 2026";

/**
 * Privacy informativa shown at /?view=privacy (route swap, not actual URL).
 * Content drafted to satisfy GDPR Art. 13 (information to data subjects) +
 * EU AI Act Art. 50 (AI disclosure). Should be reviewed by legal before
 * production launch — this is starter copy, not a finalized legal doc.
 */
export function PrivacyPage({ onBack }: PrivacyPageProps) {
  return (
    <div className="min-h-screen flex flex-col bg-background">
      <div aria-hidden className="h-[3px] bg-brand-strip" />
      <header className="sticky top-0 z-10 bg-background/95 backdrop-blur border-b border-border">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <button
            type="button"
            onClick={onBack}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Indietro</span>
          </button>
          <Logo className="h-5 w-auto" />
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <article className="max-w-3xl mx-auto px-6 py-10 space-y-8 text-foreground/90 leading-relaxed">
          <header className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">
              Informativa sulla privacy
            </h1>
            <p className="text-sm text-muted-foreground">Ultimo aggiornamento: {LAST_UPDATED}</p>
          </header>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">1. Chi siamo</h2>
            <p>
              Questo assistente è un servizio interno di Regalgrid (titolare del trattamento).
              Per esercitare i tuoi diritti come interessato puoi scriverci a{" "}
              <code className="text-xs bg-secondary px-1.5 py-0.5 rounded">
                privacy@regalgrid.com
              </code>
              .
            </p>
          </section>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">
              2. Quali dati raccogliamo
            </h2>
            <ul className="list-disc list-inside space-y-1.5 ml-2">
              <li>
                <strong>Account</strong>: indirizzo email, nome visualizzato, password
                (in forma di hash argon2id; non conserviamo mai la password in chiaro).
              </li>
              <li>
                <strong>Conversazioni</strong>: i messaggi che invii e le risposte
                generate, associati al tuo account.
              </li>
              <li>
                <strong>Log di audit</strong>: per ogni risposta registriamo la domanda,
                gli articoli normativi citati, il modello utilizzato e parametri tecnici
                (latenza, indirizzo IP, user-agent del browser).
              </li>
              <li>
                <strong>Token di sessione</strong>: salvati nel browser (localStorage)
                per mantenerti autenticato fra refresh.
              </li>
            </ul>
          </section>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">3. Perché trattiamo questi dati</h2>
            <ul className="list-disc list-inside space-y-1.5 ml-2">
              <li>
                <strong>Erogazione del servizio</strong> (base giuridica: esecuzione di
                un contratto / interesse legittimo).
              </li>
              <li>
                <strong>Accountability normativa</strong>: i log di audit garantiscono
                che ogni risposta sia tracciabile alle fonti citate. Base giuridica:
                obbligo legale + interesse legittimo a documentare le decisioni assistite
                da AI.
              </li>
              <li>
                <strong>Sicurezza</strong>: prevenzione di abusi, debugging,
                rate-limiting.
              </li>
            </ul>
          </section>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">4. Per quanto tempo conserviamo i dati</h2>
            <ul className="list-disc list-inside space-y-1.5 ml-2">
              <li>
                <strong>Conversazioni e messaggi</strong>: finché non li elimini dal
                pannello laterale, oppure finché non disattivi il tuo account.
              </li>
              <li>
                <strong>Log di audit</strong>: conservati per finalità di
                accountability normativa anche dopo l'eliminazione della conversazione
                originaria. L'associazione al tuo account viene rimossa (utente messo a
                null) ma il contenuto della domanda e degli articoli citati resta per
                la durata richiesta dalla normativa applicabile.
              </li>
            </ul>
          </section>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">5. AI e processi decisionali</h2>
            <p>
              Le risposte sono generate da modelli linguistici (OpenAI GPT-4.1-mini, embedding
              text-embedding-3-large) operanti sui regolamenti elettrici italiani ed europei
              indicizzati nel sistema. Conformemente all'art. 50 del Regolamento UE 2024/1689
              (AI Act) ti informiamo che:
            </p>
            <ul className="list-disc list-inside space-y-1.5 ml-2">
              <li>
                Stai interagendo con un sistema di intelligenza artificiale.
              </li>
              <li>
                Le risposte possono contenere errori. Verifica sempre con le fonti citate
                (articolo, paragrafo, pagina) prima di assumere decisioni legali o
                operative.
              </li>
              <li>
                Il sistema non sostituisce la consulenza di un esperto qualificato.
              </li>
            </ul>
          </section>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">6. I tuoi diritti</h2>
            <p>
              Ai sensi del GDPR puoi esercitare in qualunque momento:
            </p>
            <ul className="list-disc list-inside space-y-1.5 ml-2">
              <li>Accesso, rettifica, cancellazione (art. 15-17).</li>
              <li>Limitazione e opposizione (art. 18, 21).</li>
              <li>Portabilità (art. 20).</li>
              <li>
                Reclamo all'Autorità Garante per la protezione dei dati personali.
              </li>
            </ul>
            <p>
              Scrivici a{" "}
              <code className="text-xs bg-secondary px-1.5 py-0.5 rounded">
                privacy@regalgrid.com
              </code>{" "}
              indicando il diritto che intendi esercitare e l'email associata al tuo account.
            </p>
          </section>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">7. Messaggi vocali</h2>
            <p>
              Se utilizzi il microfono per dettare una domanda, la registrazione audio
              viene inviata a OpenAI esclusivamente per ottenerne la trascrizione in
              testo. Non conserviamo la registrazione audio: una volta ottenuto il
              testo, l'audio viene scartato dal nostro sistema. La trascrizione viene
              poi trattata come una normale domanda scritta (vedi sezione 2).
            </p>
            <p>
              Avrai sempre la possibilità di rivedere e modificare la trascrizione
              prima di inviarla all'assistente. La prima volta che utilizzi il
              microfono ti chiediamo un consenso esplicito all'invio dell'audio a
              OpenAI per la trascrizione.
            </p>
          </section>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">8. Trasferimenti extra-UE</h2>
            <p>
              Per generare le risposte, le tue domande e gli estratti dei documenti
              indicizzati vengono inviati ai modelli di OpenAI, le cui API possono
              comportare un trasferimento al di fuori dell'Unione Europea. OpenAI
              aderisce al EU-US Data Privacy Framework. Non condividiamo dati con altri
              fornitori terzi.
            </p>
          </section>

          <section className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold text-foreground">9. Modifiche all'informativa</h2>
            <p>
              Aggiorniamo questa pagina quando cambiamo trattamenti o fornitori. La data
              di ultimo aggiornamento è indicata in cima. Per modifiche sostanziali ti
              avviseremo via email.
            </p>
          </section>
        </article>
      </main>
    </div>
  );
}
