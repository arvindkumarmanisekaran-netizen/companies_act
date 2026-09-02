import React, { useEffect, useMemo, useRef, useState } from "react";
import { SectionCard } from "./SectionViewer";

const sectionKey = (chapter, section, index) =>
  `${chapter.chapter_number || "chapter"}::${section.section_number || index}::${index}`;

const searchableSectionText = (chapter, section) => {
  const parts = [chapter.chapter_number, chapter.chapter_title, section.section_number, section.title];

  const addHistoricalEntry = (entry) => {
    parts.push(entry?.text, entry?.source_note, entry?.clause_number, entry?.subsection_number);
    entry?.clauses?.forEach((clause) => parts.push(clause.clause_number, clause.text));
  };

  section.subsections?.forEach((subsection) => {
    parts.push(subsection.subsection_number, subsection.text);
    subsection.clauses?.forEach((clause) => parts.push(clause.clause_number, clause.text));
    subsection.amendments?.forEach((amendment) => parts.push(amendment.note));
    subsection.historical_clauses?.forEach(addHistoricalEntry);
    subsection.historical_versions?.forEach(addHistoricalEntry);
  });
  section.historical_subsections?.forEach(addHistoricalEntry);

  return parts.filter(Boolean).join(" ").toLowerCase();
};

const ActViewer = ({ data }) => {
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [selectedSectionKey, setSelectedSectionKey] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");
  const contentRef = useRef(null);
  const rawChapters = data?.chapters || [];

  // Old generated files contain one chapter list from the table of contents and
  // another from the Act body. Keep the richer copy so navigation never doubles.
  const chapters = useMemo(() => {
    const chapterOrder = [];
    const chaptersByNumber = new Map();

    rawChapters.forEach((chapter) => {
      const chapterNumber = chapter.chapter_number?.trim().toUpperCase() || "UNKNOWN";
      const existing = chaptersByNumber.get(chapterNumber);
      if (!existing) {
        chapterOrder.push(chapterNumber);
        chaptersByNumber.set(chapterNumber, chapter);
        return;
      }

      if ((chapter.sections?.length || 0) > (existing.sections?.length || 0)) {
        chaptersByNumber.set(chapterNumber, chapter);
      }
    });

    return chapterOrder.map((chapterNumber) => chaptersByNumber.get(chapterNumber));
  }, [rawChapters]);

  const sectionEntries = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    const entries = [];

    chapters.forEach((chapter) => {
      if (selectedChapter && chapter.chapter_number !== selectedChapter) return;
      (chapter.sections || []).forEach((section, index) => {
        if (term && !searchableSectionText(chapter, section).includes(term)) return;
        entries.push({
          chapter,
          section,
          key: sectionKey(chapter, section, index),
        });
      });
    });

    return entries;
  }, [chapters, searchTerm, selectedChapter]);

  useEffect(() => {
    if (!sectionEntries.length) {
      setSelectedSectionKey(null);
      return;
    }
    if (!sectionEntries.some((entry) => entry.key === selectedSectionKey)) {
      setSelectedSectionKey(sectionEntries[0].key);
    }
  }, [sectionEntries, selectedSectionKey]);

  const selectedIndex = Math.max(
    0,
    sectionEntries.findIndex((entry) => entry.key === selectedSectionKey),
  );
  const selectedEntry = sectionEntries[selectedIndex] || null;

  const goToSection = (index) => {
    const entry = sectionEntries[index];
    if (!entry) return;
    setSelectedSectionKey(entry.key);
    contentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  const chooseChapter = (chapterNumber) => {
    setSelectedChapter(chapterNumber);
    setSelectedSectionKey(null);
  };

  if (!data || !data.chapters) {
    return <div className="p-8 text-center text-gray-500">No document data available.</div>;
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col md:flex-row">
      <aside className="w-full shrink-0 border-r border-gray-200 bg-gray-50 p-4 md:w-80">
        <div className="mb-4">
          <input
            type="search"
            placeholder="Search sections, clauses or history..."
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            className="w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <button
          onClick={() => chooseChapter(null)}
          className={`mb-2 w-full rounded-md px-3 py-2 text-left text-sm font-medium ${
            selectedChapter === null
              ? "bg-blue-100 text-blue-900"
              : "text-gray-700 hover:bg-gray-100"
          }`}
        >
          All Chapters ({chapters.length})
        </button>

        <div className="max-h-48 space-y-1 overflow-y-auto border-b border-gray-200 pb-3 md:max-h-[32vh]">
          {chapters.map((chapter) => (
            <button
              key={chapter.chapter_number}
              onClick={() => chooseChapter(chapter.chapter_number)}
              className={`w-full rounded-md px-3 py-2 text-left text-xs leading-snug ${
                selectedChapter === chapter.chapter_number
                  ? "bg-blue-900 font-semibold text-white"
                  : "text-gray-600 hover:bg-gray-200"
              }`}
            >
              <div className="font-bold">{chapter.chapter_number}</div>
              <div className="truncate">{chapter.chapter_title}</div>
            </button>
          ))}
        </div>

        <div className="mt-3">
          <div className="mb-2 flex items-center justify-between px-1 text-xs font-bold uppercase tracking-wide text-gray-500">
            <span>Sections</span>
            <span>{sectionEntries.length}</span>
          </div>
          <div className="max-h-56 space-y-1 overflow-y-auto md:max-h-[42vh]">
            {sectionEntries.map((entry, index) => (
              <button
                key={entry.key}
                onClick={() => goToSection(index)}
                className={`w-full rounded-md px-3 py-2 text-left text-xs ${
                  selectedEntry?.key === entry.key
                    ? "bg-white font-semibold text-blue-900 shadow-sm ring-1 ring-blue-200"
                    : "text-gray-600 hover:bg-gray-200"
                }`}
              >
                <span className="font-bold">Section {entry.section.section_number}</span>
                <span className="mt-0.5 block truncate">{entry.section.title}</span>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main ref={contentRef} className="max-h-[calc(100vh-4rem)] flex-1 overflow-y-auto p-4 md:p-6">
        {selectedEntry ? (
          <div className="mx-auto max-w-5xl">
            <div className="mb-4 flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-blue-700">
                  {selectedEntry.chapter.chapter_number}
                </span>
                <h2 className="text-xl font-bold text-gray-800">
                  {selectedEntry.chapter.chapter_title}
                </h2>
                <p className="mt-1 text-xs text-gray-500">
                  Section {selectedIndex + 1} of {sectionEntries.length} in this view
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => goToSection(selectedIndex - 1)}
                  disabled={selectedIndex === 0}
                  className="rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  onClick={() => goToSection(selectedIndex + 1)}
                  disabled={selectedIndex === sectionEntries.length - 1}
                  className="rounded bg-blue-900 px-3 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>

            <SectionCard section={selectedEntry.section} />
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-gray-300 p-10 text-center text-gray-500">
            No sections match the current chapter and search filters.
          </div>
        )}
      </main>
    </div>
  );
};

export default ActViewer;
