import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CalendarDays,
  ChevronDown,
  ChevronUp,
  Clock3,
  FileText,
  History,
  RotateCcw,
  ShieldCheck,
  X,
} from "lucide-react";

const DAY_MS = 24 * 60 * 60 * 1000;
const ACT_ENACTMENT_DATE = "2013-08-29";

const parseDay = (value) => {
  const [year, month, day] = String(value || "").split("-").map(Number);
  return Date.UTC(year || 1970, (month || 1) - 1, day || 1);
};

const dayValue = (value) => Math.round(parseDay(value) / DAY_MS);
const fromDayValue = (value) => new Date(Number(value) * DAY_MS).toISOString().slice(0, 10);

const formatDate = (value) => {
  if (!value) return "Undated";
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

const ChangeRow = ({ event }) => (
  <div className="grid gap-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-3">
    <div>
      <div className="text-[11px] font-bold text-slate-500">{formatDate(event.event_date)}</div>
      <span className="mt-1 inline-flex rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide text-emerald-800">Legal effect</span>
    </div>
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-extrabold text-slate-900">{relationshipLabel(event.source_relationship_type || event.relationship_type)}</span>
        {event.target?.section_number && (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-bold text-amber-900">
            Section {event.target.section_number}{event.target.label ? ` ${event.target.label}` : ""}
          </span>
        )}
        <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-900">
          {event.document?.instrument_label || relationshipLabel(event.document?.instrument_type)}
        </span>
      </div>
      <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-600">{event.document?.title}</p>
    </div>
  </div>
);

const SourceRow = ({ source }) => (
  <div className="grid gap-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-3">
    <div>
      <div className="text-[11px] font-bold text-slate-500">{formatDate(source.display_date)}</div>
      <span className="mt-1 inline-flex rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide text-slate-600">
        {String(source.date_basis || "source date").replaceAll("_", " ")}
      </span>
    </div>
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-900">
          {source.instrument_label || relationshipLabel(source.instrument_type)}
        </span>
        {Number(source.change_relationship_count || 0) > 0 && (
          <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-800">Linked to Act changes</span>
        )}
      </div>
      <p className="mt-1 text-xs leading-relaxed text-slate-700">{source.title}</p>
    </div>
  </div>
);

const TimelineControls = ({
  meta,
  selectedDate,
  onDateChange,
  loading,
  events = [],
  sources = [],
  sourceSummary = [],
  eventsLoading = false,
  sourcesLoading = false,
  activeSectionNumber,
  timelineSummary,
}) => {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [corpusOpen, setCorpusOpen] = useState(false);
  const [changeFilter, setChangeFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");

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

  const changeTypes = useMemo(() => {
    const map = new Map();
    changeEvents.forEach((event) => {
      const type = event.document?.instrument_type;
      if (!type || map.has(type)) return;
      map.set(type, event.document?.instrument_label || relationshipLabel(type));
    });
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [changeEvents]);

  const filteredChanges = useMemo(
    () => changeEvents.filter((event) => changeFilter === "all" || event.document?.instrument_type === changeFilter),
    [changeEvents, changeFilter],
  );

  const filteredSources = useMemo(
    () => sources.filter((source) => sourceFilter === "all" || source.instrument_type === sourceFilter),
    [sources, sourceFilter],
  );

  const eventDates = useMemo(() => {
    const unique = [];
    const seen = new Set();
    for (const event of changeEvents) {
      if (!event.event_date || seen.has(event.event_date)) continue;
      seen.add(event.event_date);
      unique.push(event.event_date);
      if (unique.length >= 14) break;
    }
    return unique;
  }, [changeEvents]);

  const exactVersions = Number(timelineSummary?.versioned_provisions || 0);
  const gaps = Number(timelineSummary?.coverage_gap_provisions || 0);
  const unresolved = Number(timelineSummary?.unresolved_historical_changes ?? meta?.unresolved_historical_changes ?? 0);

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
                {!isCurrent && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-wide text-amber-900">Historical snapshot</span>}
              </div>
              <p className="mt-1 max-w-4xl text-xs leading-relaxed text-slate-500">
                Move the slider to reconstruct the Companies Act as it stood on that date. Confirmed amendments, substitutions, insertions, omissions, commencements and corrections are applied using their resolved legal-effect dates.
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
                <input type="date" min={min} max={max} value={selectedDate} onChange={(event) => onDateChange(event.target.value)} className="bg-transparent py-2 text-sm outline-none" />
              </label>
              <button type="button" onClick={() => onDateChange(max)} disabled={isCurrent} className="inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-blue-950 px-3 text-xs font-bold text-white disabled:cursor-default disabled:opacity-40">
                <RotateCcw size={14} aria-hidden="true" /> Current Act
              </button>
            </div>
          </div>

          <div className="mt-4">
            <input type="range" min={minDay} max={maxDay} value={Math.min(maxDay, Math.max(minDay, selectedDay))} onChange={(event) => onDateChange(fromDayValue(event.target.value))} className="h-2 w-full cursor-pointer accent-blue-900" aria-label="Select historical date" />
            <div className="mt-1 flex justify-between text-[10px] font-bold text-slate-400 sm:text-xs">
              <span>29 Aug 2013</span><span>{formatDate(max)}</span>
            </div>
            {!!eventDates.length && (
              <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1" aria-label="Legal-effect dates up to selected date">
                {eventDates.map((eventDate) => (
                  <button key={eventDate} type="button" onClick={() => onDateChange(eventDate)} className="shrink-0 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-bold text-slate-600 hover:border-blue-300 hover:text-blue-900">
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
            <button
              type="button"
              onClick={() => { setSourceFilter("all"); setCorpusOpen(true); }}
              disabled={!activeSectionNumber}
              className="flex items-center gap-2 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-left text-xs font-bold text-blue-950 transition hover:border-blue-300 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <BookOpen size={15} className="text-blue-800" />
              <span>{activeSectionNumber ? `Sources · Section ${activeSectionNumber}` : "Section sources"}</span>
              <span className="ml-auto text-[10px] font-semibold text-blue-700">Open</span>
            </button>
            <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
              <ShieldCheck size={15} className="text-emerald-700" />
              <span><strong className="text-slate-900">{exactVersions.toLocaleString("en-IN")}</strong> exact versioned provisions</span>
            </div>
            <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-xs ${gaps || unresolved ? "bg-amber-50 text-amber-800" : "bg-white text-slate-600"}`}>
              <AlertTriangle size={15} />
              <span><strong>{gaps.toLocaleString("en-IN")}</strong> wording gaps · <strong>{unresolved.toLocaleString("en-IN")}</strong> unresolved</span>
            </div>
          </div>

          <div className="mt-2 flex justify-end">
            <button type="button" onClick={() => setDetailsOpen((value) => !value)} className="inline-flex min-h-9 items-center gap-1 rounded-lg px-2.5 text-xs font-bold text-blue-900 hover:bg-blue-50">
              {detailsOpen ? "Hide legal changes" : "Show legal changes"}
              {detailsOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            </button>
          </div>
        </div>

        {detailsOpen && (
          <div className="mt-3 rounded-2xl border border-slate-200 bg-white p-3 sm:p-4">
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">Legal changes effective by {formatDate(selectedDate)}</h3>
                <p className="mt-1 max-w-4xl text-xs text-slate-500">Confirmed legal-effect events affecting the Act by the selected date. The badge identifies whether the source is an Amendment Act, Ordinance, Rules, Notification, Commencement Notification, Circular, Corrigendum, Order or other parsed instrument type.</p>
              </div>
              <select value={changeFilter} onChange={(event) => setChangeFilter(event.target.value)} className="min-h-10 rounded-lg border border-slate-300 bg-white px-2.5 text-xs font-semibold text-slate-700" aria-label="Filter changes by document type">
                <option value="all">All document types</option>
                {changeTypes.map(([type, label]) => <option key={type} value={type}>{label}</option>)}
              </select>
            </div>
            <div className="mt-3 max-h-[30rem] space-y-2 overflow-y-auto pr-1">
              {filteredChanges.slice(0, 160).map((event) => <ChangeRow key={`${event.relationship_id}-${event.event_date}`} event={event} />)}
              {!eventsLoading && !filteredChanges.length && <div className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-xs text-slate-500">No resolved legal-effect changes match this filter by the selected date.</div>}
              {eventsLoading && <div className="py-6 text-center text-xs text-slate-400">Updating historical database view…</div>}
            </div>
          </div>
        )}
      </div>

      {corpusOpen && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/55 p-3 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="corpus-dialog-title" onMouseDown={(event) => { if (event.target === event.currentTarget) setCorpusOpen(false); }}>
          <div className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-4 py-4 sm:px-6">
              <div>
                <div className="flex items-center gap-2">
                  <FileText size={18} className="text-blue-900" />
                  <h3 id="corpus-dialog-title" className="text-base font-extrabold text-slate-950">Sources relevant to Section {activeSectionNumber}</h3>
                </div>
                <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-500">
                  Only parsed documents linked to Section {activeSectionNumber} and available by {formatDate(selectedDate)} are shown here. A source appearing here does not by itself change the Act; resolved legal-effect relationships determine the historical wording.
                </p>
              </div>
              <button type="button" onClick={() => setCorpusOpen(false)} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900" aria-label="Close sources"><X size={18} /></button>
            </div>

            <div className="grid min-h-0 flex-1 gap-4 overflow-hidden p-4 sm:p-6 lg:grid-cols-[250px_minmax(0,1fr)]">
              <aside className="overflow-y-auto rounded-xl bg-slate-50 p-3">
                <h4 className="text-[11px] font-extrabold uppercase tracking-wide text-slate-500">Relevant document types</h4>
                <div className="mt-2 space-y-1">
                  <button type="button" onClick={() => setSourceFilter("all")} className={`w-full rounded-lg px-2.5 py-2 text-left text-xs font-semibold ${sourceFilter === "all" ? "bg-blue-950 text-white" : "text-slate-700 hover:bg-white"}`}>All relevant types</button>
                  {sourceSummary.map((item) => (
                    <button key={item.instrument_type} type="button" onClick={() => setSourceFilter(item.instrument_type)} className={`w-full rounded-lg px-2.5 py-2 text-left text-xs font-semibold ${sourceFilter === item.instrument_type ? "bg-blue-950 text-white" : "text-slate-700 hover:bg-white"}`}>
                      {item.instrument_label}
                    </button>
                  ))}
                </div>
                <div className="mt-4 border-t border-slate-200 pt-3 text-[11px] leading-relaxed text-slate-500">
                  Depending on the section and date, relevant material can include the Companies Act, Amendment Acts, Ordinances, Rules and Amendment Rules, Notifications and Commencement Notifications, Circulars, Corrigenda, Orders, Removal of Difficulties Orders, Forms, Accounting Standards and Ind AS, and Regulations.
                </div>
              </aside>

              <div className="min-h-0 overflow-y-auto pr-1">
                <h4 className="mb-0.5 text-sm font-extrabold text-slate-900">Section {activeSectionNumber} · {formatDate(selectedDate)}</h4>
                <p className="mb-3 text-[11px] text-slate-500">Sources are filtered by the section currently open and by the timeline date.</p>
                <div className="space-y-2">
                  {filteredSources.map((source) => <SourceRow key={source.document_id} source={source} />)}
                  {!sourcesLoading && !filteredSources.length && <div className="rounded-xl border border-dashed border-slate-200 px-4 py-10 text-center text-xs text-slate-500">No dated parsed sources linked to this section match the selected date and document type.</div>}
                  {sourcesLoading && <div className="py-8 text-center text-xs text-slate-400">Updating sources for Section {activeSectionNumber}…</div>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};

export default TimelineControls;
