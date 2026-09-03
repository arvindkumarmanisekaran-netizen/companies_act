import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Menu,
  Search,
  X,
} from "lucide-react";
import { SectionCard } from "./SectionViewer";

const sectionKey = (chapter, section, index) =>
  `${chapter.chapter_number || "chapter"}::${section.section_number || index}::${index}`;

const sectionDisplayTitle = (section) => {
  const sectionNumber = String(section?.section_number || "");
  const escapedSectionNumber = sectionNumber.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  return String(section?.title || "")
    .replace(
      new RegExp(
        `^(?:section\\s+)?${escapedSectionNumber}[.：:–—-]?\\s*`,
        "i",
      ),
      "",
    )
    .trim();
};

const searchableSectionText = (chapter, section) => {
  const parts = [
    chapter.chapter_number,
    chapter.chapter_title,
    section.section_number,
    section.title,
  ];

  const addHistoricalEntry = (entry) => {
    parts.push(
      entry?.text,
      entry?.source_note,
      entry?.clause_number,
      entry?.subsection_number,
    );
    entry?.clauses?.forEach((clause) =>
      parts.push(clause.clause_number, clause.text),
    );
  };

  section.subsections?.forEach((subsection) => {
    parts.push(subsection.subsection_number, subsection.text);
    subsection.clauses?.forEach((clause) =>
      parts.push(clause.clause_number, clause.text),
    );
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
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const contentRef = useRef(null);
  const rawChapters = data?.chapters || [];

  const chapters = useMemo(() => {
    const chapterOrder = [];
    const chaptersByNumber = new Map();

    rawChapters.forEach((chapter) => {
      const chapterNumber =
        chapter.chapter_number?.trim().toUpperCase() || "UNKNOWN";
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

    return chapterOrder.map((chapterNumber) =>
      chaptersByNumber.get(chapterNumber),
    );
  }, [rawChapters]);

  const sectionEntries = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    const entries = [];

    chapters.forEach((chapter) => {
      if (selectedChapter && chapter.chapter_number !== selectedChapter) return;
      (chapter.sections || []).forEach((section, index) => {
        if (term && !searchableSectionText(chapter, section).includes(term)) {
          return;
        }
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

  useEffect(() => {
    if (!mobileNavOpen) return undefined;

    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [mobileNavOpen]);

  const selectedIndex = Math.max(
    0,
    sectionEntries.findIndex((entry) => entry.key === selectedSectionKey),
  );
  const selectedEntry = sectionEntries[selectedIndex] || null;
  const previousEntry = sectionEntries[selectedIndex - 1];
  const nextEntry = sectionEntries[selectedIndex + 1];

  const scrollReaderToTop = () => {
    if (window.matchMedia("(min-width: 768px)").matches) {
      contentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const goToSection = (index) => {
    const entry = sectionEntries[index];
    if (!entry) return;
    setSelectedSectionKey(entry.key);
    setMobileNavOpen(false);
    scrollReaderToTop();
  };

  const chooseChapter = (chapterNumber) => {
    setSelectedChapter(chapterNumber);
    setSelectedSectionKey(null);
  };

  if (!data || !data.chapters) {
    return (
      <div className="p-8 text-center text-gray-500">
        No document data available.
      </div>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] bg-slate-50 md:min-h-[calc(100vh-4rem)]">
      {mobileNavOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-slate-950/50 backdrop-blur-[2px] md:hidden"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <aside
        aria-label="Act navigation"
        className={`fixed inset-y-0 left-0 z-50 flex h-[100dvh] w-[88vw] max-w-sm shrink-0 transform flex-col border-r border-slate-200 bg-white shadow-2xl transition-transform duration-200 md:sticky md:top-16 md:z-20 md:h-[calc(100vh-4rem)] md:w-80 md:translate-x-0 md:shadow-none ${
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-slate-200 bg-blue-950 px-4 py-3 text-white md:hidden">
          <div className="flex items-center gap-2">
            <BookOpen size={19} aria-hidden="true" />
            <div>
              <div className="text-sm font-bold">Browse the Act</div>
              <div className="text-xs text-blue-200">
                Chapters and sections
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            className="grid size-10 place-items-center rounded-lg text-blue-100 hover:bg-white/10"
            aria-label="Close navigation"
          >
            <X size={22} />
          </button>
        </div>

        <div className="border-b border-slate-200 p-4">
          <label className="relative block">
            <Search
              size={17}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              aria-hidden="true"
            />
            <span className="sr-only">Search the Act</span>
            <input
              type="search"
              placeholder="Search sections, clauses or history"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              className="w-full rounded-xl border border-slate-300 bg-slate-50 py-2.5 pl-10 pr-3 text-sm text-slate-900 outline-none transition focus:border-blue-600 focus:bg-white focus:ring-2 focus:ring-blue-100"
            />
          </label>
        </div>

        <div className="flex min-h-0 flex-1 flex-col p-3">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Chapters
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">
              {chapters.length}
            </span>
          </div>

          <div className="max-h-[32dvh] space-y-1 overflow-y-auto border-b border-slate-200 pb-3 md:max-h-[31vh]">
            <button
              type="button"
              onClick={() => chooseChapter(null)}
              className={`w-full rounded-lg px-3 py-2.5 text-left text-sm font-semibold ${
                selectedChapter === null
                  ? "bg-blue-50 text-blue-950 ring-1 ring-inset ring-blue-200"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              All chapters
            </button>

            {chapters.map((chapter) => (
              <button
                type="button"
                key={chapter.chapter_number}
                onClick={() => chooseChapter(chapter.chapter_number)}
                className={`w-full rounded-lg px-3 py-2.5 text-left leading-snug ${
                  selectedChapter === chapter.chapter_number
                    ? "bg-blue-950 text-white shadow-sm"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <span className="block text-xs font-bold uppercase tracking-wide">
                  {chapter.chapter_number}
                </span>
                <span
                  className={`mt-0.5 block truncate text-sm ${
                    selectedChapter === chapter.chapter_number
                      ? "text-blue-100"
                      : "text-slate-500"
                  }`}
                >
                  {chapter.chapter_title}
                </span>
              </button>
            ))}
          </div>

          <div className="mb-2 mt-3 flex items-center justify-between px-1">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Sections
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">
              {sectionEntries.length}
            </span>
          </div>

          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
            {sectionEntries.map((entry, index) => (
              <button
                type="button"
                key={entry.key}
                onClick={() => goToSection(index)}
                className={`w-full rounded-lg border px-3 py-2.5 text-left transition ${
                  selectedEntry?.key === entry.key
                    ? "border-blue-200 bg-blue-50 text-blue-950"
                    : "border-transparent text-slate-700 hover:bg-slate-100"
                }`}
              >
                <span className="block text-sm font-bold">
                  Section {entry.section.section_number}
                </span>
                <span className="mt-0.5 block truncate text-xs text-slate-500">
                  {sectionDisplayTitle(entry.section)}
                </span>
              </button>
            ))}
            {!sectionEntries.length && (
              <p className="px-3 py-6 text-center text-sm text-slate-500">
                No matching sections
              </p>
            )}
          </div>
        </div>
      </aside>

      <main
        ref={contentRef}
        className="min-w-0 flex-1 overflow-visible px-3 pb-28 pt-0 sm:px-5 md:max-h-[calc(100vh-4rem)] md:overflow-y-auto md:p-6"
      >
        <div className="sticky top-14 z-30 -mx-3 mb-3 flex items-center justify-between border-b border-slate-200 bg-white/95 px-3 py-2.5 shadow-sm backdrop-blur sm:-mx-5 sm:px-5 md:hidden">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-blue-950 px-3.5 py-2 text-sm font-bold text-white shadow-sm"
          >
            <Menu size={19} aria-hidden="true" />
            Browse
          </button>
          {selectedEntry && (
            <div className="min-w-0 pl-3 text-right">
              <div className="text-[11px] font-bold uppercase tracking-wider text-blue-700">
                {selectedEntry.chapter.chapter_number}
              </div>
              <div className="truncate text-sm font-bold text-slate-900">
                Section {selectedEntry.section.section_number}
              </div>
            </div>
          )}
        </div>

        {selectedEntry ? (
          <div className="mx-auto max-w-5xl">
            <div className="mb-3 border-b border-slate-300 pb-3 pt-1 md:mb-4 md:flex md:items-end md:justify-between md:gap-4 md:pb-4">
              <div className="min-w-0">
                <span className="text-xs font-bold uppercase tracking-wider text-blue-700">
                  {selectedEntry.chapter.chapter_number}
                </span>
                <h2 className="mt-0.5 text-lg font-extrabold leading-tight text-slate-900 sm:text-xl">
                  {selectedEntry.chapter.chapter_title}
                </h2>
                <p className="mt-2 text-sm font-semibold leading-snug text-slate-600">
                  Section {selectedEntry.section.section_number}:{" "}
                  {sectionDisplayTitle(selectedEntry.section)}
                </p>
              </div>

              <div className="hidden shrink-0 gap-2 md:flex">
                <button
                  type="button"
                  onClick={() => goToSection(selectedIndex - 1)}
                  disabled={selectedIndex === 0}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft size={17} aria-hidden="true" />
                  Previous
                </button>
                <button
                  type="button"
                  onClick={() => goToSection(selectedIndex + 1)}
                  disabled={selectedIndex === sectionEntries.length - 1}
                  className="inline-flex items-center gap-1 rounded-lg bg-blue-950 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-900 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next
                  <ChevronRight size={17} aria-hidden="true" />
                </button>
              </div>
            </div>

            <SectionCard section={selectedEntry.section} />
          </div>
        ) : (
          <div className="mx-auto mt-6 max-w-lg rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
            <Search className="mx-auto mb-3 text-slate-400" aria-hidden="true" />
            <h2 className="font-bold text-slate-900">No matching sections</h2>
            <p className="mt-1 text-sm text-slate-500">
              Try another search or choose all chapters.
            </p>
          </div>
        )}
      </main>

      {selectedEntry && (
        <nav
          aria-label="Section pagination"
          className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-2 gap-2 border-t border-slate-200 bg-white/95 px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3 shadow-[0_-8px_24px_rgba(15,23,42,0.1)] backdrop-blur md:hidden"
        >
          <button
            type="button"
            onClick={() => goToSection(selectedIndex - 1)}
            disabled={!previousEntry}
            className="flex min-h-12 min-w-0 items-center gap-2 rounded-xl border border-slate-300 px-3 text-left text-slate-700 disabled:opacity-35"
          >
            <ChevronLeft className="shrink-0" size={20} aria-hidden="true" />
            <span className="min-w-0">
              <span className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Previous
              </span>
              <span className="block truncate text-sm font-bold">
                {previousEntry
                  ? `Section ${previousEntry.section.section_number}`
                  : "Start"}
              </span>
            </span>
          </button>
          <button
            type="button"
            onClick={() => goToSection(selectedIndex + 1)}
            disabled={!nextEntry}
            className="flex min-h-12 min-w-0 items-center justify-end gap-2 rounded-xl bg-blue-950 px-3 text-right text-white disabled:opacity-35"
          >
            <span className="min-w-0">
              <span className="block text-[11px] font-semibold uppercase tracking-wide text-blue-200">
                Next
              </span>
              <span className="block truncate text-sm font-bold">
                {nextEntry
                  ? `Section ${nextEntry.section.section_number}`
                  : "End"}
              </span>
            </span>
            <ChevronRight className="shrink-0" size={20} aria-hidden="true" />
          </button>
        </nav>
      )}
    </div>
  );
};

export default ActViewer;
