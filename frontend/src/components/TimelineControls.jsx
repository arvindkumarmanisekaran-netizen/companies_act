import React, { useMemo, useState } from "react";
import {
  CalendarDays,
  ChevronDown,
  ChevronUp,
  Clock3,
  FileText,
  History,
  RotateCcw,
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

const EventRow = ({ event }) => (
  <div className="grid gap-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-3">
    <div className="text-[11px] font-bold text-slate-500">{formatDate(event.event_date)}</div>
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-extrabold text-slate-900">{relationshipLabel(event.relationship_type)}</span>
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

  const min = ACT_ENACTMENT_DATE;
  const max = meta?.max_date || new Date().toISOString().slice(0, 10);
  const minDay = useMemo(() => dayValue(min), [min]);
  const maxDay = useMemo(() => dayValue(max), [max]);
  const selectedDay = dayValue(selectedDate || max);

  const changeEvents = useMemo(
    () => events.filter((event) => CHANGE_RELATIONSHIPS.has(event.relationship_type)),
    [events],
  );
  const contextEvents = useMemo(
    () => events.filter((event) => !CHANGE_RELATIONSHIPS.has(event.relationship_type)),
    [events],
  );
  const totalDocuments = useMemo(
    () => (meta?.document_types || []).reduce((sum, item) => sum + Number(item.count || 0), 0),
    [meta?.document_types],
  );

  const visibleEvents = activeTab === "changes" ? changeEvents : contextEvents;

  return (
    <section className="border-b border-slate-200 bg-white" aria-label="Historical Act timeline">
      <div className="mx-auto max-w-[1600px] px-3 py-3 sm:px-6 sm:py-4">
        <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3 sm:p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Clock3 size={18} className="shrink-0 text-blue-900" aria-hidden="true" />
                <h2 className="text-sm font-extrabold text-slate-900 sm:text-base">Historical view</h2>
                {loading && <span className="text-xs font-semibold text-slate-400">Updating…</span>}
              </div>
              <p className="mt-1 text-xs text-slate-500">
                The page shows the Companies Act as it stood on the selected date.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="rounded-xl border border-blue-100 bg-blue-50 px-3 py-2">
                <div className="text-[10px] font-extrabold uppercase tracking-wide text-blue-600">Selected date</div>
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
                disabled={selectedDate === max}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-blue-950 px-3 text-xs font-bold text-white disabled:cursor-default disabled:opacity-40"
              >
                <RotateCcw size={14} aria-hidden="true" />
                Latest
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
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-slate-200 pt-3 text-xs text-slate-600">
            <span className="inline-flex items-center gap-1.5">
              <History size={14} className="text-slate-400" />
              <strong className="text-slate-900">{changeEvents.length}</strong> changes up to this date
            </span>
            <span className="inline-flex items-center gap-1.5">
              <FileText size={14} className="text-slate-400" />
              <strong className="text-slate-900">{totalDocuments.toLocaleString("en-IN")}</strong> parsed documents in corpus
            </span>
            {(timelineSummary?.incomplete_sections ?? 0) > 0 && selectedDate !== max && (
              <span className="font-semibold text-amber-700">
                {timelineSummary.incomplete_sections} sections have partial historical coverage
              </span>
            )}
            <button
              type="button"
              onClick={() => setDetailsOpen((value) => !value)}
              className="ml-auto inline-flex min-h-9 items-center gap-1 rounded-lg px-2.5 font-bold text-blue-900 hover:bg-blue-50"
            >
              {detailsOpen ? "Hide details" : "Show changes & sources"}
              {detailsOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            </button>
          </div>
        </div>

        {detailsOpen && (
          <div className="mt-3 rounded-2xl border border-slate-200 bg-white p-3 sm:p-4">
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">Changes and source material</h3>
                <p className="mt-1 text-xs text-slate-500">
                  Only material dated on or before {formatDate(selectedDate)} is shown here.
                </p>
              </div>

              <div className="inline-flex w-fit rounded-lg bg-slate-100 p-1 text-xs font-bold">
                <button
                  type="button"
                  onClick={() => setActiveTab("changes")}
                  className={`rounded-md px-3 py-1.5 ${activeTab === "changes" ? "bg-white text-blue-950 shadow-sm" : "text-slate-500"}`}
                >
                  Changes ({changeEvents.length})
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("sources")}
                  className={`rounded-md px-3 py-1.5 ${activeTab === "sources" ? "bg-white text-blue-950 shadow-sm" : "text-slate-500"}`}
                >
                  Other sources ({contextEvents.length})
                </button>
              </div>
            </div>

            <div className="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div>
                <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
                  {visibleEvents.slice(0, 30).map((event) => (
                    <EventRow key={`${event.relationship_id}-${event.event_date}`} event={event} />
                  ))}
                  {!eventsLoading && !visibleEvents.length && (
                    <div className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-xs text-slate-500">
                      No dated {activeTab === "changes" ? "changes" : "related source activity"} found up to this date.
                    </div>
                  )}
                  {eventsLoading && <div className="py-6 text-center text-xs text-slate-400">Loading timeline…</div>}
                </div>
              </div>

              <aside className="rounded-xl bg-slate-50 p-3">
                <h4 className="text-xs font-extrabold uppercase tracking-wide text-slate-500">Parsed document types</h4>
                <div className="mt-2 divide-y divide-slate-200">
                  {(meta?.document_types || []).map((item) => (
                    <div key={item.instrument_type} className="flex items-center justify-between gap-3 py-1.5 text-xs">
                      <span className="text-slate-700">{item.label}</span>
                      <span className="font-bold tabular-nums text-slate-500">{Number(item.count || 0).toLocaleString("en-IN")}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                  The corpus includes the principal Act, Amendment Acts, Amendment Rules, Rules, Notifications,
                  Commencement Notifications, Circulars, Corrigenda, Orders, Forms, Accounting Standards / Ind AS,
                  Removal of Difficulties Orders and Regulations.
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
