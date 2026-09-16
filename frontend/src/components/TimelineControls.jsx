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
      <span className="mt-1 inline-flex rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide text-emerald-800">
        Legal effect
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
          <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-800">
            {source.change_relationship_count} change link{Number(source.change_relationship_count) === 1 ? "" : "s"}
          </span>
        )}
        {Number(source.relationship_count || 0) > 0 && (
          <span className="text-[10px] font-semibold text-slate-400">{source.relationship_count} relationships</span>
        )}
      </div>
      <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-600">{source.title}</p>
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
  sourceTotal = 0,
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

  const filteredChanges = useMemo(
    () => changeEvents.filter(
      (event) => instrumentFilter === "all" || event.document?.instrument_type === instrumentFilter,
    ),
    [changeEvents, instrumentFilter],
  );

  const filteredSources = useMemo(
    () => sources.filter(
      (source) => instrumentFilter === "all" || source.instrument_type === instrumentFilter,
    ),
    [sources, instrumentFilter],
  );

  const totalDocuments = Number(meta?.total_documents || 0) || sourceSummary.reduce(
    (sum, item) => sum + Number(item.total || 0),
    0,
  );
  const undatedDocuments = sourceSummary.reduce((sum, item) => sum + Number(item.undated || 0), 0);
  const datedDocuments = sourceSummary.reduce((sum, item) => sum + Number(item.dated || 0), 0);

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
  const unresolved = Number(
    timelineSummary?.unresolved_historical_changes ?? meta?.unresolved_historical_changes ?? 0,
  );

  const familyText = (meta?.corpus_families || []).join(" · ");

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
              <p className="mt-1 max-w-4xl text-xs leading-relaxed text-slate-500">
                Move the slider to any date from enactment onward. The Act, its versioned provisions, cumulative legal changes and parsed source material update together. Historical wording is shown only when its legal effective date is supported; unresolved periods stay visibly marked instead of showing today&apos;s text as past law.
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
              <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1" aria-label="Recent legal-effect dates up to selected date">
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

          <div className="mt-4 grid gap-2 border-t border-slate-200 pt-3 sm:grid-cols-2 xl:grid-cols-5">
            <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
              <History size={15} className="text-slate-400" />
              <span><strong className="text-slate-900">{changeEvents.length}</strong> resolved legal changes loaded</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
              <FileText size={15} className="text-slate-400" />
              <span><strong className="text-slate-900">{sourceTotal.toLocaleString("en-IN")}</strong> dated sources by this date</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
              <FileText size={15} className="text-slate-400" />
              <span><strong className="text-slate-900">{totalDocuments.toLocaleString("en-IN")}</strong> documents in corpus</span>
            </div>
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
                <h3 className="text-sm font-extrabold text-slate-900">Changes and complete parsed source corpus</h3>
                <p className="mt-1 max-w-4xl text-xs text-slate-500">
                  “Legal changes” uses resolved legal-effect dates. “Parsed sources” shows documents published or enacted by {formatDate(selectedDate)}; publication alone never changes the historical wording.
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
                  {sourceSummary.map((item) => (
                    <option key={item.instrument_type} value={item.instrument_type}>
                      {item.instrument_label} ({Number(item.total || 0).toLocaleString("en-IN")})
                    </option>
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
                    Parsed sources ({sourceTotal.toLocaleString("en-IN")})
                  </button>
                </div>
              </div>
            </div>

            <div className="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
                {activeTab === "changes" && filteredChanges.slice(0, 120).map((event) => (
                  <ChangeRow key={`${event.relationship_id}-${event.event_date}`} event={event} />
                ))}
                {activeTab === "sources" && filteredSources.slice(0, 160).map((source) => (
                  <SourceRow key={source.document_id} source={source} />
                ))}
                {!eventsLoading && activeTab === "changes" && !filteredChanges.length && (
                  <div className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-xs text-slate-500">
                    No resolved legal-effect changes match this filter by the selected date.
                  </div>
                )}
                {!eventsLoading && activeTab === "sources" && !filteredSources.length && (
                  <div className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-xs text-slate-500">
                    No dated parsed sources match this filter by the selected date.
                  </div>
                )}
                {eventsLoading && <div className="py-6 text-center text-xs text-slate-400">Updating historical database view…</div>}
              </div>

              <aside className="rounded-xl bg-slate-50 p-3">
                <h4 className="text-xs font-extrabold uppercase tracking-wide text-slate-500">Parsed document types</h4>
                <div className="mt-2 max-h-72 divide-y divide-slate-200 overflow-y-auto pr-1">
                  {sourceSummary.map((item) => (
                    <div key={item.instrument_type} className="py-1.5 text-xs">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-semibold text-slate-700">{item.instrument_label}</span>
                        <span className="font-bold tabular-nums text-slate-500">{Number(item.total || 0).toLocaleString("en-IN")}</span>
                      </div>
                      <div className="mt-0.5 text-[10px] text-slate-400">
                        {Number(item.dated || 0).toLocaleString("en-IN")} dated · {Number(item.undated || 0).toLocaleString("en-IN")} undated
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 rounded-lg border border-slate-200 bg-white p-2.5 text-[11px] leading-relaxed text-slate-600">
                  <strong>{datedDocuments.toLocaleString("en-IN")}</strong> documents have a usable corpus date; <strong>{undatedDocuments.toLocaleString("en-IN")}</strong> remain undated and are kept in the database but are not placed on the slider chronology.
                </div>
                {!!familyText && (
                  <p className="mt-3 text-[11px] leading-relaxed text-slate-500">{familyText}</p>
                )}
                <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                  The database includes the Companies Act structure, Amendment Acts/Ordinances where present, Rules and Amendment Rules, Notifications and Commencement Notifications, Circulars, Corrigenda, Orders, Removal of Difficulties Orders, Forms, Accounting Standards/Ind AS and Regulations.
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
