import React, { useEffect } from "react";

export const SubsectionRenderer = ({ subsection }) => {
  return (
    <div className="mb-4 pl-4 border-l-2 border-gray-200">
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
    </div>
  );
};

export const SectionCard = ({ section }) => {
  useEffect(() => {
    if (section?.title) {
      console.log(
        `[Section ${section.section_number}] Loaded ${section.subsections?.length || 0} subsections`,
      );
    }
  }, [section]);

  if (!section) return null;

  return (
    <div className="p-6 bg-white shadow-md rounded-lg mb-6 border border-gray-200">
      <h3 className="text-lg font-bold text-gray-900 mb-3">
        Section {section.section_number}: {section.title}
      </h3>

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
    </div>
  );
};

export default SectionCard;
