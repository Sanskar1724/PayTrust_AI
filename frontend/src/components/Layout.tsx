import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity, BookOpen, Bot, BrainCircuit, ClipboardCheck, FlaskConical, LayoutDashboard, LogOut, Menu,
  ReceiptText, ScrollText, ShieldCheck, Store, Swords, Users,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useLive } from "../lib/live";
import type { Stats } from "../lib/types";

interface Item { to: string; label: string; icon: ReactNode; badge?: number }

export function Layout() {
  const { operator, logout, can } = useAuth();
  const { connected } = useLive();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => api<Stats>("/v1/stats"), refetchInterval: 30_000 });
  const pending = stats.data?.pending_approvals ?? 0;

  const sections: { title: string; items: Item[] }[] = [
    {
      title: "Monitor",
      items: [
        { to: "/", label: "Overview", icon: <LayoutDashboard className="size-4" /> },
        { to: "/payments", label: "Payments", icon: <ReceiptText className="size-4" /> },
        { to: "/approvals", label: "Approvals", icon: <ClipboardCheck className="size-4" />, badge: pending },
      ],
    },
    {
      title: "Test",
      items: [
        { to: "/playground", label: "Playground", icon: <FlaskConical className="size-4" /> },
        { to: "/arena", label: "Agent Arena", icon: <Swords className="size-4" /> },
        { to: "/model", label: "ML model", icon: <BrainCircuit className="size-4" /> },
      ],
    },
    {
      title: "Configure",
      items: [
        { to: "/policies", label: "Policies", icon: <ShieldCheck className="size-4" /> },
        { to: "/agents", label: "Agents & keys", icon: <Bot className="size-4" /> },
        { to: "/directory", label: "Users & merchants", icon: <Store className="size-4" /> },
        ...(can("admin") ? [{ to: "/team", label: "Team", icon: <Users className="size-4" /> }] : []),
        { to: "/audit", label: "Audit log", icon: <ScrollText className="size-4" /> },
      ],
    },
  ];

  const nav = (
    <nav className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <img src="/logo.svg" alt="" className="size-8" />
        <div>
          <div className="text-sm font-semibold text-white">PayTrust AI</div>
          <div className="text-[11px] text-slate-400">Agent payment control</div>
        </div>
      </div>
      <div className="flex-1 space-y-6 overflow-y-auto px-3 pb-4">
        {sections.map((section) => (
          <div key={section.title}>
            <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{section.title}</div>
            <ul className="space-y-0.5">
              {section.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/"}
                    onClick={() => setOpen(false)}
                    className={({ isActive }) => clsx(
                      "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition",
                      isActive ? "bg-white/10 font-medium text-white" : "text-slate-400 hover:bg-white/5 hover:text-slate-100",
                    )}
                  >
                    {item.icon}
                    <span className="flex-1">{item.label}</span>
                    {!!item.badge && (
                      <span className="rounded-full bg-amber-400 px-1.5 text-[11px] font-semibold text-amber-950">{item.badge}</span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-white/10 p-3">
        <a href="/docs" target="_blank" rel="noreferrer" className="mb-2 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-slate-400 hover:bg-white/5 hover:text-slate-100">
          <BookOpen className="size-4" /> API docs
        </a>
        <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-2">
          <div className="flex size-8 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white">
            {operator?.name.slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm text-slate-100">{operator?.name}</div>
            <div className="truncate text-[11px] capitalize text-slate-500">{operator?.role}</div>
          </div>
          <button onClick={logout} className="rounded-md p-1.5 text-slate-400 hover:bg-white/10 hover:text-white" title="Sign out">
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:pl-64">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 bg-ink lg:block">{nav}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-slate-900/50" />
          <aside className="absolute inset-y-0 left-0 w-64 bg-ink" onClick={(e) => e.stopPropagation()}>{nav}</aside>
        </div>
      )}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/85 px-4 backdrop-blur sm:px-8">
        <button className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
          <Menu className="size-5" />
        </button>
        <div className="flex-1" />
        <div className="flex items-center gap-2 text-xs text-slate-500" title={connected ? "Receiving live decisions" : "Reconnecting to live feed"}>
          <Activity className={clsx("size-3.5", connected ? "text-emerald-500" : "text-slate-400")} />
          <span className={clsx("size-2 rounded-full", connected ? "bg-emerald-500" : "bg-slate-300")} />
          {connected ? "Live" : "Offline"}
        </div>
      </header>
      <main key={location.pathname} className="mx-auto max-w-7xl px-4 py-8 sm:px-8">
        <Outlet />
      </main>
    </div>
  );
}
