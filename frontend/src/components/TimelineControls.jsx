import React, { useMemo, useState } from "react";
import { CalendarDays, ChevronDown, ChevronUp, Clock3, Database, RotateCcw } from "lucide-react";

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
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
};

const relationshipLabel = (value) =>
  String(value || "change")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const dateBasisLabel = (value) => {
  if (value === "effective_date") return "effective date";
  if (value === "enactment_date") return "enactment date";
  return "publication date";
};

const EventCard = ({ event }) => (
  <div className="rounded-lg border border-slate-200 bg-white p-2.5">
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-900">
        {event.document.instrument_label}
      </span>
      <span className="text-[10px] font-semibold text-slate-500">{event.event_date}</span>
      <span className="text-[10px] font-semibold text-slate-500">{relationshipLabel(event.relationship_type)}</span>
      <span
        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
          event.legal_effect_confirmed
            ? "bg-emerald-50 text-emerald-800"
            : "bg-slate-100 text-slate-500"
        }`}
      >
        {event.legal_effect_confirmed ? "resolved legal effect" : dateBasisLabel(event.date_basis)}
      </span>
      {event.target?.section_number && (
        <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900">
          Section {event.target.section_number}
          {event.target.label ? ` ${event.target.label}` : ""}
        </span>
      )}
    </div>
    <p className="mt-1 line-clamp-2 text-xs font-semibold leading-snug text-slate-800">{event.document.title}</p>
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

  return (
    <section className="border-b border-slate-200 bg-white shadow-sm" aria-label="Historical Act timeline">
      <div className="mx-auto max-w-[1600px] px-3 py-3 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-sm font-extrabold text-slate-900">
              <Clock3 size={18} className="text-blue-800" aria-hidden="true" />
              Act as it stood on <span className="text-blue-900">{formatDate(selectedDate)}</span>
              {loading && <span className="text-xs font-medium text-slate-500">Updating…</span>}
            </div>
            <p className="mt-1 max-w-4xl text-xs leading-relaxed text-slate-600">
              Move the slider to reconstruct the Act from the historical provision-version database. Resolved wording, omissions and substitutions update with the selected date; related instruments and normalized legal relationships are also limited to material available by that date.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-2.5 text-xs font-semibold text-slate-700">
              <CalendarDays size={15} aria-hidden="true" />
              <span className="sr-only">Historical date</span>
              <input
                type="date"
                min={min}
                max={max}
                value={selectedDate}
                onChange={(event) => onDateChange(event.target.value)}
                className="min-w-0 bg-transparent py-2 text-sm outline-none"
              />
            </label>
            <button
              type="button"
              onClick={() => onDateChange(max)}
              disabled={selectedDate === max}
              className="inline-flex min-h-10 items-center gap-1.5 rounded-lg bg-blue-950 px-3 text-xs font-bold text-white disabled:cursor-default disabled:opacity-40"
            >
              <RotateCcw size={14} aria-hidden="true" />
              Today
            </button>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 sm:gap-3">
          <span className="text-[10px] font-bold text-slate-500 sm:text-xs">2013</span>
          <input
            type="range"
            min={minDay}
            max={maxDay}
            value={Math.min(maxDay, Math.max(minDay, selectedDay))}
            onChange={(event) => onDateChange(fromDayValue(event.target.value))}
            className="h-2 w-full cursor-pointer accent-blue-900"
            aria-label="Select historical date"
          />
          <span className="text-[10px] font-bold text-slate-500 sm:text-xs">{max.slice(0, 4)}</span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">
            <Database size={13} aria-hidden="true" />
            {meta?.version_rows ?? 0} resolved version rows
          </span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">
            {totalDocuments.toLocaleString("en-IN")} parsed legal documents
          </span>
          {(meta?.unresolved_historical_changes ?? 0) > 0 && (
            <span className="rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 font-semibold text-amber-800">
              {meta.unresolved_historical_changes} historical changes awaiting exact effective-date resolution
            </span>
          )}
          {(timelineSummary?.incomplete_sections ?? 0) > 0 && selectedDate !== max && (
            <span className="rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 font-semibold text-amber-800">
              {timelineSummary.incomplete_sections} sections have partial date coverage
            </span>
          )}
          <button
            type="button"
            onClick={() => setDetailsOpen((value) => !value)}
            className="ml-auto inline-flex min-h-9 items-center gap-1 rounded-lg px-2.5 font-bold text-blue-900 hover:bg-blue-50"
          >
            Corpus & changes
            {detailsOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </button>
        </div>

        {detailsOpen && (
          <div className="mt-3 grid gap-4 border-t border-slate-200 pt-3 xl:grid-cols-3">
            <div>
              <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Parsed document types in the database</h2>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(meta?.document_types || []).map((item) => (
                  <span
                    key={item.instrument_type}
                    className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700"
                    title={item.instrument_type}
                  >
                    {item.label} <span className="text-slate-400">{item.count}</span>
                  </span>
                ))}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                The historical view is backed by the principal Companies Act structure and the parsed corpus: Amendment Acts, Amendment Rules, Rules, Notifications, Commencement Notifications, Circulars, Corrigenda, Orders, Forms, Accounting Standards / Ind AS, Removal of Difficulties Orders and Regulations. The normalized relationship graph links these instruments to the relevant provisions.
              </p>
              {meta?.latest_corpus_date && (
                <p className="mt-2 text-[11px] font-semibold text-slate-500">
                  Latest dated corpus material: {meta.latest_corpus_date}
                </p>
              )}
            </div>

            <div>
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Change-linked instruments up to this date</h2>
                {eventsLoading && <span className="text-[11px] text-slate-400">Loading…</span>}
              </div>
              <div className="mt-2 max-h-64 space-y-2 overflow-y-auto pr-1">
                {changeEvents.slice(0, 18).map((event) => (
                  <EventCard key={`${event.relationship_id}-${event.event_date}`} event={event} />
                ))}
                {!eventsLoading && !changeEvents.length && (
                  <p className="py-3 text-xs text-slate-500">No dated change-linked instruments were found up to this date.</p>
                )}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Other related corpus activity</h2>
                {eventsLoading && <span className="text-[11px] text-slate-400">Loading…</span>}
              </div>
              <div className="mt-2 max-h-64 space-y-2 overflow-y-auto pr-1">
                {contextEvents.slice(0, 18).map((event) => (
                  <EventCard key={`${event.relationship_id}-${event.event_date}`} event={event} />
                ))}
                {!eventsLoading && !contextEvents.length && (
                  <p className="py-3 text-xs text-slate-500">No other dated corpus relationships were found up to this date.</p>
                )}
              </div>
            </div>

            <p className="xl:col-span-3 text-[11px] leading-relaxed text-slate-500">
              <strong>Date rule:</strong> publication dates are useful for showing when a parsed document entered the corpus, but publication alone is not treated as the legal effective date of a change. The Act wording changes on the slider only where an explicit or deterministically resolved effective date is available in the historical provision-version data. Items without that certainty remain visible as dated source activity rather than being silently applied to the statutory text.
            </p>
          </div>
        )}
      </div>
    </section>
  );
};

export default TimelineControls;
