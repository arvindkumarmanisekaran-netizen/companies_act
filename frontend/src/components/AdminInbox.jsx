import React, { useEffect, useMemo, useState } from "react";
import { Inbox, Search, X } from "lucide-react";

const apiBaseUrl = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

const headersFor = (adminName) => ({
  Accept: "application/json",
  "Content-Type": "application/json",
  "X-Admin-Name": adminName,
});

export default function AdminInbox({ adminName, onClose, onChanged }) {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/admin/feedback`, { credentials: "include", headers: headersFor(adminName) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `Inbox failed (${response.status})`);
      setItems(payload.results || []);
      setSelected((current) => payload.results?.find((item) => item.id === current?.id) || payload.results?.[0] || null);
      onChanged?.(payload.unread || 0);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [adminName]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return query ? items.filter((item) => `${item.sender_name} ${item.message}`.toLowerCase().includes(query)) : items;
  }, [items, search]);

  const openMessage = async (item) => {
    setSelected(item);
    if (item.read_at) return;
    try {
      const response = await fetch(`${apiBaseUrl}/api/admin/feedback/${item.id}/read`, { method: "POST", credentials: "include", headers: headersFor(adminName) });
      if (!response.ok) throw new Error("Could not mark feedback as read");
      const next = items.map((entry) => entry.id === item.id ? { ...entry, read_at: new Date().toISOString() } : entry);
      setItems(next);
      onChanged?.(next.filter((entry) => !entry.read_at).length);
    } catch (readError) {
      setError(readError.message);
    }
  };

  return <div className="fixed inset-0 z-[90] flex bg-slate-950/60 p-2 backdrop-blur-sm sm:p-4" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="m-auto flex h-[92dvh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2"><Inbox size={20} className="text-blue-950"/><div><h2 className="font-extrabold text-slate-900">Feedback inbox</h2><p className="text-xs text-slate-500">Messages delivered to {adminName}</p></div></div>
        <button type="button" onClick={onClose} className="grid size-9 place-items-center rounded-lg hover:bg-slate-100" aria-label="Close inbox"><X size={19}/></button>
      </header>
      <label className="relative border-b border-slate-200 p-3"><Search size={16} className="absolute left-6 top-1/2 -translate-y-1/2 text-slate-400"/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search sender or message" className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm outline-none focus:border-blue-700"/></label>
      {error && <p className="bg-red-50 px-4 py-2 text-xs font-semibold text-red-700">{error}</p>}
      <div className="grid min-h-0 flex-1 md:grid-cols-[19rem_1fr]">
        <aside className="min-h-0 overflow-y-auto border-r border-slate-200 bg-slate-50">
          {loading ? <p className="p-5 text-sm text-slate-500">Loading feedback…</p> : filtered.length ? filtered.map((item) => <button key={item.id} type="button" onClick={() => openMessage(item)} className={`block w-full border-b border-slate-200 px-4 py-3 text-left ${selected?.id === item.id ? "bg-blue-50" : "hover:bg-white"}`}>
            <span className="flex items-center gap-2"><strong className="min-w-0 flex-1 truncate text-sm text-slate-900">{item.sender_name}</strong>{!item.read_at && <span className="size-2 shrink-0 rounded-full bg-blue-700"/>}</span>
            <span className="mt-1 block line-clamp-2 text-xs leading-5 text-slate-600">{item.message}</span>
            <span className="mt-1 block text-[10px] text-slate-400">{new Date(item.created_at).toLocaleString()}</span>
          </button>) : <p className="p-5 text-sm text-slate-500">No feedback messages.</p>}
        </aside>
        <main className="min-h-0 overflow-y-auto p-5">
          {selected ? <article><div className="mb-4 border-b border-slate-200 pb-3"><h3 className="text-lg font-extrabold text-slate-900">{selected.sender_name}</h3><p className="text-xs text-slate-500">{new Date(selected.created_at).toLocaleString()} · {selected.source}</p></div><p className="whitespace-pre-wrap text-[15px] leading-7 text-slate-800">{selected.message}</p>{selected.context_url && <p className="mt-5 break-all border-t border-slate-200 pt-3 text-xs text-slate-500">Sent from: {selected.context_url}</p>}</article> : <div className="grid h-full place-items-center text-sm text-slate-400">Select a feedback message</div>}
        </main>
      </div>
    </section>
  </div>;
}
