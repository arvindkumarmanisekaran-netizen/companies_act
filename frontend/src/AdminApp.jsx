import React, { useCallback, useEffect, useRef, useState } from "react";
import { FileText, History, Inbox, LogOut, Search, ShieldCheck, Trash2, X } from "lucide-react";
import ActViewer from "./components/ActViewer";
import AdminInbox from "./components/AdminInbox";
import { forgetUser, getRememberedUser } from "./userSession";

const apiBaseUrl = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const todayIso = () => new Date().toISOString().slice(0, 10);

async function api(path, options = {}) {
  const adminName = getRememberedUser().trim().toLowerCase();
  const response = await fetch(`${apiBaseUrl}${path}`, { credentials: "include", ...options, headers: { "Content-Type": "application/json", "X-Admin-Name": adminName, ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function AdminViewer({ user, onLogout }) {
  const [actData, setActData] = useState(null); const [error, setError] = useState("");
  const asOfDate = todayIso();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pdfLibraryOpen, setPdfLibraryOpen] = useState(false);
  const [inboxOpen, setInboxOpen] = useState(false);
  const [unreadFeedback, setUnreadFeedback] = useState(0);
  const load = useCallback(() => {
    const base = import.meta.env.BASE_URL.replace(/\/$/, "");
    fetch(`${base}/docs/sections_master.json`).then((r) => { if (!r.ok) throw new Error(`Unable to load the Act (${r.status})`); return r.json(); }).then(setActData).catch((err) => setError(err.message));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    let active = true;
    const refreshUnread = () => api("/api/admin/feedback?limit=500").then((data) => {
      if (active) setUnreadFeedback(data.unread || 0);
    }).catch(() => {});
    refreshUnread();
    const timer = window.setInterval(refreshUnread, 5000);
    const refreshWhenVisible = () => { if (document.visibilityState === "visible") refreshUnread(); };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshUnread);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshUnread);
    };
  }, []);
  if (error) return <div className="p-8 text-red-700">{error}</div>;
  if (!actData) return <div className="grid h-screen place-items-center text-slate-500">Loading Act content…</div>;
  return <div className="min-h-screen bg-slate-50">
    <header className="sticky top-0 z-40 flex h-14 items-center justify-between gap-3 bg-blue-950 px-4 text-white shadow-md sm:h-16 sm:px-6">
      <h1 className="min-w-0 truncate text-sm font-bold tracking-wide sm:text-lg"><span className="sm:hidden">Admin</span><span className="hidden sm:inline">{actData.act_title || "THE COMPANIES ACT, 2013"}</span></h1>
      <div className="flex shrink-0 items-center gap-1.5 text-xs sm:gap-2"><span className="hidden items-center gap-1 md:flex"><ShieldCheck size={15}/>{user.username}</span><button aria-label="Open PDF library" onClick={() => setPdfLibraryOpen(true)} className="inline-flex items-center gap-1 rounded border border-blue-700 p-2 hover:bg-blue-900 sm:px-2.5 sm:py-1.5"><FileText size={16}/><span className="hidden sm:inline">PDFs</span></button><button aria-label="Open inbox" onClick={() => setInboxOpen(true)} className="relative inline-flex items-center gap-1 rounded border border-blue-700 p-2 hover:bg-blue-900 sm:px-2.5 sm:py-1.5"><Inbox size={16}/><span className="hidden sm:inline">Inbox</span>{unreadFeedback > 0 && <span className="absolute -right-1.5 -top-1.5 rounded-full bg-red-500 px-1.5 py-0.5 text-[9px] font-extrabold text-white sm:static">{unreadFeedback}</span>}</button><button aria-label="Open edit history" onClick={() => setHistoryOpen(true)} className="inline-flex items-center gap-1 rounded border border-blue-700 p-2 hover:bg-blue-900 sm:px-2.5 sm:py-1.5"><History size={16}/><span className="hidden sm:inline">History</span></button><button aria-label="Logout" onClick={onLogout} className="inline-flex items-center gap-1 rounded border border-blue-700 p-2 hover:bg-blue-900 sm:px-2.5 sm:py-1.5"><LogOut size={16}/><span className="hidden sm:inline">Logout</span></button></div>
    </header>
    <ActViewer data={actData} asOfDate={asOfDate} adminMode userName={user.username} onLogout={onLogout}/>
    {historyOpen && <AdminHistory username={user.username} onClose={() => setHistoryOpen(false)}/>}
    {pdfLibraryOpen && <PdfLibrary onClose={() => setPdfLibraryOpen(false)}/>} 
    {inboxOpen && <AdminInbox adminName={user.username} onClose={() => setInboxOpen(false)} onChanged={setUnreadFeedback}/>} 
  </div>;
}

function PdfLibrary({ onClose }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const requestSequence = useRef(0);
  const load = useCallback(() => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setItems([]);
    return api(`/api/admin/pdfs?q=${encodeURIComponent(query)}`)
      .then((data) => {
        if (sequence !== requestSequence.current) return;
        const results = data.results || [];
        results.sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || "")) || String(right.id).localeCompare(String(left.id)));
        setItems(results);
      })
      .catch((error) => { if (sequence === requestSequence.current) setMessage(error.message); })
      .finally(() => { if (sequence === requestSequence.current) setLoading(false); });
  }, [query]);
  useEffect(() => { const timer = window.setTimeout(load, 180); return () => window.clearTimeout(timer); }, [load]);
  const remove = async (item) => { if (!window.confirm(`Remove the PDF attached to “${item.title}”?`)) return; try { await api(`/api/admin/documents/${encodeURIComponent(item.id)}/pdf`, { method: "DELETE" }); setMessage("PDF removed."); await load(); } catch (error) { setMessage(error.message); } };
  const insert = async (event) => { const file = event.target.files?.[0]; event.target.value = ""; if (!file) return; try { const title = file.name.replace(/\.pdf$/i, "").replace(/[_-]+/g, " "); await api("/api/admin/pdfs", { method: "POST", headers: { "Content-Type": "application/pdf", "X-Filename": file.name, "X-Title": title, "X-Instrument-Type": "rules" }, body: file }); setMessage("PDF inserted into the library."); await load(); } catch (error) { setMessage(error.message); } };
  return <div className="fixed inset-0 z-[80] flex bg-slate-950/60 p-3 backdrop-blur-sm"><section className="m-auto flex h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"><header className="flex items-center justify-between border-b px-4 py-3"><div><h2 className="font-bold">PDF library</h2><p className="text-xs text-slate-500">View and remove PDFs attached to Rules and Notifications.</p></div><button onClick={onClose} className="grid size-9 place-items-center rounded hover:bg-slate-100"><X size={19}/></button></header><div className="flex gap-2 border-b bg-slate-50 p-3"><div className="relative min-w-0 flex-1"><Search size={15} className="absolute left-2 top-2.5 text-slate-400"/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title or filename" className="w-full rounded border px-8 py-2 text-sm"/></div><label className="inline-flex cursor-pointer items-center rounded bg-emerald-700 px-3 py-2 text-xs font-bold text-white">Insert PDF<input type="file" accept="application/pdf,.pdf" onChange={insert} className="hidden" /></label><button type="button" onClick={load} className="rounded bg-blue-950 px-3 py-2 text-xs font-bold text-white">Refresh</button></div>{message && <p className="px-4 pt-3 text-xs font-semibold text-blue-800">{message}</p>}<div className="min-h-0 flex-1 overflow-y-auto p-4">{loading ? <p className="text-sm text-slate-500">Loading PDFs…</p> : items.length ? <div className="grid gap-2">{items.map((item) => <div key={item.id} className="flex items-center gap-3 overflow-hidden rounded-lg border border-slate-200 p-3"><FileText className="shrink-0 text-blue-800" size={20}/><div className="min-w-0 flex-1"><strong className="block truncate text-sm">{item.source_category === "custom" && item.updated_at ? `${new Date(item.updated_at).toISOString().slice(0, 10)} — ` : ""}{item.source_file || item.source_path?.split("/").pop() || item.title}</strong><span className="block truncate text-xs text-slate-500">{item.source_file || item.source_path?.split("/").pop() || item.title}</span><span className="text-[11px] uppercase text-slate-400">{item.instrument_type}</span></div><div className="sticky right-0 z-10 flex shrink-0 items-center gap-2 border-l border-slate-200 bg-white pl-3"><a href={`${apiBaseUrl}/api/documents/${encodeURIComponent(item.id)}/pdf?download=true`} target="_blank" rel="noreferrer" className="rounded border px-2 py-1 text-xs font-bold text-blue-800" title="Download PDF">Download PDF</a><button type="button" onClick={() => remove(item)} className="rounded border border-red-200 p-2 text-red-700" aria-label={`Delete PDF ${item.source_file || item.title}`} title="Delete PDF"><Trash2 size={15}/></button></div></div>)}</div> : <div className="rounded border border-dashed p-8 text-center text-sm text-slate-500">No attached PDFs found.</div>}</div></section></div>;
}

function AdminHistory({ username, onClose }) {
  const [items, setItems] = useState([]), [selected, setSelected] = useState(null);
  const [search, setSearch] = useState(""), [field, setField] = useState(""), [section, setSection] = useState("");
  const [message, setMessage] = useState("");
  const load = () => api("/api/admin/history").then((data) => { setItems(data.results); setSelected((s) => data.results.find((x) => x.id === s?.id) || data.results[0] || null); });
  useEffect(() => { load(); }, []);
  const filtered = items.filter((x) => { const hay = `${x.section_number} ${x.label} ${x.provision_id} ${JSON.stringify(x.old_value)} ${JSON.stringify(x.new_value)}`.toLowerCase(); return (!search || hay.includes(search.toLowerCase())) && (!field || (field === "callout" ? x.field_name.startsWith("callout_") : field === "context_reference" ? x.field_name.startsWith("context_reference_") : x.field_name === field)) && (!section || String(x.section_number) === section); });
  useEffect(() => {
    setSelected((current) => filtered.find((item) => item.id === current?.id) || filtered[0] || null);
    setMessage("");
    }, [search, field, section, items]);
  const act = async (kind) => { try { const path = selected.revision_kind === "callout" ? `/api/admin/callout-revisions/${String(selected.id).replace("callout-", "")}/${kind}` : selected.revision_kind === "context_reference" ? `/api/admin/context-reference-revisions/${String(selected.id).replace("context-", "")}/${kind}` : `/api/admin/revisions/${selected.id}/${kind}`; await api(path, { method: "POST" }); setMessage(kind === "undo" ? "Revision undone." : "Revision restored."); await load(); } catch (error) { setMessage(error.message); } };
  const printable = (value) => typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : String(value ?? "");
  const oldLines = printable(selected?.old_value).split("\n"), newLines = printable(selected?.new_value).split("\n");
  return <div className="fixed inset-0 z-[70] flex bg-slate-950/60 p-3 backdrop-blur-sm"><section className="m-auto flex h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
    <header className="flex items-center justify-between border-b px-4 py-3"><div><h2 className="font-bold">Edit history</h2><p className="text-xs text-slate-500">Changes made by {username}</p></div><button onClick={onClose} className="grid size-9 place-items-center rounded hover:bg-slate-100"><X size={19}/></button></header>
    <div className="grid grid-cols-2 gap-2 border-b bg-slate-50 p-3 md:grid-cols-4"><input placeholder="Search changes…" value={search} onChange={(e) => setSearch(e.target.value)} className="rounded border px-2 py-1.5 text-xs"/><input placeholder="Section" value={section} onChange={(e) => setSection(e.target.value)} className="rounded border px-2 py-1.5 text-xs"/><select value={field} onChange={(e) => setField(e.target.value)} className="rounded border px-2 py-1.5 text-xs"><option value="">All fields</option><option value="current_text">Text</option><option value="title">Title</option><option value="status">Status</option><option value="callout">Callouts and bulb notes</option><option value="context_reference">Hover popups</option></select><button type="button" onClick={() => { setSearch(""); setSection(""); setField(""); }} disabled={!search && !section && !field} className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-100 disabled:opacity-40">Clear filters</button></div>
    <div className="grid min-h-0 flex-1 md:grid-cols-[20rem_1fr]"><aside className="overflow-y-auto border-r bg-slate-50">{filtered.length ? filtered.map((x) => <button key={x.id} onClick={() => { setSelected(x); setMessage(""); }} className={`block w-full border-b px-4 py-3 text-left ${selected?.id === x.id ? "bg-blue-50" : "hover:bg-white"}`}><strong className="block text-sm">Section {x.section_number} · {x.label}</strong><span className="block text-xs text-slate-500">{x.field_name.replace("_", " ")} · {new Date(x.created_at).toLocaleString()}</span><span className="text-[11px] text-blue-700">effective {x.effective_date || "all dates"}</span></button>) : <p className="p-5 text-sm text-slate-500">No matching edits.</p>}</aside>
      <main className="min-w-0 overflow-auto bg-slate-950 p-4 font-mono text-xs text-slate-200">{selected && <><div className="mb-3 border-b border-slate-700 pb-3 text-slate-400"><div className="mb-2 flex gap-2"><button disabled={selected.undone_by_revision_id || selected.reverts_revision_id} onClick={() => act("undo")} className="rounded bg-amber-600 px-3 py-1.5 font-sans font-bold text-white disabled:opacity-40">Undo this change</button><button disabled={!selected.undone_by_revision_id || selected.reverts_revision_id} onClick={() => act("redo")} className="rounded bg-emerald-700 px-3 py-1.5 font-sans font-bold text-white disabled:opacity-40">Redo this change</button></div>{message && <div className="mb-2 text-cyan-300">{message}</div>}<div className="text-amber-300">revision {selected.id}</div><div>--- {selected.provision_id}@before</div><div>+++ {selected.provision_id}@{selected.effective_date || "current"}</div></div>{oldLines.map((line, i) => line !== newLines[i] && <div key={`o${i}`} className="whitespace-pre-wrap bg-red-950 px-2 py-0.5 text-red-200">- {line || " "}</div>)}{newLines.map((line, i) => line !== oldLines[i] && <div key={`n${i}`} className="whitespace-pre-wrap bg-emerald-950 px-2 py-0.5 text-emerald-200">+ {line || " "}</div>)}</>}</main>
    </div></section></div>;
}

export default function AdminApp() {
  const [user, setUser] = useState(undefined);
  useEffect(() => {
    const remembered = getRememberedUser().trim().toLowerCase();
    api("/api/admin/me").then(setUser).catch(async () => {
      if (remembered !== "arv@momo" && remembered !== "nak@momo") {
        window.location.replace("/");
        return;
      }
      try {
        setUser(await api("/api/admin/login", { method: "POST", body: JSON.stringify({ username: remembered }) }));
        window.history.replaceState({}, "", "/admin");
      } catch {
        window.location.replace("/");
      }
    });
  }, []);
  if (user === undefined) return <main className="admin-login-shell"><div className="admin-muted">Checking session…</div></main>;
  return <AdminViewer user={user} onLogout={async () => {
    window.CompaniesActNative?.setAdminName("");
    await api("/api/admin/logout", { method: "POST" }).catch(() => {});
    forgetUser();
    window.location.replace("/");
  }}/>;
}
