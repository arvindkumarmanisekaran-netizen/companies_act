import React, { useCallback, useEffect, useRef, useState } from "react";
import ActViewer from "./components/ActViewer";
import TimelineControls from "./components/TimelineControls";

const apiJson = async (url, signal) => {
  const response = await fetch(url, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`HTTP ${response.status}: ${detail || response.statusText}`);
  }
  return response.json();
};

function App() {
  const [meta, setMeta] = useState(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [actData, setActData] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);

  const loadMeta = useCallback(async () => {
    setError(null);
    try {
      const data = await apiJson("/api/timeline/meta");
      setMeta(data);
      setSelectedDate((value) => value || data.max_date);
    } catch (err) {
      console.error("Failed to load timeline metadata:", err);
      setError(`Timeline API unavailable: ${err.message}`);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    if (!selectedDate) return undefined;

    const requestId = ++requestRef.current;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setEventsLoading(true);
      setError(null);

      try {
        const [act, timelineEvents] = await Promise.all([
          apiJson(`/api/timeline/act?as_of=${encodeURIComponent(selectedDate)}`, controller.signal),
          apiJson(`/api/timeline/events?as_of=${encodeURIComponent(selectedDate)}&limit=80`, controller.signal),
        ]);
        if (requestId !== requestRef.current) return;
        setActData(act);
        setEvents(timelineEvents.items || []);
      } catch (err) {
        if (err.name === "AbortError") return;
        console.error("Failed to load historical Act view:", err);
        if (requestId === requestRef.current) {
          setError(`Could not reconstruct the Act for ${selectedDate}: ${err.message}`);
        }
      } finally {
        if (requestId === requestRef.current) {
          setLoading(false);
          setEventsLoading(false);
        }
      }
    }, 160);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [selectedDate]);

  if (!actData && loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="flex items-center gap-3 font-medium text-gray-600">
          <svg className="h-5 w-5 animate-spin text-blue-900" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          Loading historical Companies Act database…
        </div>
      </div>
    );
  }

  if (!actData && error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
        <div className="max-w-xl rounded-lg border border-red-200 bg-red-50 p-6 text-red-700 shadow-sm">
          <h2 className="mb-2 text-lg font-semibold">Historical database unavailable</h2>
          <p className="mb-4 break-words rounded border border-red-200 bg-red-100 p-2.5 font-mono text-sm">{error}</p>
          <button
            type="button"
            onClick={loadMeta}
            className="rounded bg-red-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-800"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between gap-3 bg-blue-950 px-4 text-white shadow-md sm:h-16 sm:px-6">
        <h1 className="min-w-0 truncate text-sm font-bold tracking-wide sm:text-lg">
          {actData?.act_title || "THE COMPANIES ACT, 2013"}
        </h1>
        <div className="hidden shrink-0 items-center gap-3 sm:flex">
          <span className="rounded border border-blue-700 bg-blue-900 px-2.5 py-1 font-mono text-xs">
            DATABASE · HISTORICAL VIEW
          </span>
        </div>
      </header>

      {meta && selectedDate && (
        <TimelineControls
          meta={meta}
          selectedDate={selectedDate}
          onDateChange={setSelectedDate}
          loading={loading}
          events={events}
          eventsLoading={eventsLoading}
          timelineSummary={actData?.timeline_summary}
        />
      )}

      {error && actData && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-center text-xs font-semibold text-red-700">
          {error} The last successfully loaded date remains visible.
        </div>
      )}

      <main className={loading ? "opacity-80 transition-opacity" : "transition-opacity"}>
        <ActViewer data={actData} />
      </main>
    </div>
  );
}

export default App;
