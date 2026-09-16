import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  ChevronDown,
  ChevronUp,
  Clock3,
  FileText,
  History,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

const DAY_MS = 24 * 60 * 60 * 1000;
const ACT_ENACTMENT_DATE = "2013-08-29";
const CHANGE_RELATIONSHIPS = new Set([
  "amends",
  "substitutes",
  "inserts",
  "omits",
  "commences",
  "corrects",
]);

const parseDay = (value) => {
  const [year, month, day] = String(value || "").split("-").map(Number);
  return Date.UTC(year || 1970, (month || 1) - 1, day || 1);
};

const dayValue = (value) => Math.round(parseDay(value) / DAY_MS);
const fromDayValue = (value) => new Date(Number(value) * DAY_MS).toISOString().slice(0, 10);

const formatDate = (value) => {
  if (!value) return "";
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
};

const relationshipLabel = (value) =>
  String(value || "change")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const EventRow = ({ event }) => {
  const legalEffect = event.event_kind === "legal_effect" || event.legal_effect_confirmed;
  return (
    <div className="grid gap-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-3">
      <div>
        <div className="text-[11px] font-bold text-slate-500">{formatDate(event.event_date)}</div>
        <span
          className={`mt-1 inline-flex rounded px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide ${
            legalEffect ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600"
          }`}
        >
          {legalEffect ? "Legal effect" : "Published source"}
        </span>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-extrabold text-slate-900">
            {relationshipLabel(event.source_relationship_type || event.relationship_type)}
          </span>
          {event.target?.section_number && (
            <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-bold text-amber-900">
              Section {event.target.section_number}{event.target.label ? ` ${event.target.label}` : ""}
            </span>
          )}
          <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-900">
            {event.document.instrument_label}
          </span>
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-600">{event.document.title}</p>
      </div>
    </div>
  );
};

const TimelineControls = ({
  meta,
  selectedDate,
  onDateChange,
  loading,
  events = [],
  eventsLoading = false,
  timelineSummary,
}) => {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("changes");
  const [instrumentFilter, setInstrumentFilter] = useState("all");

  const min = ACT_ENACTMENT_DATE;
  const max = meta?.max_date || new Date().toISOString().slice(0, 10);
  const minDay = useMemo(() => dayValue(min), [min]);
  const maxDay = useMemo(() => dayValue(max), [max]);
  const selectedDay = dayValue(selectedDate || max);
  const isCurrent = selectedDate === max;

  const changeEvents = useMemo(
    () => events.filter((event) => event.event_kind === "legal_effect" || event.legal_effect_confirmed),
    [events],
  );
  const contextEvents = useMemo(
    () => events.filter((event) => !(event.event_kind === "legal_effect" || event.legal_effect_confirmed)),
    [events],
  );
  const totalDocuments = Number(meta?.total_documents || 0) || useMemo(
    () => (meta?.document_types || []).reduce((sum, item) => sum + Number(item.count || 0), 0),
    [meta?.document_types],
  );

  const tabEvents = activeTab === "changes" ? changeEvents : contextEvents;
  const visibleEvents = useMemo(
    () => tabEvents.filter(
      (event) => instrumentFilter === "all" || event.document?.instrument_type === instrumentFilter,
    ),
    [tabEvents, instrumentFilter],
  );

  const eventDates = useMemo(() => {
    const unique = [];
    const seen = new Set();
    for (const event of changeEvents) {
      if (!event.event_date || seen.has(event.event_date)) continue;
      seen.add(event.event_date);
      unique.push(event.event_date);
      if (unique.length >= 12) break;
    }
    return unique;
  }, [changeEvents]);

  const exactVersions = Number(timelineSummary?.versioned_provisions || 0);
  const gaps = Number(timelineSummary?.coverage_gap_provisions || 0);
  const unresolved = Number(
    timelineSummary?.unresolved_historical_changes ?? meta?.unresolved_historical_changes ?? 0,
  );

  return (
    <section className="border-b border-slate-200 bg-white" aria-label="Historical Act timeline">
      <div className="mx-auto max-w-[1600px] px-3 py-3 sm:px-6 sm:py-4">
        <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3 sm:p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Clock3 size={18} className="shrink-0 text-blue-900" aria-hidden="true" />
                <h2 className="text-sm font-extrabold text-slate-900 sm:text-base">Act through time</h2>
                {loading && <span className="text-xs font-semibold text-slate-400">Updating…</span>}
                {!isCurrent && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-wide text-amber-900">
                    Historical snapshot
                  </span>
                )}
              </div>
              <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-500">
                Move the slider to reconstruct the Companies Act on a past date. Exact historical wording is shown only where the database supports the effective date and text; unresolved gaps are marked instead of silently using today&apos;s wording.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="rounded-xl border border-blue-100 bg-blue-50 px-3 py-2">
                <div className="text-[10px] font-extrabold uppercase tracking-wide text-blue-600">As at</div>
                <div className="mt-0.5 text-sm font-extrabold text-blue-950">{formatDate(selectedDate)}</div>
              </div>

              <label className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700">
                <CalendarDays size={15} aria-hidden="true" />
                <span className="sr-only">Historical date</span>
                <input
                  type="date"
                  min={min}
                  max={max}
                  value={selectedDate}
                  onChange={(event) => onDateChange(event.target.value)}
                  className="bg-transparent py-2 text-sm outline-none"
                />
              </label>

              <button
                type="button"
                onClick={() => onDateChange(max)}
                disabled={isCurrent}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-blue-950 px-3 text-xs font-bold text-white disabled:cursor-default disabled:opacity-40"
              >
                <RotateCcw size={14} aria-hidden="true" />
                Current Act
              </button>
            </div>
          </div>

          <div className="mt-4">
            <input
              type="range"
              min={minDay}
              max={maxDay}
              value={Math.min(maxDay, Math.max(minDay, selectedDay))}
              onChange={(event) => onDateChange(fromDayValue(event.target.value))}
              className="h-2 w-full cursor-pointer accent-blue-900"
              aria-label="Select historical date"
            />
            <div className="mt-1 flex justify-between text-[10px] font-bold text-slate-400 sm:text-xs">
              <span>29 Aug 2013</span>
              <span>{formatDate(max)}</span>
            </div>

            {!!eventDates.length && (
              <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1" aria-label="Recent change dates up to selected date">
                {eventDates.map((eventDate) => (
                  <button
                    key={eventDate}
                    type="button"
                    onClick={() => onDateChange(eventDate)}
                    className="shrink-0 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-bold text-slate-600 hover:border-blue-300 hover:text-blue-900"
                  >
                    {formatDate(eventDate)}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="mt-4 grid gap-2 border-t border-slate-200 pt-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
              <History size={15} className="text-slate-400" />
              <span><strong className="text-slate-900">{changeEvents.length}</strong> resolved legal changes loaded</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
              <FileText size={15} className="text-slate-400" />
              <span><strong className="text-slate-900">{totalDocuments.toLocaleString("en-IN")}</strong> parsed documents</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
              <ShieldCheck size={15} className="text-emerald-700" />
              <span><strong className="text-slate-900">{exactVersions.toLocaleString("en-IN")}</strong> exact versioned provisions</span>
            </div>
            <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-xs ${gaps || unresolved ? "bg-amber-50 text-amber-800" : "bg-white text-slate-600"}`}>
              <AlertTriangle size={15} />
              <span><strong>{gaps.toLocaleString("en-IN")}</strong> wording gaps · <strong>{unresolved.toLocaleString("en-IN")}</strong> unresolved history items</span>
            </div>
          </div>

          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={() => setDetailsOpen((value) => !value)}
              className="inline-flex min-h-9 items-center gap-1 rounded-lg px-2.5 text-xs font-bold text-blue-900 hover:bg-blue-50"
            >
              {detailsOpen ? "Hide changes & sources" : "Show changes & sources"}
              {detailsOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            </button>
          </div>
        </div>

        {detailsOpen && (
          <div className="mt-3 rounded-2xl border border-slate-200 bg-white p-3 sm:p-4">
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">Changes and parsed source material</h3>
                <p className="mt-1 text-xs text-slate-500">
                  Legal-effect changes are separated from publication-only source activity through {formatDate(selectedDate)}.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={instrumentFilter}
                  onChange={(event) => setInstrumentFilter(event.target.value)}
                  className="min-h-10 rounded-lg border border-slate-300 bg-white px-2.5 text-xs font-semibold text-slate-700"
                  aria-label="Filter by document type"
                >
                  <option value="all">All document types</option>
                  {(meta?.document_types || []).map((item) => (
                    <option key={item.instrument_type} value={item.instrument_type}>{item.label}</option>
                  ))}
                </select>
                <div className="inline-flex w-fit rounded-lg bg-slate-100 p-1 text-xs font-bold">
                  <button
                    type="button"
                    onClick={() => setActiveTab("changes")}
                    className={`rounded-md px-3 py-1.5 ${activeTab === "changes" ? "bg-white text-blue-950 shadow-sm" : "text-slate-500"}`}
                  >
                    Legal changes ({changeEvents.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("sources")}
                    className={`rounded-md px-3 py-1.5 ${activeTab === "sources" ? "bg-white text-blue-950 shadow-sm" : "text-slate-500"}`}
                  >
                    Related sources ({contextEvents.length})
                  </button>
                </div>
              </div>
            </div>

            <div className="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
              <div>
                <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
                  {visibleEvents.slice(0, 60).map((event) => (
                    <EventRow key={`${event.relationship_id}-${event.event_date}-${event.event_kind}`} event={event} />
                  ))}
                  {!eventsLoading && !visibleEvents.length && (
                    <div className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-xs text-slate-500">
                      No dated {activeTab === "changes" ? "legal-effect changes" : "related source activity"} match this filter.
                    </div>
                  )}
                  {eventsLoading && <div className="py-6 text-center text-xs text-slate-400">Loading timeline…</div>}
                </div>
              </div>

              <aside className="rounded-xl bg-slate-50 p-3">
                <h4 className="text-xs font-extrabold uppercase tracking-wide text-slate-500">Parsed document types</h4>
                <div className="mt-2 max-h-72 divide-y divide-slate-200 overflow-y-auto pr-1">
                  {(meta?.document_types || []).map((item) => (
                    <div key={item.instrument_type} className="flex items-center justify-between gap-3 py-1.5 text-xs">
                      <span className="text-slate-700">{item.label}</span>
                      <span className="font-bold tabular-nums text-slate-500">{Number(item.count || 0).toLocaleString("en-IN")}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                  {(meta?.corpus_families || [
                    "Companies Act, 2013 and consolidated structure",
                    "Amendment Acts and Ordinances",
                    "Rules and Amendment Rules",
                    "Notifications and Commencement Notifications",
                    "Circulars and Corrigenda",
                    "Orders and Removal of Difficulties Orders",
                    "Forms",
                    "Accounting Standards / Ind AS",
                    "Regulations",
                  ]).join(" · ")}
                </p>
                <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-[10px] leading-relaxed text-amber-900">
                  Publication dates provide documentary context. They do not alter the historical Act unless the legal effective date has been resolved.
                </p>
              </aside>
            </div>
          </div>
        )}
      </div>
    </section>
  );
};

export default TimelineControls;
