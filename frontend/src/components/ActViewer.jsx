import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Contrast,
  Info,
  Inbox,
  LogOut,
  Menu,
  MessageSquareText,
  MonitorCog,
  Moon,
  Search,
  Settings,
  Sun,
  Type,
  X,
} from "lucide-react";
import { prefetchSectionTimeline, SectionCard } from "./SectionViewer";
import AdminInbox from "./AdminInbox";
import { captureEvent } from "../analytics";

const apiBaseUrl = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const isMobileApp = import.meta.env.VITE_MOBILE_APP === "true";
const APP_SHARE_URL = "https://companiesact.site";
const ADMIN_NAMES = new Set(["arv@momo", "nak@momo"]);

const sectionKey = (chapter, section) =>
  `${chapter.chapter_number || "chapter"}::${section.section_number || "section"}`;

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

const ActViewer = ({ data, asOfDate, adminMode = false, userName = "", onLogout }) => {
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [selectedSectionKey, setSelectedSectionKey] = useState(null);
  const [expandedChapters, setExpandedChapters] = useState(() => new Set());
  const [searchTerm, setSearchTerm] = useState("");
  const [navigationResults, setNavigationResults] = useState([]);
  const [navigationResultQuery, setNavigationResultQuery] = useState("");
  const [navigationSearching, setNavigationSearching] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [themePreference, setThemePreference] = useState(() => localStorage.getItem("companies-act:theme:v2") || "light");
  const [fontScale, setFontScale] = useState(() => Number(localStorage.getItem("companies-act:font-scale")) || 100);
  const [fontFamily, setFontFamily] = useState(() => localStorage.getItem("companies-act:font-family") || "sans");
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackToast, setFeedbackToast] = useState(null);
  const [inboxOpen, setInboxOpen] = useState(false);
  const [settingsNotice, setSettingsNotice] = useState("");
  const [navigationDirection, setNavigationDirection] = useState("forward");
  const [swipeOffset, setSwipeOffset] = useState(null);
  const [swipeDirection, setSwipeDirection] = useState(0);
  const [swipeSettling, setSwipeSettling] = useState(false);
  const [swipeHandoff, setSwipeHandoff] = useState(false);
  const [swipePreviewEntry, setSwipePreviewEntry] = useState(null);
  const [bottomTabsTarget, setBottomTabsTarget] = useState(null);
  const contentRef = useRef(null);
  const swipeStageRef = useRef(null);
  const swipeRef = useRef(null);
  const swipeTimerRef = useRef(null);
  const swipeCompletionRef = useRef(null);
  const suppressSwipeClickRef = useRef(false);
  const suppressSwipeClickTimerRef = useRef(null);
  const preserveBrowseContextRef = useRef(false);
  const trackedSectionRef = useRef(null);
  const rawChapters = data?.chapters || [];

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
      if (!term && selectedChapter && chapter.chapter_number !== selectedChapter) return;
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

  const allSectionEntries = useMemo(
    () => chapters.flatMap((chapter) => (chapter.sections || []).map((section, index) => ({
      chapter,
      section,
      key: sectionKey(chapter, section, index),
    }))),
    [chapters],
  );

  useEffect(() => {
    const query = searchTerm.trim();
    if (query.length < 2 || /^(?:section\s*)?\d+[A-Za-z]?\.?$/i.test(query)) {
      setNavigationResults([]);
      setNavigationResultQuery("");
      setNavigationSearching(false);
      return undefined;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setNavigationSearching(true);
      try {
        const response = await fetch(`${apiBaseUrl}/api/navigation-search?q=${encodeURIComponent(query)}&limit=6`, {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(`Search failed (${response.status})`);
        const payload = await response.json();
        setNavigationResults(payload.results || []);
        setNavigationResultQuery(query.toLowerCase());
      } catch (error) {
        if (error.name !== "AbortError") {
          setNavigationResults([]);
          setNavigationResultQuery("");
        }
      } finally {
        if (!controller.signal.aborted) setNavigationSearching(false);
      }
    }, 220);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [searchTerm]);

  useEffect(() => {
    if (preserveBrowseContextRef.current && allSectionEntries.some((entry) => entry.key === selectedSectionKey)) return;
    if (!sectionEntries.length) {
      setSelectedSectionKey(null);
      return;
    }

    if (!allSectionEntries.some((entry) => entry.key === selectedSectionKey)) {
      setSelectedSectionKey(allSectionEntries[0].key);
    }
  }, [allSectionEntries, sectionEntries, selectedSectionKey]);

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

  useEffect(() => {
    if (!mobileNavOpen) {
      setSettingsOpen(false);
    }
  }, [mobileNavOpen]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const resolved = themePreference === "auto" ? (media.matches ? "dark" : "light") : themePreference;
      document.documentElement.dataset.readerTheme = resolved;
      document.documentElement.dataset.readerThemePreference = themePreference;
    };
    localStorage.setItem("companies-act:theme:v2", themePreference);
    applyTheme();
    media.addEventListener?.("change", applyTheme);
    return () => media.removeEventListener?.("change", applyTheme);
  }, [themePreference]);

  useEffect(() => {
    const boundedScale = Math.min(130, Math.max(85, Number(fontScale) || 100));
    document.documentElement.style.fontSize = `${boundedScale}%`;
    document.documentElement.dataset.readerFont = fontFamily;
    localStorage.setItem("companies-act:font-scale", String(boundedScale));
    localStorage.setItem("companies-act:font-family", fontFamily);
  }, [fontFamily, fontScale]);

  const activeSectionEntries = sectionEntries.some((entry) => entry.key === selectedSectionKey)
    ? sectionEntries
    : allSectionEntries;
  const selectedIndex = Math.max(
    0,
    activeSectionEntries.findIndex((entry) => entry.key === selectedSectionKey),
  );
  const selectedEntry = activeSectionEntries[selectedIndex] || null;
  const swipeSelectedIndex = Math.max(
    0,
    allSectionEntries.findIndex((entry) => entry.key === selectedSectionKey),
  );

  useEffect(() => {
    if (adminMode || !selectedEntry || trackedSectionRef.current === selectedEntry.key) return;
    trackedSectionRef.current = selectedEntry.key;
    captureEvent("section_opened", {
      chapter_number: selectedEntry.chapter.chapter_number,
      section_number: selectedEntry.section.section_number,
      as_of_date: asOfDate,
    });
  }, [adminMode, asOfDate, selectedEntry?.key]);

  useEffect(() => {
    if (!selectedEntry || adminMode) return;
    for (let distance = 1; distance <= 5; distance += 1) {
      [swipeSelectedIndex - distance, swipeSelectedIndex + distance].forEach((index) => {
        const entry = allSectionEntries[index];
        if (entry) prefetchSectionTimeline(entry.section.section_number, asOfDate);
      });
    }
  }, [adminMode, allSectionEntries, asOfDate, selectedEntry?.key, swipeSelectedIndex]);

  useEffect(() => () => {
    window.clearTimeout(swipeTimerRef.current);
    window.clearTimeout(suppressSwipeClickTimerRef.current);
    swipeCompletionRef.current = null;
  }, []);

  const scrollReaderToTop = () => {
    contentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  const goToSection = (index, entries = sectionEntries, animate = true, scrollToTop = true) => {
    const entry = entries[index];
    if (!entry) return;
    captureEvent("section_navigation", {
      section_number: entry.section.section_number,
      navigation: index < selectedIndex ? "previous" : "next",
    });
    preserveBrowseContextRef.current = false;
    setNavigationDirection(animate ? (index < selectedIndex ? "back" : "forward") : "none");
    setSelectedSectionKey(entry.key);
    setMobileNavOpen(false);
    if (scrollToTop) scrollReaderToTop();
  };

  const swipeBlocked = (target) => target.closest("input, textarea, select, [contenteditable='true'], [role='dialog'], [data-no-swipe]");
  const startSwipe = (event) => {
    if (swipeSettling || swipeHandoff || adminMode || !window.matchMedia("(max-width: 767px)").matches || !event.isPrimary || swipeBlocked(event.target)) return;
    swipeRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, startedAt: performance.now(), active: false, offset: 0 };
  };
  const moveSwipe = (event) => {
    const gesture = swipeRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - gesture.x;
    const deltaY = event.clientY - gesture.y;
    if (!gesture.active) {
      if (Math.abs(deltaX) < 8) return;
      if (Math.abs(deltaX) <= Math.abs(deltaY) * 1.1) { swipeRef.current = null; return; }
      gesture.active = true;
      suppressSwipeClickRef.current = true;
      event.currentTarget.setPointerCapture?.(event.pointerId);
    }
    event.preventDefault();
    const hasDestination = deltaX < 0 ? swipeSelectedIndex < allSectionEntries.length - 1 : swipeSelectedIndex > 0;
    const width = swipeStageRef.current?.getBoundingClientRect().width || contentRef.current?.clientWidth || window.innerWidth;
    const resisted = hasDestination ? deltaX : deltaX * 0.22;
    gesture.offset = Math.max(-width, Math.min(width, resisted));
    const nextDirection = gesture.offset < 0 ? 1 : -1;
    setSwipeDirection(nextDirection);
    setSwipePreviewEntry(allSectionEntries[swipeSelectedIndex + nextDirection] || null);
    setSwipeOffset(gesture.offset);
  };
  const completeSwipeTransition = () => {
    const pending = swipeCompletionRef.current;
    if (!pending) return;
    swipeCompletionRef.current = null;
    window.clearTimeout(swipeTimerRef.current);
    if (!pending.shouldNavigate) {
      setSwipeOffset(null);
      setSwipeDirection(0);
      setSwipePreviewEntry(null);
      setSwipeSettling(false);
      return;
    }
    setSwipeHandoff(true);
    setSwipeSettling(false);
    const destinationEntry = pending.entries[pending.destination];
    if (destinationEntry) {
      setSearchTerm("");
      setSelectedChapter(destinationEntry.chapter.chapter_number);
    }
    goToSection(pending.destination, pending.entries, false, false);
    swipeTimerRef.current = window.setTimeout(() => {
      setSwipeOffset(null);
      setSwipeDirection(0);
      setSwipePreviewEntry(null);
      setSwipeHandoff(false);
    }, 120);
  };
  const finishSwipe = (event, cancelled = false) => {
    const gesture = swipeRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    swipeRef.current = null;
    if (!gesture.active) return;
    window.clearTimeout(suppressSwipeClickTimerRef.current);
    suppressSwipeClickTimerRef.current = window.setTimeout(() => {
      suppressSwipeClickRef.current = false;
    }, 80);
    const width = swipeStageRef.current?.getBoundingClientRect().width || contentRef.current?.clientWidth || window.innerWidth;
    const elapsed = Math.max(1, performance.now() - gesture.startedAt);
    const velocity = gesture.offset / elapsed;
    const direction = gesture.offset < 0 ? 1 : -1;
    const destination = swipeSelectedIndex + direction;
    const canNavigate = destination >= 0 && destination < allSectionEntries.length;
    const shouldNavigate = !cancelled && canNavigate && (Math.abs(gesture.offset) >= width * 0.2 || Math.abs(velocity) >= 0.42);
    setSwipeSettling(true);
    setSwipeOffset(shouldNavigate ? (direction > 0 ? -width : width) : 0);
    window.clearTimeout(swipeTimerRef.current);
    swipeCompletionRef.current = { shouldNavigate, destination, entries: allSectionEntries };
    swipeTimerRef.current = window.setTimeout(completeSwipeTransition, 320);
  };

  const chooseChapter = (chapterNumber) => {
    preserveBrowseContextRef.current = false;
    setSelectedChapter(chapterNumber);
    setSelectedSectionKey(null);
    captureEvent("chapter_selected", { chapter_number: chapterNumber || "all" });
  };

  const revealProvision = (provisionId, attempt = 0) => {
    if (!provisionId || attempt > 80) return;
    const target = document.getElementById(provisionId);
    if (!target) {
      window.setTimeout(() => revealProvision(provisionId, attempt + 1), 50);
      return;
    }
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("definition-target-flash");
    requestAnimationFrame(() => target.classList.add("definition-target-flash"));
    window.setTimeout(() => target.classList.remove("definition-target-flash"), 1800);
  };

  const jumpToSection = (value, provisionId = null) => {
    const requested = String(value || "").trim().replace(/^section\s+/i, "").replace(/\.$/, "").toUpperCase();
    if (!requested) return false;
    for (const chapter of chapters) {
      const index = (chapter.sections || []).findIndex((item) => String(item.section_number || "").trim().toUpperCase() === requested);
      if (index >= 0) {
        const destinationNumber = Number.parseInt(requested, 10);
        const currentNumber = Number.parseInt(selectedEntry?.section?.section_number, 10);
        setNavigationDirection(Number.isFinite(destinationNumber) && Number.isFinite(currentNumber) && destinationNumber < currentNumber ? "back" : "forward");
        preserveBrowseContextRef.current = true;
        setSelectedSectionKey(sectionKey(chapter, chapter.sections[index], index));
        setSearchTerm("");
        setNavigationResults([]);
        setNavigationResultQuery("");
        setMobileNavOpen(false);
        if (provisionId) revealProvision(provisionId);
        else requestAnimationFrame(scrollReaderToTop);
        return true;
      }
    }
    return false;
  };

  const runNavigationSearch = async (value) => {
    const query = String(value || "").trim();
    if (!query) return;
    captureEvent("search_submitted", { query });
    if (jumpToSection(query)) {
      captureEvent("search_result_selected", { query, section_number: query.replace(/^section\s+/i, ""), selection_type: "direct" });
      return;
    }

    let matches = navigationResultQuery === query.toLowerCase() ? navigationResults : [];
    if (!matches.length) {
      setNavigationSearching(true);
      try {
        const response = await fetch(`${apiBaseUrl}/api/navigation-search?q=${encodeURIComponent(query)}&limit=6`, {
          headers: { Accept: "application/json" },
        });
        if (response.ok) {
          const payload = await response.json();
          matches = payload.results || [];
          setNavigationResults(matches);
          setNavigationResultQuery(query.toLowerCase());
        }
      } finally {
        setNavigationSearching(false);
      }
    }

    captureEvent("search_completed", { query, result_count: matches.length });
    const destination = matches[0];
    if (destination) {
      captureEvent("search_result_selected", { query, section_number: destination.section_number, selection_type: "first_result" });
      jumpToSection(destination.section_number, destination.provision_id);
    }
  };

  const shareApp = async () => {
    setSettingsNotice("");
    captureEvent("share_started", { method: navigator.share ? "native" : "clipboard" });
    try {
      if (navigator.share) {
        await navigator.share({
          title: "Companies Act, 2013",
          text: "Read the current Companies Act, 2013 with amendment histories, rules and notifications.",
          url: APP_SHARE_URL,
        });
        setSettingsNotice("Share sheet opened.");
        captureEvent("share_completed", { method: "native" });
        return;
      }
      await navigator.clipboard.writeText(APP_SHARE_URL);
      setSettingsNotice("App link copied.");
      captureEvent("share_completed", { method: "clipboard" });
    } catch (error) {
      if (error?.name !== "AbortError") setSettingsNotice("Could not share automatically. The app link is companiesact.site.");
    }
  };

  const normalizedUserName = userName.trim().toLowerCase();
  const isNamedAdmin = ADMIN_NAMES.has(normalizedUserName);

  const submitFeedback = async () => {
    const message = feedbackText.trim();
    if (!message || feedbackBusy) return;

    setFeedbackBusy(true);
    setSettingsNotice("");
    captureEvent("feedback_started", { section_number: selectedEntry?.section?.section_number || null });
    try {
      const response = await fetch(`${apiBaseUrl}/api/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sender_name: userName || "Reader",
          message,
          source: isMobileApp ? "android" : "web",
          context_url: isMobileApp
            ? `section:${selectedEntry?.section?.section_number || "unknown"}`
            : window.location.href,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Could not send feedback");
      }
      setFeedbackText("");
      captureEvent("feedback_submitted", { section_number: selectedEntry?.section?.section_number || null });
      setFeedbackToast({ type: "success", message: "Feedback sent to both administrators." });
    } catch (error) {
      captureEvent("feedback_failed", { section_number: selectedEntry?.section?.section_number || null, error: error.message || "unknown" });
      setFeedbackToast({ type: "error", message: error.message || "Could not send feedback. Please try again." });
    } finally {
      setFeedbackBusy(false);
    }
  };

  useEffect(() => {
    if (!feedbackToast) return undefined;
    const timer = window.setTimeout(() => setFeedbackToast(null), 3500);
    return () => window.clearTimeout(timer);
  }, [feedbackToast]);
  useEffect(() => {
    const navigate = (event) => jumpToSection(event.detail?.sectionNumber, event.detail?.provisionId);
    const navigateFromHash = () => {
      const provisionMatch = window.location.hash.match(/^#provision-(.+)$/i);
      if (provisionMatch) {
        const provisionId = decodeURIComponent(provisionMatch[1]);
        const sectionMatch = provisionId.match(/:section:([^:]+)/i);
        if (sectionMatch) jumpToSection(sectionMatch[1], provisionId);
        return;
      }
      const match = window.location.hash.match(/^#section-(.+)$/i);
      if (match) jumpToSection(decodeURIComponent(match[1]));
    };
    window.addEventListener("companies-act:navigate-section", navigate);
    window.addEventListener("popstate", navigateFromHash);
    navigateFromHash();
    return () => {
      window.removeEventListener("companies-act:navigate-section", navigate);
      window.removeEventListener("popstate", navigateFromHash);
    };
  }, [chapters]);

  if (!data || !data.chapters) {
    return <div className="p-8 text-center text-gray-500">No document data available.</div>;
  }

  return (
    <div className={`flex min-h-0 overflow-hidden bg-slate-50 ${adminMode ? "h-[calc(100dvh-3.5rem)] md:h-[calc(100dvh-6.5rem)]" : "h-[100dvh] md:h-[calc(100dvh-4rem)]"}`}>
      {mobileNavOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="mobile-nav-backdrop fixed inset-0 z-40 bg-slate-950/50 backdrop-blur-[2px] md:hidden"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <aside
        aria-label="Act navigation"
        className={`mobile-nav-drawer fixed inset-y-0 left-0 z-50 flex h-[100dvh] w-[88vw] max-w-sm shrink-0 transform flex-col overflow-hidden border-r border-slate-200 bg-white shadow-2xl md:relative md:inset-auto md:top-0 md:z-20 md:h-full md:w-80 md:translate-x-0 md:shadow-none ${
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-slate-200 bg-blue-950 px-4 py-3 text-white md:hidden">
          <div className="flex items-center gap-2">
            <BookOpen size={19} aria-hidden="true" />
            <div>
              <div className="text-sm font-bold">Browse the Act</div>
              <div className="text-xs text-blue-200">Chapter → section</div>
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

        <div className="relative border-b border-slate-200 p-4">
          <form onSubmit={(event) => { event.preventDefault(); runNavigationSearch(searchTerm); }} className="flex gap-2 md:hidden">
            <label className="relative min-w-0 flex-1">
              <Search size={17} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden="true"/>
              <span className="sr-only">Search by section, concept or form</span>
              <input type="search" inputMode="search" enterKeyHint="search" placeholder="Section, concept or form" value={searchTerm} onChange={(event) => { preserveBrowseContextRef.current = false; setNavigationResults([]); setNavigationResultQuery(""); setSearchTerm(event.target.value); }} aria-controls={navigationResults.length ? "mobile-navigation-search-results" : undefined} className="w-full rounded-xl border border-slate-300 bg-white py-2.5 pl-10 pr-3 text-sm text-slate-900 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100"/>
            </label>
            <button type="submit" disabled={!searchTerm.trim() || navigationSearching} className="motion-control grid size-11 shrink-0 place-items-center rounded-xl bg-blue-950 text-white disabled:opacity-40" aria-label="Run search"><Search size={19}/></button>
          </form>

          <form onSubmit={(event) => { event.preventDefault(); runNavigationSearch(searchTerm); }} className="hidden md:block">
            <label className="relative block">
              <Search size={17} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden="true"/>
              <span className="sr-only">Search by section, concept or form</span>
              <input type="search" placeholder="Section, concept or form" value={searchTerm} onChange={(event) => { preserveBrowseContextRef.current = false; setNavigationResults([]); setNavigationResultQuery(""); setSearchTerm(event.target.value); }} aria-controls={navigationResults.length ? "desktop-navigation-search-results" : undefined} className="w-full rounded-xl border border-slate-300 bg-slate-50 py-2.5 pl-10 pr-3 text-sm text-slate-900 outline-none transition focus:border-blue-600 focus:bg-white focus:ring-2 focus:ring-blue-100"/>
            </label>
          </form>

          {(navigationSearching || navigationResults.length > 0) && searchTerm.trim() && (
            <div id="navigation-search-results" role="listbox" className="absolute inset-x-4 top-[calc(100%-0.45rem)] z-40 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
              {navigationSearching && navigationResults.length === 0 && <div className="px-3 py-2.5 text-xs font-semibold text-slate-500">Finding the best section…</div>}
              {navigationResults.map((result) => (
                <button
                  key={`${result.match_type}-${result.section_number}`}
                  type="button"
                  role="option"
                  onClick={() => {
                    captureEvent("search_result_selected", {
                      query: searchTerm.trim(),
                      section_number: result.section_number,
                      selection_type: "suggestion",
                    });
                    jumpToSection(result.section_number, result.provision_id);
                  }}
                  className="flex w-full items-center gap-3 border-b border-slate-100 px-3 py-2.5 text-left last:border-0 hover:bg-blue-50"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-blue-950 text-xs font-extrabold text-white">{result.section_number}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-bold text-slate-900">{result.title || `Section ${result.section_number}`}</span>
                    <span className="block truncate text-[11px] font-semibold uppercase tracking-wide text-slate-500">{result.match_type} · {result.matched_term}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col p-3">
          <label className="mb-3 block md:hidden">
            <span className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-500">Chapter</span>
            <select value={selectedChapter || ""} onChange={(event) => chooseChapter(event.target.value || null)} className="w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-sm font-bold text-slate-800 outline-none focus:border-blue-700 focus:ring-2 focus:ring-blue-100">
              <option value="">All chapters</option>
              {chapters.map((chapter) => <option key={chapter.chapter_number} value={chapter.chapter_number}>{chapter.chapter_number} — {chapter.chapter_title}</option>)}
            </select>
          </label>

          <div className="mb-2 hidden items-center justify-between px-1 md:flex">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Chapters
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">
              {chapters.length}
            </span>
          </div>

          <div className="hidden min-h-0 flex-1 touch-pan-y space-y-1 overflow-y-auto overscroll-contain border-b border-slate-200 pb-3 [-webkit-overflow-scrolling:touch] md:block">
            <button
              type="button"
              onClick={() => chooseChapter(null)}
              className={`motion-control w-full rounded-lg px-3 py-2.5 text-left text-sm font-semibold ${
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
                className={`motion-control w-full rounded-lg px-3 py-2.5 text-left leading-snug ${
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

          <div className="mb-2 flex items-center justify-between px-1 md:mt-3">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Sections
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">
              {sectionEntries.length}
            </span>
          </div>

          <div className="min-h-0 flex-1 touch-pan-y space-y-1 overflow-y-auto overscroll-contain [-webkit-overflow-scrolling:touch] md:flex-[2]">
            {sectionEntries.map((entry, index) => (
              <button
                type="button"
                key={entry.key}
                onClick={() => goToSection(index)}
                className={`section-nav-item motion-control w-full rounded-lg border px-3 py-2.5 text-left transition ${
                  selectedEntry?.key === entry.key
                    ? "border-blue-200 bg-blue-50 text-blue-950"
                    : "border-transparent text-slate-700 hover:bg-slate-100"
                }`}
              >
                <span className="block text-sm font-semibold leading-snug">
                  <strong className="font-extrabold">{entry.section.section_number}.</strong>{" "}
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

        <div className="flex items-center justify-between gap-3 border-t border-slate-200 bg-white px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3 md:pb-3">
          <div className="flex min-w-0 items-center gap-2 text-blue-950"><BookOpen size={20}/><div className="min-w-0"><strong className="block truncate text-sm">Companies Act, 2013</strong><span className="block truncate text-[11px] text-slate-500">{userName || "India’s company law reference"}</span></div></div>
          <button type="button" onClick={() => { setSettingsNotice(""); setSettingsOpen(true); captureEvent("settings_opened"); }} className="motion-control grid size-11 shrink-0 place-items-center rounded-xl border border-slate-300 bg-slate-50 text-blue-950" aria-label="Open settings"><Settings size={21}/></button>
        </div>

        {settingsOpen && (
          <section className="absolute inset-0 z-[60] flex flex-col bg-slate-50" aria-label="Settings menu">
            <header className="flex items-center gap-3 bg-blue-950 px-3 py-3 text-white">
              <button type="button" onClick={() => setSettingsOpen(false)} className="grid size-10 place-items-center rounded-lg hover:bg-white/10" aria-label="Back to navigation"><ArrowLeft size={21}/></button>
              <div><h2 className="text-base font-extrabold">Settings</h2><p className="text-xs text-blue-200">Reading and app preferences</p></div>
            </header>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 pb-[calc(2rem+env(safe-area-inset-bottom))]">
              {!adminMode && userName && <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-center gap-3"><div className="min-w-0 flex-1"><h3 className="truncate font-extrabold text-slate-900">{userName}</h3><p className="text-xs text-slate-500">Signed-in reader</p></div><button type="button" onClick={onLogout} className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-bold text-red-700"><LogOut size={15}/>Logout</button></div>
              </section>}
              {isNamedAdmin && <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-blue-50 text-blue-950"><Inbox size={19}/></span><div className="min-w-0 flex-1"><h3 className="font-extrabold text-slate-900">Admin inbox</h3><p className="text-xs text-slate-500">Feedback and complaints from readers.</p></div><button type="button" onClick={() => setInboxOpen(true)} className="rounded-lg bg-blue-950 px-3 py-2 text-xs font-bold text-white">Open</button></div>
              </section>}
              <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-3 flex items-center gap-2"><Sun size={18} className="text-blue-900"/><h3 className="font-extrabold text-slate-900">Appearance</h3></div>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    ["auto", "Auto", MonitorCog],
                    ["light", "Light", Sun],
                    ["dark", "Dark", Moon],
                    ["contrast", "High contrast", Contrast],
                  ].map(([value, label, Icon]) => <button key={value} type="button" onClick={() => { setThemePreference(value); captureEvent("theme_changed", { theme: value }); }} className={`motion-control flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left text-xs font-bold ${themePreference === value ? "border-blue-900 bg-blue-950 text-white" : "border-slate-300 bg-white text-slate-700"}`}><Icon size={16}/>{label}</button>)}
                </div>
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-3 flex items-center gap-2"><Type size={18} className="text-blue-900"/><h3 className="font-extrabold text-slate-900">Font settings</h3></div>
                <label className="block text-xs font-bold text-slate-600">Text size: {fontScale}%<input type="range" min="85" max="130" step="5" value={fontScale} onChange={(event) => { const value = Number(event.target.value); setFontScale(value); captureEvent("font_size_changed", { font_scale: value }); }} className="mt-2 w-full accent-blue-950"/></label>
                <div className="mt-3 grid grid-cols-2 gap-2"><button type="button" onClick={() => { setFontFamily("sans"); captureEvent("font_family_changed", { font_family: "sans" }); }} className={`rounded-xl border px-3 py-2.5 text-sm font-bold ${fontFamily === "sans" ? "border-blue-900 bg-blue-50 text-blue-950" : "border-slate-300 text-slate-700"}`}>Sans serif</button><button type="button" onClick={() => { setFontFamily("serif"); captureEvent("font_family_changed", { font_family: "serif" }); }} className={`rounded-xl border px-3 py-2.5 font-serif text-sm font-bold ${fontFamily === "serif" ? "border-blue-900 bg-blue-50 text-blue-950" : "border-slate-300 text-slate-700"}`}>Serif</button></div>
              </section>

              <section className="hidden">
                <div className="hidden" />
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-3 flex items-center gap-2"><MessageSquareText size={18} className="text-blue-900"/><h3 className="font-extrabold text-slate-900">Feedback and complaints</h3></div>
                <textarea value={feedbackText} onChange={(event) => setFeedbackText(event.target.value)} placeholder="Tell us what happened or what could be improved…" className="min-h-28 w-full resize-y rounded-xl border border-slate-300 bg-white p-3 text-sm outline-none focus:border-blue-700 focus:ring-2 focus:ring-blue-100"/>
                <button type="button" onClick={submitFeedback} disabled={!feedbackText.trim() || feedbackBusy} className="mt-3 inline-flex rounded-lg bg-blue-950 px-4 py-2.5 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-40">{feedbackBusy ? "Sending…" : "Send to administrators"}</button>
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-2 flex items-center gap-2"><Info size={18} className="text-blue-900"/><h3 className="font-extrabold text-slate-900">About Us</h3></div>
                <p className="text-sm leading-6 text-slate-600">Companies Act is a legal reference designed to make the current Act, its amendment history, related rules, notifications and practical insights easier to read and navigate.</p>
              </section>
              {settingsNotice && <p className="rounded-xl bg-emerald-50 px-3 py-2 text-center text-xs font-bold text-emerald-800">{settingsNotice}</p>}
            </div>
          </section>
        )}
      </aside>

      <main
        ref={contentRef}
        onPointerDown={startSwipe}
        onPointerMove={moveSwipe}
        onPointerUp={(event) => finishSwipe(event)}
        onPointerCancel={(event) => finishSwipe(event, true)}
        onClickCapture={(event) => {
          if (!suppressSwipeClickRef.current) return;
          event.preventDefault();
          event.stopPropagation();
          suppressSwipeClickRef.current = false;
        }}
        className="h-full min-h-0 min-w-0 flex-1 touch-pan-y overflow-x-hidden overflow-y-auto overscroll-contain px-3 pb-[calc(5rem+env(safe-area-inset-bottom))] pt-0 [overflow-anchor:none] [-webkit-overflow-scrolling:touch] sm:px-5 md:px-6 md:pb-20 md:pt-0"
      >
        <div className="sticky top-0 z-40 -mx-3 mb-0 flex min-h-14 items-center gap-3 border-b border-slate-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur sm:-mx-5 sm:px-5 md:hidden">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="motion-control grid size-11 shrink-0 place-items-center rounded-xl bg-blue-950 text-white shadow-sm"
            aria-label="Open navigation"
          >
            <Menu size={19} aria-hidden="true" />
          </button>
          {selectedEntry && (
            <div className="min-w-0 flex-1 text-left"><div className="text-[15px] font-bold leading-snug text-slate-900 line-clamp-2">Section {selectedEntry.section.section_number}: {sectionDisplayTitle(selectedEntry.section)}</div></div>
          )}
        </div>

        {selectedEntry && (
          <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 bg-white/95 pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] shadow-[0_-8px_22px_-14px_rgba(15,23,42,0.5)] backdrop-blur md:left-80 md:pl-0 md:pr-0">
            <div className="pointer-events-auto mx-auto max-w-5xl border-x border-t border-slate-300 bg-white" ref={setBottomTabsTarget} />
          </div>
        )}

        {selectedEntry ? (
          <div ref={swipeStageRef} className="relative">
          {swipeDirection !== 0 && swipePreviewEntry && <div aria-hidden="true" className={`reader-drag-scene pointer-events-none absolute inset-x-0 top-0 mx-auto max-w-5xl will-change-transform ${swipeHandoff ? "z-20" : "z-0"}`} style={{ transform: swipeHandoff ? "translate3d(0,0,0)" : `translate3d(calc(${swipeDirection > 0 ? "100%" : "-100%"} + ${swipeOffset || 0}px),0,0)`, transition: swipeSettling ? "transform 190ms cubic-bezier(.2,.82,.25,1)" : "none" }}><SectionCard section={swipePreviewEntry.section} asOfDate={asOfDate} showWorkspaceTabs={false}/></div>}
          <div key={`${selectedEntry.key}:${asOfDate}`} onTransitionEnd={(event) => { if (event.target === event.currentTarget && event.propertyName === "transform") completeSwipeTransition(); }} className={`reader-scene reader-scene-${navigationDirection} relative z-10 mx-auto max-w-5xl ${swipeOffset !== null ? "reader-drag-scene will-change-transform" : ""}`} style={swipeOffset !== null ? { transform: swipeHandoff ? "translate3d(0,0,0)" : `translate3d(${swipeOffset}px,0,0)`, transition: swipeSettling ? "transform 190ms cubic-bezier(.2,.82,.25,1)" : "none" } : undefined}>
            <SectionCard key={`${selectedEntry.key}:${asOfDate}`} section={selectedEntry.section} asOfDate={asOfDate} adminMode={adminMode} tabsPortalTarget={bottomTabsTarget} readerHeader={
            <div className="hidden border-b border-slate-300 px-3 py-2 sm:px-4 md:flex md:items-end md:justify-between md:gap-4 md:px-4 md:pb-4 md:pt-2">
              <div className="min-w-0">
                <span className="hidden text-xs font-bold uppercase tracking-wider text-blue-700 md:inline">
                  {selectedEntry.chapter.chapter_number}
                </span>
                <h2 className="mt-0.5 hidden text-lg font-extrabold leading-tight text-slate-900 sm:text-xl md:block">
                  {selectedEntry.chapter.chapter_title}
                </h2>
                <p className="text-[15px] font-semibold leading-snug text-slate-700 md:mt-2 md:text-sm md:text-slate-600">
                  Section {selectedEntry.section.section_number}:{" "}
                  {sectionDisplayTitle(selectedEntry.section)}
                </p>
              </div>
              <div className="hidden shrink-0 gap-2 md:flex">
                <button
                  type="button"
                  onClick={() => goToSection(selectedIndex - 1, activeSectionEntries)}
                  disabled={selectedIndex === 0}
                  className="motion-control inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft size={17} aria-hidden="true" /> Previous
                </button>
                <button
                  type="button"
                  onClick={() => goToSection(selectedIndex + 1, activeSectionEntries)}
                  disabled={selectedIndex === activeSectionEntries.length - 1}
                  className="motion-control inline-flex items-center gap-1 rounded-lg bg-blue-950 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-900 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next <ChevronRight size={17} aria-hidden="true" />
                </button>
              </div>
            </div>}/>
          </div>
          </div>
        ) : (
          <div className="mx-auto mt-6 max-w-lg rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
            <Search className="mx-auto mb-3 text-slate-400" aria-hidden="true" />
            <h2 className="font-bold text-slate-900">No matching sections</h2>
            <p className="mt-1 text-sm text-slate-500">Try another search.</p>
          </div>
        )}
      </main>

      {inboxOpen && <AdminInbox adminName={normalizedUserName} onClose={() => setInboxOpen(false)}/>}

      {feedbackToast && <div className="pointer-events-none fixed inset-x-3 bottom-[calc(5.25rem+env(safe-area-inset-bottom))] z-[110] flex justify-center md:bottom-6" role="status" aria-live="polite">
        <div className={`max-w-md rounded-xl px-4 py-3 text-sm font-bold text-white shadow-2xl ring-1 ring-white/20 ${feedbackToast.type === "success" ? "bg-emerald-700" : "bg-red-700"}`}>
          {feedbackToast.message}
        </div>
      </div>}

    </div>
  );
};

export default ActViewer;
