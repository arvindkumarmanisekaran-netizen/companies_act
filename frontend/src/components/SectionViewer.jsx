import React from "react";

const ChangeBadge = ({ type }) => {
  if (!type || type === "active") return null;
  const label = type === "substituted" ? "Substituted wording" : "Omitted wording";
  const colors =
    type === "substituted"
      ? "bg-amber-100 text-amber-800 border-amber-200"
      : "bg-red-100 text-red-800 border-red-200";

  return (
    <span className={`inline-flex px-2 py-0.5 rounded border text-[11px] font-bold uppercase ${colors}`}>
      {label}
    </span>
  );
};

const HistoricalEntry = ({ entry, prefix }) => (
  <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <ChangeBadge type={entry.change_type} />
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
  </div>
);

export const SubsectionRenderer = ({ subsection, historical = false }) => {
  return (
    <div
      className={`mb-4 pl-4 border-l-2 ${
        historical ? "border-amber-400 bg-amber-50/40 py-3 pr-3" : "border-gray-200"
      }`}
    >
      {historical && (
        <div className="mb-2">
          <ChangeBadge type={subsection.change_type || "omitted"} />
        </div>
      )}
      <div className="flex items-start gap-2">
        {subsection.subsection_number && subsection.subsection_number !== "N/A" && (
          <span className="font-bold text-gray-700">{subsection.subsection_number}</span>
        )}
        {subsection.text && <p className="text-gray-900 leading-relaxed">{subsection.text}</p>}
      </div>

      {/* Render sub-clauses */}
      {subsection.clauses && subsection.clauses.length > 0 && (
        <div className="ml-6 mt-2 space-y-2">
          {subsection.clauses.map((clause, idx) => (
            <div
              key={`clause-${clause.clause_number || idx}-${idx}`}
              className="flex items-start gap-2 text-sm text-gray-800"
            >
              <span className="font-semibold text-blue-600 min-w-[30px]">
                {clause.clause_number}
              </span>
              <span>{clause.text}</span>
            </div>
          ))}
        </div>
      )}

      {/* Render amendments / footnotes */}
      {subsection.amendments && subsection.amendments.length > 0 && (
        <div className="ml-6 mt-2 text-xs text-amber-700 bg-amber-50 p-2 rounded border border-amber-200">
          {subsection.amendments.map((amend, idx) => (
            <div key={`amend-${amend.footnote_ref || idx}-${idx}`}>
              <strong>[{amend.footnote_ref}]</strong> {amend.note}
            </div>
          ))}
        </div>
      )}

      {subsection.historical_clauses?.map((clause, idx) => (
        <HistoricalEntry
          key={`historical-clause-${clause.clause_number || idx}-${idx}`}
          entry={clause}
          prefix={clause.clause_number}
        />
      ))}

      {subsection.historical_versions?.map((version, idx) => (
        <HistoricalEntry
          key={`historical-version-${version.subsection_number || idx}-${idx}`}
          entry={version}
          prefix="Originally enacted text"
        />
      ))}

      {historical && subsection.source_note && (
        <p className="mt-2 text-xs text-amber-900">
          <strong>Amendment note:</strong> {subsection.source_note}
        </p>
      )}
    </div>
  );
};

export const SectionCard = ({ section }) => {
  if (!section) return null;

  return (
    <div
      className={`p-6 shadow-md rounded-lg mb-6 border ${
        section.historical ? "bg-red-50/40 border-red-200" : "bg-white border-gray-200"
      }`}
    >
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-bold text-gray-900">
          Section {section.section_number}: {section.title}
        </h3>
        {section.historical && <ChangeBadge type={section.change_type || "omitted"} />}
      </div>

      {section.historical && section.source_note && (
        <p className="mb-4 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          <strong>Amendment note:</strong> {section.source_note}
        </p>
      )}

      {section.subsections && section.subsections.length > 0 ? (
        section.subsections.map((sub, idx) => (
          <SubsectionRenderer
            key={`subsec-${section.section_number}-${sub.subsection_number}-${idx}`}
            subsection={sub}
          />
        ))
      ) : (
        <p className="text-gray-500 italic">No subsections available.</p>
      )}

      {section.historical_subsections?.length > 0 && (
        <div className="mt-5 border-t border-amber-200 pt-4">
          <h4 className="mb-3 text-sm font-bold uppercase tracking-wide text-amber-900">
            Earlier wording from the bare Act
          </h4>
          {section.historical_subsections.map((subsection, idx) => (
            <SubsectionRenderer
              key={`historical-subsection-${subsection.subsection_number || idx}-${idx}`}
              subsection={subsection}
              historical
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default SectionCard;
