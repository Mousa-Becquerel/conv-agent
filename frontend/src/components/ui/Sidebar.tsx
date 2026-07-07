"use client";

import { motion } from "framer-motion";
import {
  LogOut,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PenSquare,
  Trash2,
} from "lucide-react";

import { Logo } from "./Logo";
import { cn } from "@/lib/utils";

// Minimal shape the sidebar needs — kept loose so we can pass either the
// server `ConversationSummary` or a normalized local shape.
export interface SidebarConversation {
  id: string;
  title: string;
}

interface SidebarProps {
  conversations: SidebarConversation[]; // expected pre-sorted (newest first)
  activeId: string | null;
  open: boolean;
  onToggle: () => void;
  onNewConversation: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  userEmail?: string;
  onLogout?: () => void;
}

const SIDEBAR_WIDTH = 280;
const RAIL_WIDTH = 56;

export function Sidebar(props: SidebarProps) {
  return props.open ? <ExpandedSidebar {...props} /> : <CollapsedRail {...props} />;
}

// ---------- Collapsed (icon rail) ----------
function CollapsedRail({ onToggle, onNewConversation }: SidebarProps) {
  return (
    <aside
      className="hidden md:flex h-screen flex-col items-center py-4 border-r border-border bg-secondary/40 shrink-0"
      style={{ width: RAIL_WIDTH }}
    >
      <button
        type="button"
        onClick={onToggle}
        title="Apri pannello"
        className="p-2 rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground"
      >
        <PanelLeftOpen className="w-4 h-4" />
      </button>
      <button
        type="button"
        onClick={onNewConversation}
        title="Nuova conversazione"
        className="p-2 mt-2 rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground"
      >
        <PenSquare className="w-4 h-4" />
      </button>
    </aside>
  );
}

// ---------- Expanded panel ----------
function ExpandedSidebar({
  conversations,
  activeId,
  onToggle,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
  userEmail,
  onLogout,
}: SidebarProps) {
  return (
    <motion.aside
      initial={{ width: 0, opacity: 0 }}
      animate={{ width: SIDEBAR_WIDTH, opacity: 1 }}
      transition={{ duration: 0.18 }}
      className="hidden md:flex h-screen flex-col border-r border-border bg-secondary/40 shrink-0 overflow-hidden"
    >
      {/* Header: brand on the left, collapse toggle on the right */}
      <div className="flex items-center justify-between px-4 py-4">
        <Logo className="h-4 w-auto" />
        <button
          type="button"
          onClick={onToggle}
          title="Riduci pannello"
          className="p-1.5 rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground"
        >
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>

      {/* New conversation */}
      <div className="px-3 pb-3">
        <button
          type="button"
          onClick={onNewConversation}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-card border border-border hover:border-foreground/20 hover:shadow-sm transition-all text-sm text-foreground"
        >
          <PenSquare className="w-4 h-4 text-muted-foreground" />
          <span>Nuova conversazione</span>
        </button>
      </div>

      {/* Recent conversations list */}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        <div className="text-[11px] uppercase tracking-wide text-muted-foreground px-2 mb-1.5">
          Recenti
        </div>
        {conversations.length === 0 ? (
          <div className="px-2 py-1.5 text-xs text-muted-foreground">
            Nessuna conversazione
          </div>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <ConversationRow
                key={c.id}
                conv={c}
                isActive={c.id === activeId}
                onSelect={() => onSelectConversation(c.id)}
                onDelete={() => onDeleteConversation(c.id)}
              />
            ))}
          </ul>
        )}
      </div>

      {/* Footer: user identity + logout */}
      <div className="border-t border-border px-3 py-3">
        {userEmail ? (
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Account
              </div>
              <div className="text-xs text-foreground/90 truncate" title={userEmail}>
                {userEmail}
              </div>
            </div>
            {onLogout && (
              <button
                type="button"
                onClick={onLogout}
                title="Esci"
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex-shrink-0"
              >
                <LogOut className="w-4 h-4" />
              </button>
            )}
          </div>
        ) : (
          <div className="text-[11px] text-muted-foreground flex items-center justify-between">
            <span>Assistente normativo</span>
            <span className="font-medium text-foreground/70">v0.1</span>
          </div>
        )}
      </div>
    </motion.aside>
  );
}

// ---------- Conversation row ----------
interface RowProps {
  conv: SidebarConversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

function ConversationRow({ conv, isActive, onSelect, onDelete }: RowProps) {
  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
          }
        }}
        className={cn(
          "group flex items-center gap-2 pl-2 pr-1 py-1.5 rounded-md cursor-pointer text-sm transition-colors",
          isActive
            ? "bg-card border border-border text-foreground"
            : "text-foreground/80 hover:bg-secondary",
        )}
      >
        <MessageSquare className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
        <span className="flex-1 truncate" title={conv.title}>
          {conv.title}
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          title="Elimina"
          className={cn(
            "p-1 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors",
            isActive ? "opacity-70" : "opacity-0 group-hover:opacity-100",
          )}
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </li>
  );
}
