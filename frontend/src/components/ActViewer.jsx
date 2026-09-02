import React, { useMemo, useState } from "react";
// Import SectionCard (or SectionViewer default export) from SectionViewer.jsx
import { SectionCard } from "./SectionViewer";

const ActViewer = ({ data }) => {
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");
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

      const existingSectionCount = existing.sections?.length || 0;
      const candidateSectionCount = chapter.sections?.length || 0;
      if (candidateSectionCount > existingSectionCount) {
        chaptersByNumber.set(chapterNumber, chapter);
      }
    });

    return chapterOrder.map((chapterNumber) => chaptersByNumber.get(chapterNumber));
  }, [rawChapters]);

  const filteredChapters = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();

    return chapters
      .filter((chapter) => !selectedChapter || chapter.chapter_number === selectedChapter)
      .map((chapter) => {
        if (!term) return chapter;

        const chapterMatches = chapter.chapter_title?.toLowerCase().includes(term);
        const matchingSections = (chapter.sections || []).filter(
          (section) =>
            section.section_number?.toLowerCase().includes(term) ||
            section.title?.toLowerCase().includes(term) ||
            section.subsections?.some(
              (subsection) =>
                subsection.text?.toLowerCase().includes(term) ||
                subsection.clauses?.some((clause) => clause.text?.toLowerCase().includes(term)),
            ),
        );

        return chapterMatches ? chapter : { ...chapter, sections: matchingSections };
      })
      .filter((chapter) => !term || chapter.chapter_title?.toLowerCase().includes(term) || chapter.sections?.length);
  }, [chapters, searchTerm, selectedChapter]);

  if (!data || !data.chapters) {
    return <div className="p-8 text-center text-gray-500">No document data available.</div>;
  }

  return (
    <div className="flex flex-col md:flex-row min-h-[calc(100vh-4rem)]">
      {/* Sidebar Navigation */}
      <aside className="w-full md:w-80 bg-gray-50 border-r border-gray-200 p-4 shrink-0">
        <div className="mb-4">
          <input
            type="text"
            placeholder="Search sections or chapters..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <button
          onClick={() => setSelectedChapter(null)}
          className={`w-full text-left px-3 py-2 rounded-md text-sm font-medium mb-2 ${
            selectedChapter === null
              ? "bg-blue-100 text-blue-900"
              : "text-gray-700 hover:bg-gray-100"
          }`}
        >
          All Chapters ({chapters.length})
        </button>

        <div className="space-y-1 overflow-y-auto max-h-[calc(100vh-12rem)]">
          {chapters.map((chap) => (
            <button
              key={chap.chapter_number}
              onClick={() => setSelectedChapter(chap.chapter_number)}
              className={`w-full text-left px-3 py-2 rounded-md text-xs leading-snug ${
                selectedChapter === chap.chapter_number
                  ? "bg-blue-900 text-white font-semibold"
                  : "text-gray-600 hover:bg-gray-200"
              }`}
            >
              <div className="font-bold">{chap.chapter_number}</div>
              <div className="truncate">{chap.chapter_title}</div>
            </button>
          ))}
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 p-6 overflow-y-auto max-h-[calc(100vh-4rem)]">
        {filteredChapters.map((chap) => (
          <div key={chap.chapter_number} className="mb-8">
            <div className="border-b pb-2 mb-4">
              <span className="text-xs font-bold text-blue-700 uppercase tracking-wider">
                {chap.chapter_number}
              </span>
              <h2 className="text-xl font-bold text-gray-800">{chap.chapter_title}</h2>
            </div>

            <div className="space-y-4">
              {chap.sections && chap.sections.length > 0 ? (
                chap.sections.map((sec, sIdx) => (
                  <SectionCard
                    key={`${chap.chapter_number}-${sec.section_number}-${sIdx}`}
                    section={sec}
                  />
                ))
              ) : (
                <p className="text-sm text-gray-500 italic">No sections in this chapter.</p>
              )}
            </div>
          </div>
        ))}
      </main>
    </div>
  );
};

export default ActViewer;
