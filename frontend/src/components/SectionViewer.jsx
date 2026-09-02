import React, { useEffect, useMemo, useState } from "react";

const AMENDMENT_PDFS = [
  {
    year: "2015",
    label: "Companies (Amendment) Act, 2015",
    file: "Companies_Amendment_2015.pdf",
  },
  {
    year: "2017",
    label: "Companies (Amendment) Act, 2017",
    file: "Companies_Amendment_2017.pdf",
  },
  {
    year: "2019",
    label: "Companies (Amendment) Act, 2019",
    file: "Companies_Amendment_2019.pdf",
  },
  {
    year: "2020",
    label: "Companies (Amendment) Act, 2020",
    file: "Companies_Amendment_2020.pdf",
  },
];

export const amendmentPdfSources = (sourceNote) => {
  const note = String(sourceNote || "");
  const baseUrl = import.meta.env.BASE_URL.replace(/\/$/, "");

  return AMENDMENT_PDFS.flatMap((document) => {
    const titlePattern = new RegExp(
      `companies\\s*(?:\\(\\s*amendment\\s*\\)|amendment)\\s*(?:act,?\\s*)?${document.year}`,
      "i",
    );
    const titleMatch = titlePattern.exec(note);
    if (!titleMatch) return [];

    const citationStart = titleMatch.index;
    const remaining = note.slice(citationStart + titleMatch[0].length);
    const nextCitation = remaining.search(
      /;\s*(?=(?:inserted|omitted|substituted|amended)\s+by\s+|(?:the\s+)?companies\s*(?:\(\s*amendment\s*\)|amendment))/i,
    );
    const citation = note.slice(
      citationStart,
      nextCitation >= 0
        ? citationStart + titleMatch[0].length + nextCitation
        : note.length,
    );
    const page = citation.match(/PDF\s+page\s+(\d+)/i)?.[1];
    const url = `${baseUrl}/docs/amendments/${document.file}${page ? `#page=${page}` : ""}`;

    return [{ ...document, page, url }];
  });
};

const ChangeBadge = ({ type, onClick }) => {
  if (!type || type === "active") return null;
  const label = type === "substituted" ? "Substituted wording" : "Omitted wording";
  const colors =
    type === "substituted"
      ? "border-amber-300 bg-amber-100 text-amber-900"
      : "border-red-300 bg-red-100 text-red-900";
  const className = `inline-flex rounded border px-2 py-0.5 text-[11px] font-bold uppercase ${colors} ${
    onClick ? "cursor-pointer transition hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-blue-500" : ""
  }`;

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={className}
        title="Open the source amendment PDF"
      >
        {label}
        <span aria-hidden="true" className="ml-1">↗</span>
      </button>
    );
  }

  return <span className={className}>{label}</span>;
};

const AmendmentPdfModal = ({ sources, onClose }) => {
  const [activeIndex, setActiveIndex] = useState(0);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setActiveIndex(0);
  }, [sources]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  const activeSource = sources[activeIndex];
  if (!activeSource) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-3 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Amendment PDF viewer"
        className={`flex overflow-hidden rounded-xl bg-white shadow-2xl transition-all ${
          expanded
            ? "h-[calc(100vh-1.5rem)] w-[calc(100vw-1.5rem)]"
            : "h-[min(70vh,600px)] w-[min(92vw,760px)]"
        }`}
      >
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex flex-wrap items-center gap-2 border-b bg-slate-50 px-3 py-2">
            <div className="min-w-0 flex-1">
              <h4 className="truncate text-sm font-bold text-slate-900">{activeSource.label}</h4>
              <p className="text-xs text-slate-500">
                {activeSource.page ? `Opening PDF page ${activeSource.page}` : "Source amendment document"}
              </p>
            </div>

            {sources.length > 1 && (
              <select
                value={activeIndex}
                onChange={(event) => setActiveIndex(Number(event.target.value))}
                className="max-w-56 rounded border border-slate-300 bg-white px-2 py-1.5 text-xs"
                aria-label="Select amendment document"
              >
                {sources.map((source, index) => (
                  <option key={source.file} value={index}>
                    {source.label}
                  </option>
                ))}
              </select>
            )}

            <a
              href={activeSource.url}
              target="_blank"
              rel="noreferrer"
              className="rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              Open separately
            </a>
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              {expanded ? "Restore" : "Expand"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded bg-slate-800 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-700"
              aria-label="Close amendment PDF"
            >
              Close
            </button>
          </header>

          <iframe
            key={activeSource.url}
            src={activeSource.url}
            title={activeSource.label}
            className="min-h-0 flex-1 bg-slate-200"
          />
        </div>
      </section>
    </div>
  );
};

const normalizeIdentifier = (value) =>
  String(value || "")
    .toLowerCase()
    .replace(/[()[\].\s]/g, "");

const romanValue = (value) => {
  if (!/^[ivxlcdm]+$/i.test(value)) return null;
  const values = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 };
  return value
    .toLowerCase()
    .split("")
    .reduce((total, character, index, characters) => {
      const current = values[character];
      const next = values[characters[index + 1]] || 0;
      return total + (current < next ? -current : current);
    }, 0);
};

const compareIdentifiers = (left, right) => {
  const a = normalizeIdentifier(left);
  const b = normalizeIdentifier(right);
  if (/^\d+$/.test(a) && /^\d+$/.test(b)) return Number(a) - Number(b);

  const romanA = romanValue(a);
  const romanB = romanValue(b);
  if (romanA !== null && romanB !== null) return romanA - romanB;

  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
};

const groupCurrentAndHistory = (current, historical, identifierField) => {
  const groups = new Map();
  const add = (entry, kind, index) => {
    const rawIdentifier = entry?.[identifierField] || `unknown-${kind}-${index}`;
    const identifier = normalizeIdentifier(rawIdentifier) || rawIdentifier;
    if (!groups.has(identifier)) {
      groups.set(identifier, { identifier: rawIdentifier, current: [], historical: [] });
    }
    groups.get(identifier)[kind].push(entry);
  };

  current.forEach((entry, index) => add(entry, "current", index));
  historical.forEach((entry, index) => add(entry, "historical", index));
  return [...groups.values()].sort((a, b) => compareIdentifiers(a.identifier, b.identifier));
};

const HistoricalEntry = ({ entry, prefix, onOpenAmendment }) => {
  const sources = amendmentPdfSources(entry.source_note);

  return (
    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <ChangeBadge
          type={entry.change_type}
          onClick={sources.length ? () => onOpenAmendment(entry.source_note) : undefined}
        />
        {prefix && <span className="font-semibold text-gray-700">{prefix}</span>}
      </div>
      {entry.text && <p className="leading-relaxed text-gray-800">{entry.text}</p>}
      {entry.clauses?.map((clause, index) => (
        <div key={`historical-nested-${clause.clause_number || index}-${index}`} className="mt-2 flex gap-2">
          <span className="font-semibold text-amber-800">{clause.clause_number}</span>
          <span>{clause.text}</span>
        </div>
      ))}
      <p className="mt-2 border-t border-amber-200 pt-2 text-xs text-amber-900">
        <strong>Amendment note:</strong> {entry.source_note}
      </p>
      {sources.length > 0 && (
        <button
          type="button"
          onClick={() => onOpenAmendment(entry.source_note)}
          className="mt-2 text-xs font-semibold text-blue-800 underline decoration-blue-300 underline-offset-2 hover:text-blue-950"
        >
          View amendment PDF
        </button>
      )}
    </div>
  );
};

export const SubsectionRenderer = ({ subsection, historical = false, onOpenAmendment }) => {
  const sourceAvailable = amendmentPdfSources(subsection.source_note).length > 0;
  const clauseGroups = useMemo(
    () =>
      groupCurrentAndHistory(
        subsection.clauses || [],
        subsection.historical_clauses || [],
        "clause_number",
      ),
    [subsection.clauses, subsection.historical_clauses],
  );

  return (
    <div
      className={`mb-4 border-l-2 pl-4 ${
        historical ? "border-amber-400 bg-amber-50/40 py-3 pr-3" : "border-gray-200"
      }`}
    >
      {historical && (
        <div className="mb-2">
          <ChangeBadge
            type={subsection.change_type || "omitted"}
            onClick={
              sourceAvailable ? () => onOpenAmendment(subsection.source_note) : undefined
            }
          />
        </div>
      )}
      <div className="flex items-start gap-2">
        {subsection.subsection_number && subsection.subsection_number !== "N/A" && (
          <span className="font-bold text-gray-700">{subsection.subsection_number}</span>
        )}
        {subsection.text && <p className="leading-relaxed text-gray-900">{subsection.text}</p>}
      </div>

      {subsection.amendments?.length > 0 && (
        <div className="ml-6 mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
          {subsection.amendments.map((amendment, index) => (
            <div key={`amend-${amendment.footnote_ref || index}-${index}`}>
              <strong>[{amendment.footnote_ref}]</strong> {amendment.note}
            </div>
          ))}
        </div>
      )}

      {subsection.historical_versions?.map((version, index) => (
        <HistoricalEntry
          key={`historical-version-${version.subsection_number || index}-${index}`}
          entry={version}
          prefix="Earlier wording"
          onOpenAmendment={onOpenAmendment}
        />
      ))}

      {clauseGroups.length > 0 && (
        <div className="ml-6 mt-2 space-y-3">
          {clauseGroups.map((group, groupIndex) => (
            <div key={`clause-group-${normalizeIdentifier(group.identifier)}-${groupIndex}`}>
              {group.current.map((clause, index) => (
                <div
                  key={`clause-${clause.clause_number || index}-${index}`}
                  className="flex items-start gap-2 text-sm text-gray-800"
                >
                  <span className="min-w-[30px] font-semibold text-blue-600">
                    {clause.clause_number}
                  </span>
                  <span>{clause.text}</span>
                </div>
              ))}
              {group.historical.map((clause, index) => (
                <HistoricalEntry
                  key={`historical-clause-${clause.clause_number || index}-${index}`}
                  entry={clause}
                  prefix={group.current.length ? "Earlier wording" : clause.clause_number}
                  onOpenAmendment={onOpenAmendment}
                />
              ))}
            </div>
          ))}
        </div>
      )}

      {historical && subsection.source_note && (
        <p className="mt-2 text-xs text-amber-900">
          <strong>Amendment note:</strong> {subsection.source_note}
        </p>
      )}
    </div>
  );
};

export const SectionCard = ({ section }) => {
  const [pdfSources, setPdfSources] = useState([]);
  if (!section) return null;

  const openAmendment = (sourceNote) => {
    const sources = amendmentPdfSources(sourceNote);
    if (sources.length) setPdfSources(sources);
  };

  const sectionNumber = String(section.section_number || "");
  const escapedSectionNumber = sectionNumber.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const displayTitle = String(section.title || "").replace(
    new RegExp(`^${escapedSectionNumber}\\.\\s*`, "i"),
    "",
  );
  const headingKey = (value) =>
    String(value || "")
      .replace(
        new RegExp(
          `^(?:section\\s+)?${escapedSectionNumber}[.：:–—-]?\\s*`,
          "i",
        ),
        "",
      )
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  const subsections = section.subsections || [];
  const visibleSubsections = subsections.filter(
    (subsection) =>
      !(
        subsections.length > 1 &&
        String(subsection.subsection_number || "").trim().toUpperCase() === "N/A" &&
        !subsection.clauses?.length &&
        !subsection.amendments?.length &&
        headingKey(subsection.text) === headingKey(displayTitle)
      ),
  );
  const subsectionGroups = groupCurrentAndHistory(
    visibleSubsections,
    section.historical_subsections || [],
    "subsection_number",
  );
  const sectionSources = amendmentPdfSources(section.source_note);

  return (
    <>
      <article
        className={`mb-6 rounded-lg border p-6 shadow-md ${
          section.historical ? "border-red-200 bg-red-50/40" : "border-gray-200 bg-white"
        }`}
      >
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h3 className="text-lg font-bold text-gray-900">
            Section {section.section_number}: {displayTitle}
          </h3>
          {section.historical && (
            <ChangeBadge
              type={section.change_type || "omitted"}
              onClick={
                sectionSources.length ? () => openAmendment(section.source_note) : undefined
              }
            />
          )}
        </div>

        {section.historical && section.source_note && (
          <p className="mb-4 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
            <strong>Amendment note:</strong> {section.source_note}
          </p>
        )}

        {subsectionGroups.length > 0 ? (
          subsectionGroups.map((group, groupIndex) => (
            <div key={`subsection-group-${normalizeIdentifier(group.identifier)}-${groupIndex}`}>
              {group.current.map((subsection, index) => (
                <SubsectionRenderer
                  key={`subsec-${section.section_number}-${subsection.subsection_number}-${index}`}
                  subsection={subsection}
                  onOpenAmendment={openAmendment}
                />
              ))}
              {group.historical.map((subsection, index) => (
                <SubsectionRenderer
                  key={`historical-subsection-${subsection.subsection_number || index}-${index}`}
                  subsection={subsection}
                  historical
                  onOpenAmendment={openAmendment}
                />
              ))}
            </div>
          ))
        ) : (
          <p className="italic text-gray-500">No subsections available.</p>
        )}
      </article>

      {pdfSources.length > 0 && (
        <AmendmentPdfModal sources={pdfSources} onClose={() => setPdfSources([])} />
      )}
    </>
  );
};

export default SectionCard;
