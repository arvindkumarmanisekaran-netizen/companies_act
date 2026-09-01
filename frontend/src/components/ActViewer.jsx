import React, { useState } from "react";
// Import SectionCard (or SectionViewer default export) from SectionViewer.jsx
import { SectionCard } from "./SectionViewer";

const ActViewer = ({ data }) => {
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");

  if (!data || !data.chapters) {
    return <div className="p-8 text-center text-gray-500">No document data available.</div>;
  }

  // Filter chapters/sections based on selected chapter or search term
  const filteredChapters = data.chapters.filter((chap) => {
    if (selectedChapter && chap.chapter_number !== selectedChapter) {
      return false;
    }
    if (!searchTerm) return true;

    const term = searchTerm.toLowerCase();
    const matchesTitle = chap.chapter_title?.toLowerCase().includes(term);
    const matchesSection = chap.sections?.some(
      (sec) =>
        sec.section_number?.toLowerCase().includes(term) || sec.title?.toLowerCase().includes(term),
    );

    return matchesTitle || matchesSection;
  });

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
          All Chapters ({data.chapters.length})
        </button>

        <div className="space-y-1 overflow-y-auto max-h-[calc(100vh-12rem)]">
          {data.chapters.map((chap, idx) => (
            <button
              key={idx}
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
        {filteredChapters.map((chap, cIdx) => (
          <div key={cIdx} className="mb-8">
            <div className="border-b pb-2 mb-4">
              <span className="text-xs font-bold text-blue-700 uppercase tracking-wider">
                {chap.chapter_number}
              </span>
              <h2 className="text-xl font-bold text-gray-800">{chap.chapter_title}</h2>
            </div>

            <div className="space-y-4">
              {chap.sections && chap.sections.length > 0 ? (
                chap.sections.map((sec, sIdx) => (
                  /* Standardized rendering using exported SectionCard or SectionViewer alias */
                  <SectionCard key={sIdx} section={sec} />
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
