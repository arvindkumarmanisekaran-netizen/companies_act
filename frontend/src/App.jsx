import React, { useState, useEffect, useCallback } from "react";
import ActViewer from "./components/ActViewer";
import AdminApp from "./AdminApp";
import { forgetUser, getRememberedUser, rememberUser } from "./userSession";
import { captureEvent, resetAnalytics, setReaderName, startActiveTimeTracking } from "./analytics";

const ADMIN_NAMES = new Set(["arv@momo", "nak@momo"]);
const todayIso = () => new Date().toISOString().slice(0, 10);

function UserLogin({ onLogin }) {
  const [name, setName] = useState("");
  return <main className="admin-login-shell"><section className="admin-login-card">
    <div className="admin-mark">CA</div><p className="admin-eyebrow">Companies Act, 2013</p>
    <h1>Welcome</h1><p className="admin-muted">Enter your name to continue. No password is required.</p>
    <form onSubmit={(event) => { event.preventDefault(); const saved = rememberUser(name); if (saved) { setReaderName(saved); captureEvent("reader_signed_in"); onLogin(saved); } }} className="admin-form">
      <label>Your name<input autoFocus autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} required maxLength={100}/></label>
      <button className="admin-primary">Continue</button>
    </form>
  </section></main>;
}

function PublicApp({ userName, onLogout }) {
  const [actData, setActData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const asOfDate = todayIso();

  useEffect(() => startActiveTimeTracking(), []);

  const fetchActData = useCallback(() => {
    setLoading(true);
    setError(null);

    // Vite environment variable replacement for PUBLIC_URL
    const baseUrl = import.meta.env.BASE_URL.replace(/\/$/, "");
    const jsonPath = `${baseUrl}/docs/sections_master.json`;

    fetch(jsonPath, {
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
    })
      .then(async (res) => {
        const contentType = res.headers.get("content-type");

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }

        if (!contentType || !contentType.includes("application/json")) {
          throw new Error(
            `Expected JSON, got ${contentType || "unknown content-type"}. Check if public/docs/sections_master.json exists.`,
          );
        }

        return res.json();
      })
      .then((data) => {
        setActData(data);
        captureEvent("reader_ready", { chapter_count: data?.chapters?.length || 0 });
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load sections master:", err);
        setError(err.message);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchActData();
  }, [fetchActData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="flex items-center gap-3 text-gray-600 font-medium">
          <svg
            className="animate-spin h-5 w-5 text-blue-900"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            ></circle>
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            ></path>
          </svg>
          Loading Act Master Data...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="p-6 bg-red-50 border border-red-200 text-red-700 rounded-lg max-w-lg shadow-sm">
          <h2 className="text-lg font-semibold mb-2">Data Load Failure</h2>
          <p className="text-sm font-mono bg-red-100 p-2.5 rounded border border-red-200 mb-4 break-words">
            {error}
          </p>
          <button
            onClick={fetchActData}
            className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white font-medium text-sm rounded transition-colors"
          >
            Retry Loading
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Navigation Header */}
      <header className="sticky top-0 z-40 hidden h-14 items-center justify-between gap-3 bg-blue-950 px-4 text-white shadow-md sm:h-16 sm:px-6 md:flex">
        <h1 className="min-w-0 truncate text-sm font-bold tracking-wide sm:text-lg">
          {actData?.act_title || "THE COMPANIES ACT, 2013"}
        </h1>
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <span className="max-w-40 truncate text-xs font-semibold text-blue-100">{userName}</span>
          <button type="button" onClick={onLogout} className="rounded border border-blue-700 px-2.5 py-1 text-xs font-bold hover:bg-blue-900">Logout</button>
          <span className="rounded border border-blue-700 bg-blue-900 px-2.5 py-1 font-mono text-xs">
            {actData?.doc_type ? actData.doc_type.toUpperCase() : "MASTER OUTPUT"}
          </span>
        </div>
      </header>

      {/* Main View */}
      <main>
        <ActViewer data={actData} asOfDate={asOfDate} userName={userName} onLogout={onLogout} />
      </main>
    </div>
  );
}

function App() {
  const [userName, setUserName] = useState(getRememberedUser);
  const adminPath = window.location.pathname === "/admin" || window.location.pathname.startsWith("/admin/");
  const isAdmin = adminPath || ADMIN_NAMES.has(userName.trim().toLowerCase());
  useEffect(() => {
    const normalized = userName.trim().toLowerCase();
    setReaderName(userName);
    window.CompaniesActNative?.setAdminName(ADMIN_NAMES.has(normalized) ? normalized : "");
  }, [userName, isAdmin]);
  if (isAdmin) return <AdminApp />;
  if (!userName) return <UserLogin onLogin={setUserName}/>;
  return <PublicApp userName={userName} onLogout={() => { captureEvent("reader_signed_out"); forgetUser(); resetAnalytics(); setUserName(""); }}/>
}

export default App;
