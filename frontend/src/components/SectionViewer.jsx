import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { flushSync } from "react-dom";
import {
  ChevronLeft,
  ChevronRight,
  Bold,
  FilePenLine,
  FileText,
  Lightbulb,
  Link2,
  ListChecks,
  LoaderCircle,
  MessageSquareText,
  Italic,
  Minus,
  Pencil,
  Plus,
  Save,
  Scale,
  Strikethrough,
  StickyNote,
  Underline,
  Undo2,
  X,
} from "lucide-react";
import DatePicker from "./DatePicker";
import { getRememberedUser } from "../userSession";

const apiBaseUrl = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const adminFetch = (path, options = {}) => {
  const url = /^https?:\/\//i.test(path) ? path : `${apiBaseUrl}${path}`;
  return fetch(url, {
    credentials: "include",
    ...options,
    headers: {
      "X-Admin-Name": getRememberedUser().trim().toLowerCase(),
      ...(options.headers || {}),
    },
  });
};
const READER_CACHE_KEY = "companies-act:reader-cache:v1";
const READER_CACHE_LIMIT = 18;
const readerCache = new Map();
const readerPrefetches = new Map();
let readerCacheLoaded = false;

const loadReaderCache = () => {
  if (readerCacheLoaded || typeof window === "undefined") return;
  readerCacheLoaded = true;
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(READER_CACHE_KEY) || "[]");
    stored.forEach(([key, entry]) => readerCache.set(key, entry));
  } catch {
    window.sessionStorage.removeItem(READER_CACHE_KEY);
  }
};

const readReaderCache = (key) => {
  loadReaderCache();
  const entry = readerCache.get(key);
  if (!entry) return null;
  // Refresh recency whenever a visited page is used.
  readerCache.delete(key);
  readerCache.set(key, entry);
  return entry;
};

const writeReaderCache = (key, raw, data) => {
  loadReaderCache();
  readerCache.delete(key);
  readerCache.set(key, { raw, data, savedAt: Date.now() });
  while (readerCache.size > READER_CACHE_LIMIT) readerCache.delete(readerCache.keys().next().value);
  try {
    window.sessionStorage.setItem(READER_CACHE_KEY, JSON.stringify([...readerCache.entries()]));
  } catch {
    // Keep the in-memory cache if storage quota or privacy settings reject it.
  }
};

const removeReaderCache = (key) => {
  loadReaderCache();
  readerCache.delete(key);
  try {
    window.sessionStorage.setItem(READER_CACHE_KEY, JSON.stringify([...readerCache.entries()]));
  } catch {
    // The next successful write will persist the current in-memory state.
  }
};

export const prefetchSectionTimeline = (sectionNumber, asOfDate) => {
  if (!sectionNumber || !asOfDate) return Promise.resolve(null);
  const normalized = String(sectionNumber).toUpperCase();
  const cacheKey = `section:${normalized}:${asOfDate}`;
  const cached = readReaderCache(cacheKey);
  if (cached) return Promise.resolve(cached.data);
  if (readerPrefetches.has(cacheKey)) return readerPrefetches.get(cacheKey);
  const url = `${apiBaseUrl}/api/sections/${encodeURIComponent(sectionNumber)}/related?as_of=${encodeURIComponent(asOfDate)}`;
  const request = fetch(url, { cache: "no-store", headers: { Accept: "application/json" } })
    .then(async (response) => {
      if (!response.ok) throw new Error(`Timeline API returned ${response.status}`);
      const raw = await response.text();
      const data = JSON.parse(raw);
      writeReaderCache(cacheKey, raw, data);
      return data;
    })
    .catch(() => null)
    .finally(() => readerPrefetches.delete(cacheKey));
  readerPrefetches.set(cacheKey, request);
  return request;
};

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
  const className = `inline-flex min-h-7 items-center rounded-md border px-2 py-1 text-[11px] font-bold uppercase ${colors} ${
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

const PdfDocumentViewer = ({ source }) => {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const renderTaskRef = useRef(null);
  const [pdfDocument, setPdfDocument] = useState(null);
  const [pageNumber, setPageNumber] = useState(Number(source.page) || 1);
  const [pageCount, setPageCount] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [containerWidth, setContainerWidth] = useState(0);
  const [loading, setLoading] = useState(true);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return undefined;

    const updateWidth = () => setContainerWidth(node.clientWidth);
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(node);
    return () => observer.disconnect();
  }, [loading]);

  useEffect(() => {
    let cancelled = false;
    let loadingTask;
    const pdfUrl = source.url.split("#")[0];
    const baseUrl = import.meta.env.BASE_URL.replace(/\/$/, "");

    setLoading(true);
    setError("");
    setPdfDocument(null);
    setPageCount(0);
    setPageNumber(Number(source.page) || 1);
    setZoom(1);

    const loadPdf = async () => {
      try {
        const [{ getDocument }, { WorkerMessageHandler }] = await Promise.all([
          import("../vendor/pdfjs/pdf.mjs"),
          import("../vendor/pdfjs/pdf.worker.min.mjs"),
        ]);
        if (cancelled) return;

        // Run PDF.js through its built-in main-thread worker handler. This avoids
        // module-worker and .mjs MIME restrictions in older mobile browsers and
        // in static hosting environments while retaining PDF.js rendering.
        globalThis.pdfjsWorker = {
          ...globalThis.pdfjsWorker,
          WorkerMessageHandler,
        };
        loadingTask = getDocument({
          url: pdfUrl,
          standardFontDataUrl: `${baseUrl}/pdfjs/standard_fonts/`,
        });
        const document = await loadingTask.promise;
        if (cancelled) {
          document.destroy();
          return;
        }
        const requestedPage = Number(source.page) || 1;
        setPdfDocument(document);
        setPageCount(document.numPages);
        setPageNumber(Math.min(Math.max(requestedPage, 1), document.numPages));
        setLoading(false);
      } catch (loadError) {
        if (cancelled) return;
        console.error("Unable to load amendment PDF:", loadError);
        setError(
          `The amendment PDF could not be displayed${
            loadError?.message ? `: ${loadError.message}` : "."
          }`,
        );
        setLoading(false);
      }
    };

    loadPdf();

    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
      loadingTask?.destroy();
    };
  }, [source.file, source.page, source.url]);

  useEffect(() => {
    if (!pdfDocument || !containerWidth || !canvasRef.current) return undefined;

    let cancelled = false;
    const renderPage = async () => {
      setRendering(true);
      try {
        renderTaskRef.current?.cancel();
        const page = await pdfDocument.getPage(pageNumber);
        if (cancelled) return;

        const baseViewport = page.getViewport({ scale: 1 });
        const availableWidth = Math.max(containerWidth - 24, 280);
        const fitScale = availableWidth / baseViewport.width;
        const viewport = page.getViewport({ scale: fitScale * zoom });
        const outputScale = Math.min(window.devicePixelRatio || 1, 2);
        const canvas = canvasRef.current;
        const context = canvas.getContext("2d", { alpha: false });

        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;

        const renderTask = page.render({
          canvasContext: context,
          viewport,
          transform:
            outputScale === 1
              ? undefined
              : [outputScale, 0, 0, outputScale, 0, 0],
        });
        renderTaskRef.current = renderTask;
        await renderTask.promise;
      } catch (renderError) {
        if (renderError?.name !== "RenderingCancelledException") {
          console.error("Unable to render amendment PDF page:", renderError);
          setError("This PDF page could not be rendered.");
        }
      } finally {
        if (!cancelled) setRendering(false);
      }
    };

    renderPage();
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [containerWidth, pageNumber, pdfDocument, zoom]);

  const changePage = (nextPage) => {
    setPageNumber(Math.min(Math.max(nextPage, 1), pageCount));
    containerRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  if (loading) {
    return (
      <div className="grid min-h-0 flex-1 place-items-center bg-slate-200">
        <div className="flex items-center gap-2 rounded-lg bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow">
          <LoaderCircle className="animate-spin text-blue-700" size={20} />
          Loading amendment PDF…
        </div>
      </div>
    );
  }

  if (error && !pdfDocument) {
    return (
      <div className="grid min-h-0 flex-1 place-items-center bg-slate-100 p-5 text-center">
        <div>
          <p className="font-bold text-slate-900">{error}</p>
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex min-h-11 items-center rounded-lg bg-blue-950 px-4 text-sm font-semibold text-white"
          >
            Open PDF separately
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-200">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-300 bg-white px-2 py-2 sm:px-3">
        <button
          type="button"
          onClick={() => changePage(pageNumber - 1)}
          disabled={pageNumber <= 1}
          className="grid size-10 shrink-0 place-items-center rounded-lg border border-slate-300 text-slate-700 disabled:opacity-35"
          aria-label="Previous PDF page"
        >
          <ChevronLeft size={20} />
        </button>

        <div className="min-w-0 text-center">
          <div className="text-sm font-bold text-slate-900">
            Page {pageNumber} of {pageCount}
          </div>
          {rendering && <div className="text-xs text-slate-500">Rendering…</div>}
        </div>

        <button
          type="button"
          onClick={() => changePage(pageNumber + 1)}
          disabled={pageNumber >= pageCount}
          className="grid size-10 shrink-0 place-items-center rounded-lg border border-slate-300 text-slate-700 disabled:opacity-35"
          aria-label="Next PDF page"
        >
          <ChevronRight size={20} />
        </button>

        <div className="ml-1 flex shrink-0 items-center rounded-lg border border-slate-300 bg-slate-50">
          <button
            type="button"
            onClick={() => setZoom((value) => Math.max(0.75, value - 0.25))}
            disabled={zoom <= 0.75}
            className="grid size-10 place-items-center text-slate-700 disabled:opacity-35"
            aria-label="Zoom out"
          >
            <Minus size={18} />
          </button>
          <span className="min-w-11 text-center text-xs font-bold text-slate-600">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={() => setZoom((value) => Math.min(2, value + 0.25))}
            disabled={zoom >= 2}
            className="grid size-10 place-items-center text-slate-700 disabled:opacity-35"
            aria-label="Zoom in"
          >
            <Plus size={18} />
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="min-h-0 flex-1 touch-pan-y overflow-auto overscroll-contain p-3 [-webkit-overflow-scrolling:touch]"
      >
        {error && (
          <p className="sticky left-0 top-0 z-10 mb-2 rounded bg-red-100 p-2 text-center text-xs font-semibold text-red-800">
            {error}
          </p>
        )}
        <canvas
          ref={canvasRef}
          className="mx-auto block max-w-none bg-white shadow-lg"
          aria-label={`${source.label}, page ${pageNumber}`}
        />
      </div>
    </div>
  );
};

const ContinuousPdfPage = ({ pdfDocument, pageNumber, containerWidth, zoom }) => {
  const wrapperRef = useRef(null);
  const canvasRef = useRef(null);
  const renderTaskRef = useRef(null);
  const [visible, setVisible] = useState(pageNumber <= 2);
  const [aspectRatio, setAspectRatio] = useState(1.414);

  useEffect(() => {
    const node = wrapperRef.current;
    if (!node || visible) return undefined;
    const observer = new IntersectionObserver(
      ([entry]) => entry.isIntersecting && setVisible(true),
      { rootMargin: "900px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible || !containerWidth || !canvasRef.current) return undefined;
    let cancelled = false;

    const render = async () => {
      const page = await pdfDocument.getPage(pageNumber);
      if (cancelled) return;
      const baseViewport = page.getViewport({ scale: 1 });
      setAspectRatio(baseViewport.height / baseViewport.width);
      const availableWidth = Math.max(containerWidth - 24, 280);
      const viewport = page.getViewport({ scale: (availableWidth / baseViewport.width) * zoom });
      const outputScale = Math.min(window.devicePixelRatio || 1, 2);
      const canvas = canvasRef.current;
      const context = canvas.getContext("2d", { alpha: false });
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      renderTaskRef.current = page.render({
        canvasContext: context,
        viewport,
        transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      });
      await renderTaskRef.current.promise;
    };

    render().catch((error) => {
      if (error?.name !== "RenderingCancelledException") {
        console.error(`Unable to render PDF page ${pageNumber}:`, error);
      }
    });
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [containerWidth, pageNumber, pdfDocument, visible, zoom]);

  const placeholderWidth = Math.max(containerWidth - 24, 280) * zoom;
  return (
    <div
      ref={wrapperRef}
      className="mx-auto bg-white shadow-lg"
      style={{ width: placeholderWidth, minHeight: placeholderWidth * aspectRatio }}
    >
      <canvas ref={canvasRef} className="block" aria-label={`PDF page ${pageNumber}`} />
    </div>
  );
};

const ContinuousPdfViewer = ({ source }) => {
  const containerRef = useRef(null);
  const [pdfDocument, setPdfDocument] = useState(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState("");

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return undefined;
    const updateWidth = () => setContainerWidth(node.clientWidth);
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let loadingTask;
    const baseUrl = import.meta.env.BASE_URL.replace(/\/$/, "");

    Promise.all([
      import("../vendor/pdfjs/pdf.mjs"),
      import("../vendor/pdfjs/pdf.worker.min.mjs"),
    ])
      .then(([{ getDocument }, { WorkerMessageHandler }]) => {
        globalThis.pdfjsWorker = { ...globalThis.pdfjsWorker, WorkerMessageHandler };
        loadingTask = getDocument({
          url: source.url,
          standardFontDataUrl: `${baseUrl}/pdfjs/standard_fonts/`,
        });
        return loadingTask.promise;
      })
      .then((document) => {
        if (cancelled) return document.destroy();
        setPdfDocument(document);
        return undefined;
      })
      .catch((loadError) => {
        if (!cancelled) setError(loadError?.message || "The PDF could not be displayed.");
      });

    return () => {
      cancelled = true;
      loadingTask?.destroy();
    };
  }, [source.url]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-200">
      <div className="flex shrink-0 items-center justify-end border-b border-slate-300 bg-white p-2">
        <div className="flex items-center rounded-lg border border-slate-300 bg-slate-50">
          <button type="button" onClick={() => setZoom((value) => Math.max(0.75, value - 0.25))} disabled={zoom <= 0.75} className="grid size-10 place-items-center disabled:opacity-35" aria-label="Zoom out">
            <Minus size={18} />
          </button>
          <span className="min-w-12 text-center text-xs font-bold text-slate-600">{Math.round(zoom * 100)}%</span>
          <button type="button" onClick={() => setZoom((value) => Math.min(2, value + 0.25))} disabled={zoom >= 2} className="grid size-10 place-items-center disabled:opacity-35" aria-label="Zoom in">
            <Plus size={18} />
          </button>
        </div>
      </div>
      <div ref={containerRef} className="min-h-0 flex-1 overflow-auto p-3">
        {!pdfDocument && !error && (
          <div className="grid min-h-full place-items-center"><LoaderCircle className="animate-spin text-blue-800" /></div>
        )}
        {error && <p className="rounded-lg bg-red-50 p-4 text-center text-sm font-semibold text-red-800">{error}</p>}
        {pdfDocument && (
          <div className="space-y-4">
            {Array.from({ length: pdfDocument.numPages }, (_, index) => (
              <ContinuousPdfPage key={index + 1} pdfDocument={pdfDocument} pageNumber={index + 1} containerWidth={containerWidth} zoom={zoom} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
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
      className="motion-modal-backdrop fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-2 backdrop-blur-sm sm:p-3"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Amendment PDF viewer"
        className={`motion-modal-panel flex overflow-hidden rounded-xl bg-white shadow-2xl transition-all ${
          expanded
            ? "h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)]"
            : "h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] sm:h-[min(70vh,600px)] sm:w-[min(92vw,760px)]"
        }`}
      >
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex flex-wrap items-center gap-2 border-b bg-slate-50 px-3 py-2">
            <div className="w-full min-w-0 flex-1 sm:w-auto">
              <h4 className="truncate text-sm font-bold text-slate-900">{activeSource.label}</h4>
              <p className="text-xs text-slate-500">
                {activeSource.page ? `Opening PDF page ${activeSource.page}` : "Source amendment document"}
              </p>
            </div>

            {sources.length > 1 && (
              <select
                value={activeIndex}
                onChange={(event) => setActiveIndex(Number(event.target.value))}
                className="min-w-0 flex-1 rounded border border-slate-300 bg-white px-2 py-1.5 text-xs sm:max-w-56"
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

          <PdfDocumentViewer key={activeSource.url} source={activeSource} />
        </div>
      </section>
    </div>
  );
};

const readableEvidence = (value, labels = []) => {
  if (value === null || value === undefined || value === "") return [];
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return [{ label: labels.at(-1), text: String(value) }];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => readableEvidence(item, labels));
  }
  if (typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) =>
      readableEvidence(item, [...labels, key.replaceAll("_", " ")]),
    );
  }
  return [];
};

const cleanCorpusText = (value) => {
  let text = String(value || "").normalize("NFKC");

  // Gazette PDFs frequently contain Hindi headings encoded through old
  // non-Unicode fonts. PDF extraction turns those headings into Latin-looking
  // noise such as "Hkkjr dk jkti=k". Remove only those known header fragments.
  text = text
    .replace(
      /(?:¹|Â¹)?Hkkx\s+II[\s\S]{0,180}?(?=\b(?:THE GAZETTE|MINISTRY|NOTIFICATION|FORM|Declaration|section)\b)/gi,
      " ",
    )
    .replace(
      /(?:^|\n)[^\n]{0,180}(?:fnYyh|lkseokj|flrEcj|Hkkæ|vçSy|vxLr|cqèk)[^\n]{0,180}?(?=NEW DELHI)/gim,
      "\n",
    )
    .replace(/[\u0900-\u0D7F]+/g, " ")
    .replace(
      /\b(?:Hkkjr|Hkkx|jkti=k|vlk\/kj\.k|fnYyh|lkseokj|flrEcj|Hkkæ|vçSy|vxLr|cqèk|izkf\/kdj|vuqHkkx)\b/gi,
      " ",
    )
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([,.;:])/g, "$1")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  const gazetteBoilerplate = [
    /\bREGD\.?\s*NO\.?\s*D\.?\s*L\.?[-–—\s]*33004\/99\b/i,
    /^EXTRAORDINARY$/i,
    /^Section\s+3\s*[-–—]\s*Sub-section\s*\([ivx]+\)$/i,
    /^PUBLISHED BY AUTHORITY$/i,
    /^No\.\s*\d+\]\s*NEW DELHI,.*\/.*\d{4}$/i,
    /^\d+\s+GI\/\d{4}\s*\(\d+\)$/i,
  ];
  const legacyHindiLine = /(?:jftLVah|izkf\/dkj|izdkf['’]?kr|ubZ|c`gLifrokj|fnlEcj|ikS["'k]|la[ö-])/i;
  const indianScript = /[\u0900-\u0D7F]/;

  text = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => {
      if (!line) return true;
      if (gazetteBoilerplate.some((pattern) => pattern.test(line))) return false;
      if (legacyHindiLine.test(line)) return false;
      if (indianScript.test(line)) return false;
      return true;
    })
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return text;
};

const DOCUMENT_FORMATS = [["bold", Bold], ["italic", Italic], ["underline", Underline], ["strike", Strikethrough]];
const applyDocumentFormat = (value, start, end, format) => {
  if (start === end) return value;
  const open = `[[${format}]]`; const close = `[[/${format}]]`;
  return `${value.slice(0, start)}${open}${value.slice(start, end)}${close}${value.slice(end)}`;
};
const DOCUMENT_HIGHLIGHT_COLORS = [["Yellow", "#fff59d"], ["Green", "#b9f6ca"], ["Blue", "#bbdefb"], ["Red", "#ffcdd2"], ["Pink", "#f8bbd0"], ["Purple", "#d1c4e9"], ["Orange", "#ffcc80"], ["Gray", "#eeeeee"]];
const RichTextToolbar = ({ onFormat, onColor }) => <div className="sticky top-0 z-20 flex flex-nowrap items-center gap-1 overflow-x-auto border-b border-blue-200 bg-blue-50 p-2 shadow-sm">
  {DOCUMENT_FORMATS.map(([format, Icon]) => <button key={format} type="button" title={format} aria-label={format} onMouseDown={(event) => { event.preventDefault(); onFormat(format); }} className="grid size-8 place-items-center rounded border border-blue-200 bg-white text-slate-700 hover:bg-blue-100"><Icon size={15}/></button>)}
  <span className="mx-1 h-6 w-px bg-blue-200" />
  {DOCUMENT_HIGHLIGHT_COLORS.map(([name, color]) => <button key={color} type="button" title={name} aria-label={name} onMouseDown={(event) => { event.preventDefault(); onColor(color); }} className="size-6 shrink-0 rounded border border-slate-400 shadow-sm hover:ring-2 hover:ring-blue-400" style={{ backgroundColor: color }} />)}
</div>;
const RichTextEditor = ({ value, onChange, className = "" }) => {
  const ref = useRef(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  const selection = useRef({ start: 0, end: 0 });
  const format = (name) => { const element = ref.current; if (!element) return; const { start, end } = selection.current; if (start === end) return; const latest = valueRef.current; const nextValue = applyDocumentFormat(latest, start, end, name); element.value = nextValue; valueRef.current = nextValue; const nextStart = start + name.length + 4; const nextEnd = end + name.length + 4; selection.current = { start: nextStart, end: nextEnd }; element.focus(); element.setSelectionRange(nextStart, nextEnd); flushSync(() => onChange(nextValue)); };
  const color = (hex) => format(`highlight-${hex.replace("#", "")}`);
  const rememberSelection = () => { if (ref.current) selection.current = { start: ref.current.selectionStart, end: ref.current.selectionEnd }; };
  return <div className={`overflow-hidden rounded-lg border border-blue-300 ring-2 ring-blue-100 ${className}`}><RichTextToolbar onFormat={format} onColor={color}/><textarea ref={ref} value={value} onChange={(event) => onChange(event.target.value)} onSelect={rememberSelection} onMouseUp={rememberSelection} onKeyUp={rememberSelection} className="min-h-0 h-full w-full resize-y border-0 p-4 font-sans text-sm leading-7 outline-none" spellCheck="true"/></div>;
};
const FormattedDocumentText = ({ text }) => {
  const render = (value, prefix = "f") => { const match = String(value || "").match(/^([\s\S]*?)\[\[(bold|italic|underline|strike|highlight-([a-z0-9]+))\]\]([\s\S]*?)\[\[\/\2\]\]([\s\S]*)$/); if (!match) return <>{value}</>; const styles = { bold: "font-bold", italic: "italic", underline: "underline", strike: "line-through" }; return <>{match[1]}<span key={prefix} className={styles[match[2]] || ""} style={match[4] ? { backgroundColor: `#${match[4]}` } : undefined}>{render(match[5], `${prefix}-in`)}</span>{render(match[6], `${prefix}-out`)}</>; };
  return <>{render(String(text || ""))}</>;
};
const displayInlineText = (value, glossary, provisionId, adminMode) => String(value || "").includes("[[")
  ? <FormattedDocumentText text={value}/>
  : <GlossaryText glossary={glossary} currentProvisionId={provisionId} adminMode={adminMode}>{value}</GlossaryText>;
const readableInstrumentType = (value) => String(value || "Document").replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
const DOCUMENT_CACHE_KEY = "companies-act:document-cache:v1";
const PDF_CACHE_KEY = "companies-act:pdf-cache:v1";
const textHash = (value) => { let hash = 2166136261; for (const character of String(value || "")) { hash ^= character.charCodeAt(0); hash = Math.imul(hash, 16777619); } return (hash >>> 0).toString(16); };
const readLru = (key) => { try { return JSON.parse(sessionStorage.getItem(key) || "[]"); } catch { return []; } };
const writeLru = (key, entries, limit) => { try { sessionStorage.setItem(key, JSON.stringify(entries.slice(-limit))); } catch { /* storage may be unavailable */ } };

const CorpusDocumentModal = ({ context, onClose, adminMode = false, onChanged }) => {
  const relationships = (context?.relationships || []).filter((relationship, index, items) => {
    const documentId = relationship.document?.id;
    return items.findIndex((candidate) => candidate.document?.id === documentId) === index;
  });
  const targetProvisionId = context?.targetProvisionId;
  const initialDocumentId = context?.initialDocumentId;
  const creating = Boolean(context?.create);
  const [activeIndex, setActiveIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(null);
  const [message, setMessage] = useState("");
  const [documentQuery, setDocumentQuery] = useState("");
  const [documentResults, setDocumentResults] = useState([]);
  const [documentData, setDocumentData] = useState({});
  const [loadingText, setLoadingText] = useState(false);
  const [showAddReference, setShowAddReference] = useState(false);
  const relationship = relationships?.[activeIndex];
  const document = creating ? { id: null, title: `New ${context?.category || "document"}`, instrument_type: context?.category === "Notifications" ? "notification" : "rules" } : relationship?.document;
  const isNotification = context?.category === "Notifications" || /notification/i.test(String(document?.instrument_type || ""));
  const hasPdfSource = Boolean(document?.source_path || document?.source_file || documentData[document?.id]?.source_path || documentData[document?.id]?.source_file);
  const pdfUrl = document?.id
    ? `${apiBaseUrl}/api/documents/${encodeURIComponent(document.id)}/pdf`
    : "";
  const pdfSource = {
    file: document?.id || "document.pdf",
    label: document?.title || "Original document",
    url: pdfUrl,
  };

  useEffect(() => {
    const index = relationships.findIndex((item) => item.document?.id === initialDocumentId);
    setActiveIndex(index >= 0 ? index : 0);
  }, [initialDocumentId, relationships.map((item) => item.document?.id).join(",")]);
  useEffect(() => {
    if (creating) { setEditing(true); setDraft({ title: "", full_text: "", instrument_type: "" }); setLoadingText(false); return undefined; }
    setEditing(false); setDraft(null); setMessage("");
    if (!document?.id) return;
    let cancelled = false;
    setLoadingText(true);
    const load = (id) => fetch(`${apiBaseUrl}/api/documents/${encodeURIComponent(id)}`).then((response) => response.ok ? response.json() : null).then((item) => item?.id ? { ...item, full_text: cleanCorpusText(item.full_text || "") } : null).catch(() => null);
    const cached = readLru(DOCUMENT_CACHE_KEY).find((item) => item.id === document.id);
    if (cached?.full_text) { setDocumentData((current) => ({ ...current, [cached.id]: cached })); if (adminMode) setDraft({ title: cached.title || "", full_text: cached.full_text || "", instrument_type: cached.instrument_type || "rules" }); setLoadingText(false); }
    load(document.id).then((active) => {
      if (cancelled) return;
      if (active) { const entry = { ...active, content_hash: textHash(active.full_text) }; const cachedHash = readLru(DOCUMENT_CACHE_KEY).find((item) => item.id === active.id)?.content_hash; if (cachedHash !== entry.content_hash) setDocumentData((current) => ({ ...current, [active.id]: entry })); if (adminMode) setDraft({ title: active.title || "", full_text: active.full_text || "", instrument_type: active.instrument_type || "rules" }); const entries = readLru(DOCUMENT_CACHE_KEY).filter((item) => item.id !== active.id); writeLru(DOCUMENT_CACHE_KEY, [...entries, entry], 20); }
      setLoadingText(false);
      Promise.all(relationships.filter((item) => item.document?.id !== document.id).map((item) => load(item.document.id))).then((items) => {
        if (cancelled) return;
        setDocumentData((current) => { const next = { ...current }; items.forEach((item) => { if (item) { const entry = { ...item, content_hash: textHash(item.full_text) }; next[item.id] = entry; const entries = readLru(DOCUMENT_CACHE_KEY).filter((cachedItem) => cachedItem.id !== item.id); writeLru(DOCUMENT_CACHE_KEY, [...entries, entry], 20); } }); return next; });
      });
    });
    if (isNotification && pdfUrl) { const pdfs = readLru(PDF_CACHE_KEY).filter((url) => url !== pdfUrl); writeLru(PDF_CACHE_KEY, [...pdfs, pdfUrl], 5); fetch(pdfUrl, { cache: "force-cache" }).catch(() => {}); }
    return () => { cancelled = true; };
  }, [activeIndex, adminMode, document?.id, creating, relationships.map((item) => item.document?.id).join(",")]);

  const activeDocument = documentData[document?.id];
  const documentFamilyKey = (value) => String(value || "").toLowerCase().replace(/\b(amendment|notification|order|rules?|regulations?|\d{4})\b/g, "").replace(/[^a-z0-9]+/g, "");
  const currentFamily = documentFamilyKey(activeDocument?.title || document?.title);
  const earlierDocument = relationships
    .map((item) => documentData[item.document?.id])
    .filter((item) => item && item.id !== document?.id && documentFamilyKey(item.title) === currentFamily && item.full_text)
    .sort((a, b) => String(a.publication_date || a.effective_date || "").localeCompare(String(b.publication_date || b.effective_date || "")))
    .at(-1);

  const saveDocument = async () => {
    const response = await adminFetch(creating ? "/api/admin/documents" : `/api/admin/documents/${encodeURIComponent(document.id)}`, { method: creating ? "POST" : "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(creating ? { ...draft, instrument_type: draft.instrument_type || (context?.category === "Notifications" ? "notification" : "rules"), provision_id: targetProvisionId } : draft) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) return setMessage(payload.detail || "Save failed");
    if (creating) { context?.onCreated?.(); onChanged?.(); onClose(); return; }
    document.title = payload.title; document.instrument_type = payload.instrument_type || document.instrument_type; setDocumentData((current) => ({ ...current, [document.id]: { ...(current[document.id] || {}), ...payload, full_text: cleanCorpusText(draft?.full_text || "") } })); setEditing(false); setMessage("Saved."); onChanged?.();
  };
  const searchDocuments = async () => { const response = await adminFetch(`/api/admin/documents?q=${encodeURIComponent(documentQuery)}`); const payload = await response.json(); setDocumentResults(payload.results || []); };
  const addReference = async (documentId) => { const response = await adminFetch("/api/admin/relationships", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_id: documentId, provision_id: targetProvisionId, relationship_type: "references" }) }); const payload = await response.json().catch(() => ({})); if (!response.ok) return setMessage(payload.detail || "Unable to add reference"); onChanged?.(); onClose(); };
  const removeReference = async (id) => { if (!window.confirm("Remove this PDF reference?")) return; const response = await adminFetch(`/api/admin/relationships/${id}`, { method: "DELETE" }); if (!response.ok) return setMessage("Unable to remove reference"); onChanged?.(); onClose(); };

  useEffect(() => {
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  if (!document) return null;

  return createPortal((
    <div
      className="motion-modal-backdrop fixed inset-0 z-[100] grid place-items-center bg-slate-950/60 p-3 backdrop-blur-sm"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section role="dialog" aria-modal="true" aria-label={document.title} className="motion-modal-panel flex h-[calc(100dvh-1.5rem)] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl sm:h-[85dvh]">
        <header className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b bg-white px-4 py-3">
          <div className="min-w-0">
            <span className="inline-flex rounded bg-blue-100 px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-blue-900">
              {readableInstrumentType(document.instrument_type)}
            </span>
            {editing ? <><input value={draft?.title || ""} onChange={(e) => setDraft({ ...draft, title: e.target.value })} className="mt-2 w-full rounded border border-blue-300 px-2 py-1 text-base font-bold"/><select value={draft?.instrument_type || ""} onChange={(e) => setDraft({ ...draft, instrument_type: e.target.value })} className="mt-2 rounded border border-blue-300 px-2 py-1 text-xs"><option value="">Select type</option>{context?.category === "Rules" ? <><option value="rules">Rules</option><option value="amendment_rules">Amendment rules</option></> : <><option value="notification">Notification</option><option value="circular">Circular</option><option value="removal_of_difficulties_order">Removal of difficulties order</option></>}</select></> : <h4 className="mt-2 text-base font-extrabold leading-snug text-slate-900">{draft?.title || document.title}</h4>}
          </div>
          <button type="button" onClick={onClose} className="grid size-10 shrink-0 place-items-center rounded-lg hover:bg-slate-100" aria-label="Close document details">
            <X size={20} />
          </button>
          {adminMode && (!isNotification || creating || !hasPdfSource) && (editing ? <span className="flex gap-2"><button type="button" onClick={saveDocument} disabled={!draft?.title?.trim()} className="rounded-lg bg-blue-950 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">Save</button><button type="button" onClick={() => creating ? onClose() : setEditing(false)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold text-slate-700">Cancel</button></span> : <button type="button" onClick={() => setEditing(true)} className="rounded-lg bg-amber-500 px-3 py-2 text-xs font-bold text-white">Edit</button>)}
        </header>
        <div className="max-h-[55vh] shrink-0 space-y-4 overflow-y-auto p-4 text-sm text-slate-700">
          {message && <div className="text-xs font-semibold text-blue-800">{message}</div>}

          {(documentData[document?.id]?.source_path || documentData[document?.id]?.source_file) && <a
            href={`${pdfUrl}?download=true`}
            className="inline-flex min-h-10 shrink-0 items-center rounded-lg bg-blue-950 px-4 text-sm font-semibold text-white"
          >
            Download PDF
          </a>}
        </div>
        {editing ? <RichTextEditor value={draft?.full_text || ""} onChange={(full_text) => setDraft({ ...draft, full_text })} className="m-4 min-h-0 flex-1"/> : isNotification && hasPdfSource ? <ContinuousPdfViewer key={pdfUrl} source={pdfSource} /> : (
          <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50 p-4">
            {loadingText ? <p className="text-sm text-slate-500">Loading document text…</p> : earlierDocument ? (
              <CoalescedAmendment currentText={activeDocument?.full_text || ""} earlier={{ text: earlierDocument.full_text, source_note: `${earlierDocument.title || "Earlier document"} (${earlierDocument.publication_date || "previous version"})` }} />
            ) : <div className="whitespace-pre-wrap font-sans text-[15px] leading-7 text-slate-800"><FormattedDocumentText text={activeDocument?.full_text ?? draft?.full_text ?? "No converted text is available for this document."}/></div>}
          </div>
        )}
      </section>
    </div>
  ), globalThis.document.body);
};

const RelatedDocuments = ({ relationships, onOpen, targetProvisionId }) => {
  if (!relationships?.length) return null;

  const uniqueRelationships = relationships.filter((relationship, index, items) => {
    const documentId = relationship.document?.id;
    return items.findIndex((candidate) => candidate.document?.id === documentId) === index;
  });

  const documentTypes = [...new Set(
    uniqueRelationships.map((relationship) => relationship.document.instrument_type).filter(Boolean),
  )];

  return (
    <button
      type="button"
      onClick={() => onOpen({ relationships: uniqueRelationships, targetProvisionId })}
      className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs font-semibold text-blue-800 hover:bg-blue-50 hover:text-blue-950"
    >
      <FileText size={14} className="shrink-0" />
      <span>Related documents</span>
      {documentTypes.length > 0 && (
        <span className="truncate font-normal text-slate-500">— {documentTypes.join(", ")}</span>
      )}
    </button>
  );
};

const CALLOUT_COLORS = [
  { name: "Amber", box: "border-amber-300 bg-amber-50", head: "text-amber-950", dot: "bg-amber-500" },
  { name: "Blue", box: "border-blue-300 bg-blue-50", head: "text-blue-950", dot: "bg-blue-500" },
  { name: "Emerald", box: "border-emerald-300 bg-emerald-50", head: "text-emerald-950", dot: "bg-emerald-500" },
  { name: "Rose", box: "border-rose-300 bg-rose-50", head: "text-rose-950", dot: "bg-rose-500" },
  { name: "Violet", box: "border-violet-300 bg-violet-50", head: "text-violet-950", dot: "bg-violet-500" },
  { name: "Cyan", box: "border-cyan-300 bg-cyan-50", head: "text-cyan-950", dot: "bg-cyan-500" },
  { name: "Orange", box: "border-orange-300 bg-orange-50", head: "text-orange-950", dot: "bg-orange-500" },
  { name: "Lime", box: "border-lime-300 bg-lime-50", head: "text-lime-950", dot: "bg-lime-500" },
  { name: "Pink", box: "border-pink-300 bg-pink-50", head: "text-pink-950", dot: "bg-pink-500" },
  { name: "Slate", box: "border-slate-300 bg-slate-50", head: "text-slate-950", dot: "bg-slate-500" },
];

const CALLOUT_TYPES = {
  amendment: { label: "Amendment", icon: FilePenLine },
  case_law: { label: "Case law", icon: Scale },
  insight: { label: "Insight", icon: Lightbulb },
  action_point: { label: "Action point", icon: ListChecks },
  note: { label: "Note", icon: StickyNote },
  bulb: { label: "Anchored information", icon: Lightbulb },
};

const calloutTypeDetails = (type) => CALLOUT_TYPES[type] || {
  label: String(type || "Callout").replaceAll("_", " "),
  icon: MessageSquareText,
};

const GLOSSARY_EXCLUDED_TERMS = new Set(["act", "company"]);

const escapeRegularExpression = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const navigateToSection = (sectionNumber, onNavigate, provisionId = null) => {
  const normalized = String(sectionNumber).toUpperCase();
  const hash = provisionId ? `#provision-${encodeURIComponent(provisionId)}` : `#section-${normalized}`;
  window.history.pushState({}, "", hash);
  window.dispatchEvent(new CustomEvent("companies-act:navigate-section", { detail: { sectionNumber: normalized, provisionId } }));
  onNavigate?.();
};

const GlossaryTerm = ({ entry, visibleTerm, popupId, onNavigate, adminMode = false }) => {
  const rootRef = useRef(null);
  const closeTimerRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [opensAbove, setOpensAbove] = useState(false);
  const [popupStyle, setPopupStyle] = useState({});
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [draft, setDraft] = useState(() => ({
    original_term: entry.term,
    term: entry.term,
    title: entry.title || entry.term,
    content: entry.content || entry.definition || "",
    source_provision_id: entry.provision_id || "",
    source_label: entry.source || "",
    enabled: true,
  }));
  const positionPopup = () => {
    const rect = rootRef.current?.getBoundingClientRect();
    if (!rect) return;
    const viewport = window.visualViewport;
    const viewportLeft = viewport?.offsetLeft || 0;
    const viewportTop = viewport?.offsetTop || 0;
    const viewportWidth = viewport?.width || window.innerWidth;
    const viewportHeight = viewport?.height || window.innerHeight;
    const viewportRight = viewportLeft + viewportWidth;
    const viewportBottom = viewportTop + viewportHeight;
    const margin = 12;
    const gap = 7;
    const width = Math.min(352, viewportWidth - margin * 2);
    const left = Math.min(Math.max(rect.left, viewportLeft + margin), viewportRight - width - margin);
    const spaceAbove = rect.top - viewportTop - margin - gap;
    const spaceBelow = viewportBottom - rect.bottom - margin - gap;
    const above = spaceBelow < 256 && spaceAbove > spaceBelow;
    const availableHeight = Math.max(88, Math.min(256, above ? spaceAbove : spaceBelow));
    setOpensAbove(above);
    setPopupStyle({
      left: `${left}px`,
      width: `${width}px`,
      maxHeight: `${availableHeight}px`,
      top: above ? "auto" : `${rect.bottom + gap}px`,
      bottom: above ? `${window.innerHeight - rect.top + gap}px` : "auto",
    });
  };
  const cancelClose = () => {
    if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = null;
  };
  const showPopup = () => {
    cancelClose();
    positionPopup();
    setOpen(true);
  };
  const scheduleClose = () => {
    cancelClose();
    closeTimerRef.current = window.setTimeout(() => setOpen(false), 140);
  };

  useEffect(() => {
    if (!open) return undefined;
    const reposition = () => positionPopup();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    window.visualViewport?.addEventListener("resize", reposition);
    window.visualViewport?.addEventListener("scroll", reposition);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      window.visualViewport?.removeEventListener("resize", reposition);
      window.visualViewport?.removeEventListener("scroll", reposition);
    };
  }, [open]);

  useEffect(() => () => cancelClose(), []);

  const saveReference = async (event) => {
    event.preventDefault();
    setSaving(true); setMessage("");
    try {
      const response = await adminFetch("/api/admin/context-references", {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...draft, source_provision_id: draft.source_provision_id || null }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `Save failed (${response.status})`);
      setMessage("Saved.");
      setEditing(false);
      window.dispatchEvent(new CustomEvent("companies-act:glossary-changed"));
    } catch (error) {
      setMessage(error.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <span ref={rootRef} onMouseEnter={showPopup} onMouseLeave={scheduleClose} onFocusCapture={showPopup} onBlurCapture={scheduleClose} className={`glossary-term relative inline ${opensAbove ? "opens-above" : ""}`}>
      <button type="button" aria-describedby={open ? popupId : undefined} onClick={showPopup} className="glossary-trigger inline border-0 bg-transparent p-0 font-inherit text-inherit">
        {visibleTerm}
      </button>
      {open && createPortal(<div id={popupId} role="tooltip" data-glossary-popover onMouseEnter={cancelClose} onMouseLeave={scheduleClose} onPointerDown={cancelClose} onFocusCapture={cancelClose} style={popupStyle} className="glossary-popover">
        {editing ? <form onSubmit={saveReference} className="grid gap-2">
          <label className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Referenced words<input value={draft.term} onChange={(event) => setDraft({ ...draft, term: event.target.value })} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-xs font-normal normal-case tracking-normal" required/></label>
          <label className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Popup title<input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-xs font-normal normal-case tracking-normal" required/></label>
          <label className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Explanation<textarea value={draft.content} onChange={(event) => setDraft({ ...draft, content: event.target.value })} className="mt-1 min-h-24 w-full resize-y rounded border border-slate-300 px-2 py-1.5 text-xs font-normal leading-5 normal-case tracking-normal" required/></label>
          <label className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Destination provision ID<input value={draft.source_provision_id} onChange={(event) => setDraft({ ...draft, source_provision_id: event.target.value })} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-xs font-normal normal-case tracking-normal" placeholder="provision:act:companies-act-2013:section:..."/></label>
          <label className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Link label<input value={draft.source_label} onChange={(event) => setDraft({ ...draft, source_label: event.target.value })} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-xs font-normal normal-case tracking-normal" placeholder="Section 135"/></label>
          {message && <span className="text-xs font-semibold text-red-700">{message}</span>}
          <span className="flex gap-2"><button disabled={saving} className="rounded bg-blue-950 px-3 py-1.5 text-xs font-bold text-white disabled:opacity-50">{saving ? "Saving…" : "Save popup"}</button><button type="button" onClick={() => setEditing(false)} className="rounded border border-slate-300 px-3 py-1.5 text-xs font-bold text-slate-700">Cancel</button></span>
        </form> : <>
          <strong className="block font-extrabold text-slate-950">{entry.title || entry.term}</strong>
          <span className="mt-1 block text-xs leading-5 text-slate-700">{entry.content || entry.definition}</span>
          {entry.related_provision_id && entry.related_section_number && <a href={`#provision-${encodeURIComponent(entry.related_provision_id)}`} onClick={(event) => { event.preventDefault(); navigateToSection(entry.related_section_number, onNavigate, entry.related_provision_id); }} className="mt-2 block text-xs font-bold text-blue-800 underline decoration-blue-300 underline-offset-2 hover:text-blue-950">
            Relevant provision: {entry.related_source || `Section ${entry.related_section_number}`}
          </a>}
          {entry.provision_id && entry.section_number && <a href={`#provision-${encodeURIComponent(entry.provision_id)}`} onClick={(event) => { event.preventDefault(); navigateToSection(entry.section_number, onNavigate, entry.provision_id); }} className="mt-2 inline-block text-xs font-bold text-blue-800 underline decoration-blue-300 underline-offset-2 hover:text-blue-950">
            {entry.reference_type === "definition" ? "Defined in" : "Referenced at"} {entry.source || `Section ${entry.section_number}${entry.label || ""}`}
          </a>}
          {adminMode && <button type="button" onClick={() => { cancelClose(); setEditing(true); setMessage(""); }} className="ml-3 mt-2 inline-block text-xs font-bold text-amber-800 underline decoration-amber-300 underline-offset-2">Edit popup</button>}
        </>}
      </div>, document.body)}
    </span>
  );
};

const GlossaryText = ({ children, glossary = [], onNavigate, currentProvisionId = null, adminMode = false }) => {
  const text = String(children || "");
  const entries = useMemo(
    () => glossary.filter((entry) => entry.term?.length >= 3 && entry.provision_id !== currentProvisionId && !GLOSSARY_EXCLUDED_TERMS.has(entry.term.toLowerCase())),
    [glossary, currentProvisionId],
  );
  const pattern = useMemo(() => {
    if (!entries.length) return null;
    return new RegExp(`(^|[^A-Za-z0-9])(${entries.map((entry) => escapeRegularExpression(entry.term)).join("|")})(?=$|[^A-Za-z0-9])`, "gi");
  }, [entries]);
  if (!pattern || !text) return <>{text}</>;

  const byTerm = new Map(entries.map((entry) => [entry.term.toLowerCase(), entry]));
  const parts = []; let cursor = 0; let match;
  while ((match = pattern.exec(text))) {
    const termStart = match.index + match[1].length;
    if (termStart > cursor) parts.push(text.slice(cursor, termStart));
    const visibleTerm = match[2];
    const entry = byTerm.get(visibleTerm.toLowerCase());
    const popupId = `glossary-${entry.provision_id}-${termStart}`;
    parts.push(<GlossaryTerm key={`${entry.id || entry.provision_id}-${termStart}`} entry={entry} visibleTerm={visibleTerm} popupId={popupId} onNavigate={onNavigate} adminMode={adminMode}/>);
    cursor = termStart + visibleTerm.length;
    if (pattern.lastIndex === match.index) pattern.lastIndex += 1;
  }
  parts.push(text.slice(cursor));
  return <>{parts}</>;
};

const LinkedLegalText = ({ children, onNavigate, glossary = [], currentProvisionId = null, adminMode = false }) => {
  const text = String(children || "");
  const pattern = /\b(section\s+(\d+[A-Za-z]?))(?![\w])/gi;
  const parts = []; let cursor = 0; let match;
  while ((match = pattern.exec(text))) {
    parts.push(<GlossaryText key={`text-${cursor}`} glossary={glossary} onNavigate={onNavigate} currentProvisionId={currentProvisionId} adminMode={adminMode}>{text.slice(cursor, match.index)}</GlossaryText>);
    const sectionNumber = match[2].toUpperCase();
    parts.push(<a key={`${match.index}-${sectionNumber}`} href={`#section-${sectionNumber}`} onClick={(event) => { event.preventDefault(); navigateToSection(sectionNumber, onNavigate); }} className="font-bold text-blue-800 underline decoration-blue-300 underline-offset-2 hover:text-blue-950">{match[1]}</a>);
    cursor = match.index + match[0].length;
  }
  parts.push(<GlossaryText key={`text-${cursor}`} glossary={glossary} onNavigate={onNavigate} currentProvisionId={currentProvisionId} adminMode={adminMode}>{text.slice(cursor)}</GlossaryText>);
  return <>{parts}</>;
};

const emptyCallout = (sortOrder = 0) => ({ callout_type: "insight", title: "", content: "", source_provision_id: null, source_document_id: null, source_locator: {}, color_index: 0, sort_order: sortOrder, effective_from: "", effective_to: "" });

const provisionSourceLabel = (source) => {
  if (!source) return "";
  if (source.source_kind === "rule_paragraph" || source.source_document_id || source.document_id) {
    const title = source.source_document_title || source.document_title || source.source_title || "Rules document";
    const label = source.source_locator?.label;
    return [title, label ? `paragraph ${label}` : "linked paragraph"].join(" — ");
  }
  const section = source.source_section_number ?? source.section_number;
  const label = source.source_label ?? source.label;
  const title = source.source_title ?? source.title;
  const location = [section ? `Section ${section}` : "", label && label !== section ? label : ""].filter(Boolean).join(" ");
  return [location, title].filter(Boolean).join(" — ");
};

const CalloutEditor = ({ initial, provisionId, onDone, lockedType, asOfDate }) => {
  const [draft, setDraft] = useState(initial || { ...emptyCallout(), callout_type: lockedType || "insight", title: lockedType === "bulb" ? "Additional information" : "" });
  const [sourceMode, setSourceMode] = useState(initial?.source_provision_id || initial?.source_document_id ? "linked" : "manual");
  const [sourceQuery, setSourceQuery] = useState("");
  const [sourceResults, setSourceResults] = useState([]);
  const [sourceBusy, setSourceBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selectedSourceLabel = draft.source_provision_id || draft.source_document_id ? provisionSourceLabel(draft) : "";
  const searchSources = async () => {
    if (!sourceQuery.trim()) return;
    setSourceBusy(true); setError("");
    const params = new URLSearchParams({ q: sourceQuery.trim(), limit: "30" });
    if (asOfDate) params.set("as_of", asOfDate);
    const response = await adminFetch(`/api/admin/callout-sources?${params}`);
    const result = await response.json().catch(() => ({}));
    setSourceBusy(false);
    if (!response.ok) { setError(result.detail || "Unable to search source provisions"); return; }
    setSourceResults((result.results || []).filter((item) => item.source_kind !== "provision" || item.id !== provisionId));
  };
  const chooseSource = (source) => {
    const isDocument = source.source_kind === "rule_paragraph";
    setDraft({ ...draft,
      source_kind: source.source_kind,
      source_provision_id: isDocument ? null : source.id,
      source_document_id: isDocument ? source.document_id : null,
      source_locator: isDocument ? source.source_locator || {} : {},
      source_document_title: isDocument ? source.document_title : null,
      source_section_number: isDocument ? null : source.section_number,
      source_label: isDocument ? null : source.label,
      source_title: isDocument ? source.document_title : source.title,
      source_content: source.current_text,
      content: draft.content || String(source.current_text || "").slice(0, 20000),
    });
    setSourceQuery(""); setSourceResults([]);
  };
  const save = async () => {
    setBusy(true); setError("");
    const path = initial?.id ? `/api/admin/callouts/${initial.id}` : "/api/admin/callouts";
    const payload = {
      callout_type: draft.callout_type,
      title: draft.title,
      content: draft.content || "",
      source_provision_id: sourceMode === "linked" ? draft.source_provision_id || null : null,
      source_document_id: sourceMode === "linked" ? draft.source_document_id || null : null,
      source_locator: sourceMode === "linked" ? draft.source_locator || {} : {},
      color_index: Number(draft.color_index) || 0,
      sort_order: Number(draft.sort_order) || 0,
      effective_from: draft.effective_from || null,
      effective_to: draft.effective_to || null,
      anchor: draft.anchor || {},
      provision_id: provisionId,
    };
    if (initial?.id) delete payload.provision_id;
    const response = await adminFetch(path, { method: initial?.id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) { setError(result.detail || "Unable to save callout"); setBusy(false); return; }
    onDone(true);
  };
  return <div className="mt-3 space-y-3 rounded-xl border border-blue-200 bg-white p-3 shadow-sm">
    <div className="grid gap-3 sm:grid-cols-[10rem_1fr_7rem]"><label className="text-xs font-bold text-slate-600">Type<select disabled={Boolean(lockedType)} value={draft.callout_type} onChange={(e) => setDraft({ ...draft, callout_type: e.target.value })} className="mt-1 w-full rounded border p-2 font-normal disabled:bg-slate-100"><option value="amendment">Amendment</option><option value="case_law">Case law</option><option value="insight">Insight</option><option value="action_point">Action point</option><option value="note">Note</option><option value="bulb">Bulb note</option></select></label><label className="text-xs font-bold text-slate-600">Heading<input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} className="mt-1 w-full rounded border p-2 font-normal"/></label><label className="text-xs font-bold text-slate-600">Order<input type="number" min="0" value={draft.sort_order} onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })} className="mt-1 w-full rounded border p-2 font-normal"/></label></div>
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <span className="text-xs font-bold text-slate-700">Callout content</span>
      <div className="mt-2 flex gap-2"><button type="button" onClick={() => { setDraft({ ...draft, content: draft.source_content || draft.content }); setSourceMode("manual"); }} className={`rounded-md px-3 py-1.5 text-xs font-bold ${sourceMode === "manual" ? "bg-blue-950 text-white" : "border bg-white text-slate-700"}`}>Write here</button><button type="button" onClick={() => setSourceMode("linked")} className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-bold ${sourceMode === "linked" ? "bg-blue-950 text-white" : "border bg-white text-slate-700"}`}><Link2 size={13}/>Link existing content</button></div>
      {sourceMode === "manual" ? <textarea aria-label="Callout content" value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} className="mt-3 min-h-28 w-full rounded border bg-white p-2 text-sm font-normal leading-6"/> : <div className="mt-3 space-y-2">
        {(draft.source_provision_id || draft.source_document_id) && <div className="flex items-start justify-between gap-3 rounded-md border border-emerald-200 bg-emerald-50 p-2.5"><div><span className="block text-[10px] font-bold uppercase tracking-wide text-emerald-700">Linked source</span><strong className="text-sm text-emerald-950">{selectedSourceLabel || draft.source_provision_id || draft.source_document_id}</strong><p className="mt-1 line-clamp-3 text-xs leading-5 text-emerald-900">{draft.source_content || draft.content}</p></div><button type="button" onClick={() => setDraft({ ...draft, source_kind: null, source_provision_id: null, source_document_id: null, source_locator: {}, source_document_title: null, source_section_number: null, source_label: null, source_title: null, source_content: null })} className="shrink-0 text-xs font-bold text-red-700">Remove</button></div>}
        <form onSubmit={(event) => { event.preventDefault(); searchSources(); }} className="flex gap-2"><input value={sourceQuery} onChange={(event) => setSourceQuery(event.target.value)} placeholder="Search a section, rule, clause or paragraph…" className="min-w-0 flex-1 rounded border bg-white px-2.5 py-2 text-xs"/><button type="submit" disabled={sourceBusy || !sourceQuery.trim()} className="rounded bg-blue-950 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">{sourceBusy ? "Searching…" : "Search"}</button></form>
        {sourceResults.length > 0 && <div className="max-h-52 overflow-y-auto rounded-md border bg-white">{sourceResults.map((source, index) => <button key={`${source.source_kind}-${source.id || source.document_id}-${source.source_locator?.index ?? index}`} type="button" onClick={() => chooseSource(source)} className="block w-full border-b px-3 py-2 text-left last:border-b-0 hover:bg-blue-50"><span className="mb-0.5 block text-[9px] font-bold uppercase tracking-wide text-emerald-700">{source.source_kind === "rule_paragraph" ? "Rule / paragraph" : "Act provision"}</span><strong className="block text-xs text-blue-950">{provisionSourceLabel(source)}</strong><span className="mt-0.5 line-clamp-2 block text-[11px] leading-4 text-slate-600">{source.current_text}</span></button>)}</div>}
        <p className="text-[11px] leading-4 text-slate-500">The callout always displays the selected source wording. Change that rule, paragraph or Act provision once and every linked callout updates automatically.</p>
      </div>}
    </div>
    <div><span className="text-xs font-bold text-slate-600">Colour</span><div className="mt-1 flex flex-wrap gap-2">{CALLOUT_COLORS.map((color, index) => <button key={color.name} type="button" title={color.name} aria-label={color.name} onClick={() => setDraft({ ...draft, color_index: index })} className={`size-7 rounded-full ${color.dot} ${Number(draft.color_index) === index ? "ring-2 ring-blue-950 ring-offset-2" : ""}`}/>)}</div></div>
    <div className="grid gap-3 sm:grid-cols-2"><label className="text-xs font-bold text-slate-600">From date (optional)<DatePicker value={draft.effective_from || ""} onChange={(value) => setDraft({ ...draft, effective_from: value })} allowEmpty className="mt-1" inputClassName="rounded border p-2 font-normal" ariaLabel="Callout start date"/></label><label className="text-xs font-bold text-slate-600">Until date (optional)<DatePicker value={draft.effective_to || ""} onChange={(value) => setDraft({ ...draft, effective_to: value })} allowEmpty className="mt-1" inputClassName="rounded border p-2 font-normal" ariaLabel="Callout end date"/></label></div>
    {error && <p className="text-xs font-semibold text-red-700">{error}</p>}<div className="flex gap-2"><button type="button" disabled={busy || !draft.title.trim() || (sourceMode === "linked" ? !draft.source_provision_id && !draft.source_document_id : !draft.content.trim())} onClick={save} className="rounded bg-blue-950 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">{busy ? "Saving…" : "Save callout"}</button><button type="button" onClick={() => onDone(false)} className="rounded border px-3 py-2 text-xs font-bold">Cancel</button></div>
  </div>;
};

const CalloutList = ({ callouts = [], provisionId, adminMode, onChanged, allowCreate = true, glossary = [], asOfDate }) => {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const finish = (changed) => { setCreating(false); setEditingId(null); if (changed) onChanged?.(); };
  const remove = async (id) => { if (!window.confirm("Delete this callout?")) return; const response = await adminFetch(`/api/admin/callouts/${id}`, { method: "DELETE" }); if (response.ok) onChanged?.(); };
  return <div className="mt-4 space-y-3">
    {callouts.filter((callout) => callout.callout_type !== "bulb").map((callout) => {
      const color = CALLOUT_COLORS[callout.color_index] || CALLOUT_COLORS[0];
      const type = calloutTypeDetails(callout.callout_type);
      const TypeIcon = type.icon;
      if (editingId === callout.id) return <CalloutEditor key={callout.id} initial={callout} provisionId={provisionId} onDone={finish} asOfDate={asOfDate}/>;
      const linked = callout.source_provision_id || callout.source_document_id;
      const displayedContent = linked ? callout.source_content : callout.content;
      return <details key={callout.id} className={`callout-card group overflow-visible rounded-xl border ${color.box}`}><summary className={`flex cursor-pointer list-none items-center gap-2.5 px-4 py-3 font-bold ${color.head}`}><span className={`grid size-8 shrink-0 place-items-center rounded-lg text-white shadow-sm ${color.dot}`} aria-hidden="true"><TypeIcon size={17} strokeWidth={2.1}/></span><span className="text-[11px] uppercase tracking-wide opacity-70">{type.label}</span><span className="min-w-0 flex-1">{callout.title}</span>{linked && <Link2 size={14} aria-label="Linked content"/>}<ChevronRight size={17} className="transition group-open:rotate-90"/></summary><div className="callout-body border-t border-current/10 px-4 py-3 text-sm leading-6 text-slate-800 whitespace-pre-wrap"><LinkedLegalText glossary={glossary} currentProvisionId={provisionId} adminMode={adminMode}>{displayedContent || callout.content}</LinkedLegalText>{callout.source_provision_id && <button type="button" onClick={() => navigateToSection(callout.source_section_number, null, callout.source_provision_id)} className="mt-3 flex items-center gap-1.5 border-t border-current/10 pt-2 text-xs font-bold text-blue-800 hover:text-blue-950"><Link2 size={13}/>Source: {provisionSourceLabel(callout) || callout.source_provision_id}</button>}{callout.source_document_id && <a href={`${apiBaseUrl}/api/documents/${encodeURIComponent(callout.source_document_id)}/pdf`} target="_blank" rel="noreferrer" className="mt-3 flex items-center gap-1.5 border-t border-current/10 pt-2 text-xs font-bold text-blue-800 hover:text-blue-950"><Link2 size={13}/>Source: {provisionSourceLabel(callout)}</a>}{adminMode && <div className="mt-3 flex gap-2 border-t border-slate-300/60 pt-3"><button type="button" onClick={() => setEditingId(callout.id)} className="rounded bg-white px-2.5 py-1 text-xs font-bold text-blue-900 shadow-sm">Edit</button><button type="button" onClick={() => remove(callout.id)} className="rounded bg-white px-2.5 py-1 text-xs font-bold text-red-700 shadow-sm">Delete</button></div>}</div></details>;
    })}
    {adminMode && allowCreate && provisionId && !creating && <button type="button" onClick={() => setCreating(true)} className="rounded-lg border border-dashed border-blue-400 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-950">+ Add callout</button>}
    {creating && <CalloutEditor initial={emptyCallout(callouts.length)} provisionId={provisionId} onDone={finish} asOfDate={asOfDate}/>}</div>;
};

const BulbNoteModal = ({ note, provisionId, anchor, adminMode, onClose, onChanged, glossary = [], asOfDate }) => {
  const [editing, setEditing] = useState(!note);
  const color = CALLOUT_COLORS[note?.color_index ?? 0] || CALLOUT_COLORS[0];
  const finish = (changed) => { if (changed) onChanged?.(); onClose(); };
  const remove = async () => { if (!window.confirm("Delete this bulb note?")) return; const response = await adminFetch(`/api/admin/callouts/${note.id}`, { method: "DELETE" }); if (response.ok) finish(true); };
  const initial = note || { ...emptyCallout(), callout_type: "bulb", title: "Additional information", anchor: anchor || {} };
  const displayedContent = note?.source_provision_id || note?.source_document_id ? note.source_content : note?.content;
  return <div className="motion-modal-backdrop fixed inset-0 z-[80] grid place-items-center bg-slate-950/60 p-4 backdrop-blur-sm" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section role="dialog" aria-modal="true" aria-label={note?.title || "Add bulb note"} className={`motion-modal-panel w-full max-w-2xl overflow-hidden rounded-2xl border shadow-2xl ${color.box}`}><header className={`flex items-center gap-3 border-b border-current/10 px-5 py-4 ${color.head}`}><span className="grid size-10 shrink-0 place-items-center rounded-full bg-white/80"><Lightbulb size={22}/></span><div className="min-w-0 flex-1"><span className="text-[11px] font-bold uppercase tracking-wider opacity-70">Anchored information</span><h3 className="truncate text-lg font-extrabold">{note?.title || "Add additional information"}</h3></div><button type="button" onClick={onClose} className="grid size-9 place-items-center rounded-lg hover:bg-white/60" aria-label="Close"><X size={19}/></button></header><div className="max-h-[70vh] overflow-y-auto p-5">{editing ? <CalloutEditor initial={initial} provisionId={provisionId} lockedType="bulb" onDone={finish} asOfDate={asOfDate}/> : <><div className="whitespace-pre-wrap text-[15px] leading-7 text-slate-900"><LinkedLegalText onNavigate={onClose} glossary={glossary} currentProvisionId={provisionId} adminMode={adminMode}>{displayedContent}</LinkedLegalText></div>{note?.source_provision_id && <button type="button" onClick={() => navigateToSection(note.source_section_number, onClose, note.source_provision_id)} className="mt-4 flex items-center gap-1.5 border-t border-current/10 pt-3 text-xs font-bold text-blue-800"><Link2 size={13}/>Source: {provisionSourceLabel(note) || note.source_provision_id}</button>}{note?.source_document_id && <a href={`${apiBaseUrl}/api/documents/${encodeURIComponent(note.source_document_id)}/pdf`} target="_blank" rel="noreferrer" className="mt-4 flex items-center gap-1.5 border-t border-current/10 pt-3 text-xs font-bold text-blue-800"><Link2 size={13}/>Source: {provisionSourceLabel(note)}</a>}{adminMode && <div className="mt-5 flex gap-2 border-t border-current/10 pt-4"><button type="button" onClick={() => setEditing(true)} className="rounded-lg bg-blue-950 px-3 py-2 text-xs font-bold text-white">Edit</button><button type="button" onClick={remove} className="rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-bold text-red-700">Delete</button></div>}</>}</div></section></div>;
};

const snapTextAnchor = (text, rawOffset) => {
  const candidates = new Set([0, text.length]);
  for (const match of text.matchAll(/[.!?;:](?:\s|$)|\b/gu)) candidates.add(match.index + match[0].trimEnd().length);
  const offset = [...candidates].reduce((best, value) => Math.abs(value - rawOffset) < Math.abs(best - rawOffset) ? value : best, 0);
  const before = text.slice(0, offset);
  const sentenceBoundary = /[.!?;:]\s*$/.test(before);
  return { kind: offset === text.length ? "end" : sentenceBoundary ? "sentence" : "word", offset, quote: text.slice(Math.max(0, offset - 30), Math.min(text.length, offset + 30)) };
};

const AnchoredText = ({ text = "", callouts = [], provisionId, adminMode, onOpenBulb, className = "", glossary = [] }) => {
  const rootRef = useRef(null);
  const [previewAnchor, setPreviewAnchor] = useState(null);
  const bulbs = callouts.filter((callout) => callout.callout_type === "bulb").sort((a, b) => Number(a.anchor?.offset ?? text.length) - Number(b.anchor?.offset ?? text.length));
  const anchorFromEvent = (event) => {
    let offset = text.length;
    const caret = document.caretRangeFromPoint?.(event.clientX, event.clientY) || document.caretPositionFromPoint?.(event.clientX, event.clientY);
    const caretNode = caret?.startContainer || caret?.offsetNode;
    const caretOffset = caret?.startOffset ?? caret?.offset ?? 0;
    if (caretNode && rootRef.current?.contains(caretNode)) {
      const walker = document.createTreeWalker(rootRef.current, NodeFilter.SHOW_TEXT);
      let node; offset = 0;
      while ((node = walker.nextNode())) {
        if (node.parentElement?.closest("[data-anchor-marker], [data-glossary-popover]")) continue;
        if (node === caretNode) { offset += Math.min(caretOffset, node.textContent.length); break; }
        offset += node.textContent.length;
      }
    }
    return snapTextAnchor(text, offset);
  };
  const dragOver = (event) => {
    if (!adminMode || !provisionId) return;
    event.preventDefault(); event.dataTransfer.dropEffect = "copy";
    const next = anchorFromEvent(event);
    if (next.offset !== previewAnchor?.offset || next.kind !== previewAnchor?.kind) setPreviewAnchor(next);
  };
  const drop = (event) => {
    if (!adminMode || event.dataTransfer.getData("application/x-companies-bulb") !== "bulb") return;
    event.preventDefault();
    const anchor = previewAnchor || anchorFromEvent(event); setPreviewAnchor(null);
    onOpenBulb({ note: null, provisionId, anchor });
  };
  const markers = bulbs.map((bulb) => ({ offset: Number(bulb.anchor?.offset ?? text.length), bulb }));
  if (previewAnchor) markers.push({ offset: previewAnchor.offset, preview: previewAnchor });
  markers.sort((a, b) => a.offset - b.offset);
  const parts = []; let cursor = 0;
  markers.forEach((marker, index) => { const offset = Math.max(cursor, Math.min(text.length, marker.offset)); parts.push(<React.Fragment key={`text-${cursor}-${offset}`}>{displayInlineText(text.slice(cursor, offset), glossary, provisionId, adminMode)}</React.Fragment>); if (marker.bulb) { const bulbColor = CALLOUT_COLORS[marker.bulb.color_index] || CALLOUT_COLORS[0]; parts.push(<button data-anchor-marker key={`bulb-${marker.bulb.id}`} type="button" onClick={() => onOpenBulb({ note: marker.bulb, provisionId, anchor: marker.bulb.anchor })} className={`bulb-icon relative -top-[0.5em] mx-0.5 inline-grid size-5 place-items-center rounded-full border border-white/70 text-white shadow-sm ring-1 ring-slate-300 transition hover:brightness-90 ${bulbColor.dot}`} aria-label="View additional information"><Lightbulb size={12}/></button>); } else parts.push(<span data-anchor-marker key={`preview-${index}`} className="pointer-events-none relative -top-[0.5em] mx-0.5 inline-grid size-5 animate-pulse place-items-center rounded-full border-2 border-dashed border-amber-500 bg-amber-100 text-amber-800 shadow"><Lightbulb size={12}/></span>); cursor = offset; });
  parts.push(<React.Fragment key={`text-${cursor}-end`}>{displayInlineText(text.slice(cursor), glossary, provisionId, adminMode)}</React.Fragment>);
  if (!text && !bulbs.length && !adminMode) return null;
  return <span ref={rootRef} onDragOver={dragOver} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setPreviewAnchor(null); }} onDrop={drop} className={`${className} ${!text ? "inline-flex min-h-10 w-full items-center justify-center" : ""} ${adminMode ? "rounded outline-offset-4 hover:outline hover:outline-2 hover:outline-dashed hover:outline-amber-300" : ""}`}>{parts}{!text && adminMode && !bulbs.length && !previewAnchor && <span className="text-xs font-semibold text-amber-700">Drop a bulb here for the end of the section</span>}</span>;
};

const DocumentCategoryPanel = ({ relationships, label, onOpen, adminMode = false, onChanged, onCountChange, targetProvisionId }) => {
  const [removeMode, setRemoveMode] = useState(false);
  const [removedIds, setRemovedIds] = useState(() => new Set());
  const visibleRelationships = relationships.filter((relationship) => !removedIds.has(relationship.relationship_id));
  const addCustom = () => onOpen({ create: true, category: label, targetProvisionId: targetProvisionId || relationships[0]?.target_provision_id, onCreated: () => onCountChange?.(1) });
  const actions = adminMode && <div className="flex flex-wrap gap-2"><button type="button" onClick={addCustom} className="rounded-lg bg-blue-950 px-3 py-2 text-xs font-bold text-white">+ Add {label}</button><button type="button" onClick={() => setRemoveMode((value) => !value)} className="rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-bold text-red-700">{removeMode ? "Done" : `Remove ${label}`}</button></div>;
  if (!visibleRelationships.length) return <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-10 text-center"><FileText className="mx-auto mb-3 text-slate-400"/><h4 className="font-bold text-slate-800">No {label.toLowerCase()} linked to this section</h4>{actions && <div className="mt-3 flex justify-center">{actions}</div>}</div>;
  return <div className="space-y-3">{actions}<div className="grid gap-3">{visibleRelationships.map((relationship) => <div key={relationship.relationship_id} className="document-card flex items-start gap-2 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><button type="button" onClick={() => { if (!removeMode) onOpen({ relationships: visibleRelationships, category: label, initialDocumentId: relationship.document?.id, targetProvisionId: relationship.target_provision_id }); }} className={`min-w-0 flex-1 text-left ${removeMode ? "cursor-default" : ""}`}><span className="text-[11px] font-bold uppercase tracking-wide text-blue-800">{readableInstrumentType(relationship.document.instrument_type)}</span><strong className="mt-1 block text-sm leading-6 text-slate-900">{relationship.document.title}</strong>{relationship.document.publication_date && <span className="mt-1 block text-xs text-slate-500">{relationship.document.publication_date}</span>}</button>{adminMode && removeMode && <button type="button" onClick={async (event) => { event.stopPropagation(); if (!window.confirm("Remove this document from the section?")) return; const response = await adminFetch(`/api/admin/relationships/${relationship.relationship_id}`, { method: "DELETE" }); if (response.ok) { setRemovedIds((current) => new Set([...current, relationship.relationship_id])); onCountChange?.(-1); } }} className="text-xs font-bold text-red-700">Remove</button>}</div>)}</div></div>;
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
  // The source file is already in legal reading order. Sorting identifiers moved
  // unnumbered continuation paragraphs ("N/A") to the end of a section.
  return [...groups.values()];
};

const wordTokens = (text) => String(text || "").match(/\s+|[\p{L}\p{N}]+|[^\s\p{L}\p{N}]/gu) || [];

const coalescedWordDiff = (earlierText, currentText) => {
  const earlier = wordTokens(earlierText);
  const current = wordTokens(currentText);
  const table = Array.from({ length: earlier.length + 1 }, () => new Uint16Array(current.length + 1));
  for (let left = earlier.length - 1; left >= 0; left -= 1) {
    for (let right = current.length - 1; right >= 0; right -= 1) {
      table[left][right] = earlier[left] === current[right]
        ? table[left + 1][right + 1] + 1
        : Math.max(table[left + 1][right], table[left][right + 1]);
    }
  }
  const operations = [];
  const append = (type, value) => {
    const previous = operations[operations.length - 1];
    if (previous?.type === type) previous.value += value;
    else operations.push({ type, value });
  };
  let left = 0;
  let right = 0;
  while (left < earlier.length && right < current.length) {
    if (earlier[left] === current[right]) {
      append("same", earlier[left]); left += 1; right += 1;
    } else if (table[left + 1][right] >= table[left][right + 1]) {
      append("removed", earlier[left]); left += 1;
    } else {
      append("added", current[right]); right += 1;
    }
  }
  while (left < earlier.length) { append("removed", earlier[left]); left += 1; }
  while (right < current.length) { append("added", current[right]); right += 1; }
  return operations;
};

const CoalescedAmendment = ({ currentText, earlier, onOpenAmendment, glossary = [], provisionId, callouts = [], onOpenBulb, adminMode = false }) => {
  const operations = useMemo(() => coalescedWordDiff(earlier.text, currentText), [earlier.text, currentText]);
  const sources = amendmentPdfSources(earlier.source_note);
  const bulbs = callouts.filter((callout) => callout.callout_type === "bulb").sort((left, right) => Number(left.anchor?.offset || 0) - Number(right.anchor?.offset || 0));
  let markerIndex = 0;
  let currentOffset = 0;
  const styledCurrentPart = (value, type, key) => {
    const content = displayInlineText(value, glossary, provisionId, adminMode);
    return type === "added"
      ? <ins key={key} className="rounded-sm bg-emerald-100 px-0.5 font-medium text-emerald-900 no-underline box-decoration-clone">{content}</ins>
      : <React.Fragment key={key}>{content}</React.Fragment>;
  };
  const renderCurrentOperation = (operation, operationIndex) => {
    const start = currentOffset;
    const end = start + operation.value.length;
    const pieces = [];
    let localOffset = 0;
    while (markerIndex < bulbs.length && Number(bulbs[markerIndex].anchor?.offset ?? currentText.length) <= end) {
      const bulb = bulbs[markerIndex];
      const absoluteOffset = Math.max(start, Number(bulb.anchor?.offset ?? end));
      const relativeOffset = Math.max(localOffset, Math.min(operation.value.length, absoluteOffset - start));
      if (relativeOffset > localOffset) pieces.push(styledCurrentPart(operation.value.slice(localOffset, relativeOffset), operation.type, `${operationIndex}-text-${localOffset}`));
      const bulbColor = CALLOUT_COLORS[bulb.color_index] || CALLOUT_COLORS[0];
      pieces.push(<button data-anchor-marker key={`${operationIndex}-bulb-${bulb.id}`} type="button" onClick={() => onOpenBulb?.({ note: bulb, provisionId, anchor: bulb.anchor })} className={`bulb-icon relative -top-[0.5em] mx-0.5 inline-grid size-5 place-items-center rounded-full border border-white/70 text-white shadow-sm ring-1 ring-slate-300 transition hover:brightness-90 ${bulbColor.dot}`} aria-label="View additional information"><Lightbulb size={12}/></button>);
      localOffset = relativeOffset;
      markerIndex += 1;
    }
    if (localOffset < operation.value.length) pieces.push(styledCurrentPart(operation.value.slice(localOffset), operation.type, `${operationIndex}-text-end`));
    currentOffset = end;
    return pieces;
  };
  return (
    <span className="block min-w-0 flex-1">
      <span className="whitespace-pre-line text-[15px] leading-7 text-gray-900 sm:text-base">
        {operations.map((operation, index) => {
          if (operation.type === "removed") return <del key={index} className="rounded-sm bg-rose-100 px-0.5 text-rose-800 decoration-rose-500 decoration-2"><GlossaryText glossary={glossary} currentProvisionId={provisionId} adminMode={adminMode}>{operation.value}</GlossaryText></del>;
          return <React.Fragment key={index}>{renderCurrentOperation(operation, index)}</React.Fragment>;
        })}
      </span>
      <span className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] font-bold uppercase tracking-wide">
        <span className="text-rose-700"><span className="mr-1 inline-block size-2 rounded-sm bg-rose-200"/>Earlier wording</span>
        <span className="text-emerald-800"><span className="mr-1 inline-block size-2 rounded-sm bg-emerald-200"/>Current wording</span>
        {sources.length > 0 && <button type="button" onClick={() => onOpenAmendment(earlier.source_note)} className="text-blue-800 underline decoration-blue-300 underline-offset-2 normal-case tracking-normal">View amendment source</button>}
      </span>
      {earlier.source_note && <span className="mt-1 block text-[11px] leading-5 text-slate-500">{earlier.source_note}</span>}
    </span>
  );
};

export const SubsectionRenderer = ({ subsection, historical = false, historicalVersions = [], onOpenAmendment, onOpenDocument, editing = false, onTextChange, draftTexts = {}, adminMode = false, onCalloutsChanged, glossary = [], asOfDate }) => {
  const [activeBulb, setActiveBulb] = useState(null);
  const earlierVersion = historicalVersions[0] || subsection.historical_versions?.[0];
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
      id={subsection._provisionId || undefined}
      className={`mb-3 border-l-2 pl-3 sm:mb-4 sm:pl-4 ${
        historical ? "border-amber-400 bg-amber-50/40 py-3 pr-3" : "border-gray-200"
      }`}
    >
      <div className="flex items-start gap-2">
        {subsection.subsection_number && subsection.subsection_number !== "N/A" && (
          <span className="font-bold text-gray-700">{subsection.subsection_number}</span>
        )}
        {subsection.text && (editing && subsection._provisionId ? (
          <RichTextEditor value={draftTexts[subsection._provisionId] ?? subsection.text} onChange={(value) => onTextChange(subsection._provisionId, value)} className="min-h-24 flex-1"/>
        ) : earlierVersion?.text ? (
          <CoalescedAmendment currentText={subsection.text} earlier={earlierVersion} onOpenAmendment={onOpenAmendment} glossary={glossary} provisionId={subsection._provisionId} callouts={subsection.callouts} onOpenBulb={setActiveBulb} adminMode={adminMode}/>
        ) : (
          <p className="text-[15px] leading-7 text-gray-900 sm:text-base"><AnchoredText text={subsection.text} callouts={subsection.callouts} provisionId={subsection._provisionId} adminMode={adminMode} onOpenBulb={setActiveBulb} glossary={glossary}/></p>
        ))}
      </div>
      {subsection.amendments?.length > 0 && <div className="ml-0 mt-1 space-y-1 text-[11px] leading-5 text-slate-500 sm:ml-8">{subsection.amendments.map((amendment, index) => <p key={`amendment-note-${index}`}><strong>{amendment.footnote_ref ? `[${amendment.footnote_ref}] ` : ""}</strong>{amendment.note}</p>)}</div>}

      {clauseGroups.length > 0 && (
        <div className="ml-1 mt-3 space-y-3 sm:ml-6">
          {clauseGroups.map((group, groupIndex) => (
            <div key={`clause-group-${normalizeIdentifier(group.identifier)}-${groupIndex}`}>
              {group.current.map((clause, index) => {
                return (
                <div
                  key={`clause-${clause.clause_number || index}-${index}`}
                  id={clause._provisionId || undefined}
                  className="text-[15px] leading-7 text-gray-800 sm:text-base"
                >
                  <div className="flex items-start gap-2">
                    <span className="min-w-8 shrink-0 font-semibold text-blue-700">
                      {clause.clause_number}
                    </span>
                    {editing && clause._provisionId ? <RichTextEditor value={draftTexts[clause._provisionId] ?? clause.text} onChange={(value) => onTextChange(clause._provisionId, value)} className="min-h-20 min-w-0 flex-1"/> : group.historical[0]?.text && index === 0 ? <CoalescedAmendment currentText={clause.text} earlier={group.historical[0]} onOpenAmendment={onOpenAmendment} glossary={glossary} provisionId={clause._provisionId} callouts={clause.callouts} onOpenBulb={setActiveBulb} adminMode={adminMode}/> : <AnchoredText text={clause.text} callouts={clause.callouts} provisionId={clause._provisionId} adminMode={adminMode} onOpenBulb={setActiveBulb} className="min-w-0 flex-1" glossary={glossary}/>} 
                  </div>
                  <CalloutList callouts={clause.callouts} provisionId={clause._provisionId} adminMode={adminMode} allowCreate={false} onChanged={onCalloutsChanged} glossary={glossary} asOfDate={asOfDate}/>
                </div>
                );
              })}
              {!group.current.length && group.historical[0]?.text && <div className="flex items-start gap-2"><span className="min-w-8 shrink-0 font-semibold text-blue-700">{group.historical[0].clause_number}</span><CoalescedAmendment currentText="" earlier={group.historical[0]} onOpenAmendment={onOpenAmendment} glossary={glossary}/></div>}
            </div>
          ))}
        </div>
      )}

      <CalloutList callouts={subsection.callouts} provisionId={subsection._provisionId} adminMode={adminMode} onChanged={onCalloutsChanged} glossary={glossary} asOfDate={asOfDate}/>
      {activeBulb && <BulbNoteModal note={activeBulb.note} provisionId={activeBulb.provisionId} anchor={activeBulb.anchor} adminMode={adminMode} onClose={() => setActiveBulb(null)} onChanged={onCalloutsChanged} glossary={glossary} asOfDate={asOfDate}/>} 
    </div>
  );
};

export const SectionCard = ({
  section,
  asOfDate,
  adminMode = false,
  readerHeader = null,
  tabsPortalTarget = null,
  showWorkspaceTabs = true,
}) => {
  const [pdfSources, setPdfSources] = useState([]);
  const [timelineData, setTimelineData] = useState(() => {
    if (!section?.section_number || !asOfDate) return null;
    const cacheKey = `section:${String(section.section_number).toUpperCase()}:${asOfDate}`;
    return readReaderCache(cacheKey)?.data || null;
  });
  const [activeDocuments, setActiveDocuments] = useState(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [adminRecord, setAdminRecord] = useState(null);
  const [adminDraft, setAdminDraft] = useState("");
  const [adminEditing, setAdminEditing] = useState(false);
  const [adminRevision, setAdminRevision] = useState(null);
  const [adminBusy, setAdminBusy] = useState(false);
  const [adminMessage, setAdminMessage] = useState("");
  const [adminChanges, setAdminChanges] = useState({});
  const [timelineRefresh, setTimelineRefresh] = useState(0);
  const [workspaceTab, setWorkspaceTab] = useState("Act");
  const [documentCountAdjustments, setDocumentCountAdjustments] = useState({});
  useEffect(() => { setDocumentCountAdjustments({}); }, [timelineRefresh]);
  const [activeSectionBulb, setActiveSectionBulb] = useState(null);
  const [glossary, setGlossary] = useState([]);
  useEffect(() => {
    setWorkspaceTab("Act");
  }, [section?.section_number]);
  useEffect(() => {
    const refreshGlossary = () => setTimelineRefresh((value) => value + 1);
    window.addEventListener("companies-act:glossary-changed", refreshGlossary);
    return () => window.removeEventListener("companies-act:glossary-changed", refreshGlossary);
  }, []);
  const flattenNodes = (items) => items.flatMap((item) => [item, ...flattenNodes(item.children || [])]);
  const buildSource = () => {
    const title = `Section ${timelineData?.section?.section_number || section.section_number}: ${timelineData?.section?.title || section.title || ""}`;
    return `${title}\n\n${timelineData?.section?.current_text || adminRecord?.current_text || ""}`;
  };
  const parseSource = (source) => {
    const firstBreak = source.search(/\r?\n/);
    const titleLine = (firstBreak === -1 ? source : source.slice(0, firstBreak)).trim();
    const titleMatch = titleLine.match(/^Section\s+[^:]+:\s*(.*)$/i);
    const body = firstBreak === -1 ? "" : source.slice(firstBreak).trim();
    return {
      title: titleMatch?.[1]?.trim(),
      items: timelineData?.section?.id ? [{ id: timelineData.section.id, text: body }] : [],
    };
  };

  const adminRequest = async (path, options = {}) => {
    const response = await adminFetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    return payload;
  };

  const loadAdminRecord = async () => {
    if (!adminMode || !section?.section_number) return;
    const number = String(section.section_number);
    const data = await adminRequest(`/api/admin/provisions?q=${encodeURIComponent(number)}&as_of=${asOfDate}&limit=100`);
    const record = data.results.find((item) => item.provision_type === "section" && String(item.section_number) === number);
    setAdminRecord(record || null);
    setAdminDraft(record?.current_text || "");
    if (record) {
      const history = await adminRequest(`/api/admin/revisions?provision_id=${encodeURIComponent(record.id)}`);
      setAdminRevision(history.results.find((item) => item.field_name === "current_text" && item.effective_date === asOfDate && !item.undone_by_revision_id && !item.reverts_revision_id) || null);
    }
  };

  useEffect(() => {
    setAdminEditing(false); setAdminMessage("");
    loadAdminRecord().catch((error) => setAdminMessage(error.message));
  }, [adminMode, asOfDate, section?.section_number]);

  const saveAdminText = async () => {
    if (!adminRecord) return;
    setAdminBusy(true); setAdminMessage("");
    try {
      const nodes = [timelineData?.section, ...flattenNodes(timelineData?.provisions || [])].filter(Boolean);
      const byId = new Map(nodes.map((node) => [node.id, node]));
      for (const [id, text] of Object.entries(adminChanges)) {
        const node = byId.get(id);
        if (node && text !== (node.current_text || "")) await adminRequest(`/api/admin/provisions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ field: "current_text", value: text, as_of: asOfDate }) });
      }
      const cleanup = await adminRequest("/api/admin/relationships/deduplicate", { method: "POST", body: JSON.stringify({ provision_id: timelineData.section.id }) });
      setAdminEditing(false); setAdminChanges({}); setAdminMessage(cleanup.removed ? `Saved. Removed ${cleanup.removed} duplicate document reference${cleanup.removed === 1 ? "" : "s"}.` : "Saved."); setTimelineRefresh((value) => value + 1);
      await loadAdminRecord();
    } catch (error) { setAdminMessage(error.message); } finally { setAdminBusy(false); }
  };

  const undoAdminText = async () => {
    if (!adminRevision) return;
    setAdminBusy(true); setAdminMessage("");
    try {
      const result = await adminRequest(`/api/admin/revisions/${adminRevision.id}/undo`, { method: "POST" });
      setAdminRecord({ ...adminRecord, current_text: result.value || "" }); setAdminDraft(result.value || ""); setAdminEditing(false); setAdminMessage("Last edit undone."); setAdminRevision(null);
    } catch (error) { setAdminMessage(error.message); } finally { setAdminBusy(false); }
  };

  useEffect(() => {
    if (!section?.section_number || !asOfDate) return undefined;
    const controller = new AbortController();
    const url = `${apiBaseUrl}/api/sections/${encodeURIComponent(section.section_number)}/related?as_of=${encodeURIComponent(asOfDate)}`;
    const cacheKey = `section:${String(section.section_number).toUpperCase()}:${asOfDate}`;
    if (timelineRefresh > 0) removeReaderCache(cacheKey);
    const cached = timelineRefresh > 0 ? null : readReaderCache(cacheKey);
    setTimelineData(cached?.data || null);
    setTimelineLoading(!cached);

    fetch(url, { signal: controller.signal, cache: "no-store", headers: { Accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Timeline API returned ${response.status}`);
        const raw = await response.text();
        return { raw, data: JSON.parse(raw) };
      })
      .then(({ raw, data }) => {
        if (!cached || cached.raw !== raw) setTimelineData(data);
        writeReaderCache(cacheKey, raw, data);
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          console.warn(cached ? "Using cached section because revalidation failed:" : "Using bundled section text because timeline data is unavailable:", error);
          if (!cached) setTimelineData(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setTimelineLoading(false);
      });

    return () => controller.abort();
  }, [asOfDate, section?.section_number, timelineRefresh]);

  useEffect(() => {
    const controller = new AbortController();
    const cacheKey = "glossary";
    if (timelineRefresh > 0) removeReaderCache(cacheKey);
    const cached = timelineRefresh > 0 ? null : readReaderCache(cacheKey);
    if (cached) setGlossary(cached.data.results || []);
    fetch(`${apiBaseUrl}/api/glossary`, { signal: controller.signal, headers: { Accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Glossary API returned ${response.status}`);
        const raw = await response.text();
        return { raw, data: JSON.parse(raw) };
      })
      .then(({ raw, data }) => {
        if (!cached || cached.raw !== raw) setGlossary(data.results || []);
        writeReaderCache(cacheKey, raw, data);
      })
      .catch((error) => {
        if (error.name !== "AbortError") console.warn("Glossary is unavailable:", error);
      });
    return () => controller.abort();
  }, [timelineRefresh]);

  if (!section) return null;

  const openAmendment = (sourceNote) => {
    const sources = amendmentPdfSources(sourceNote);
    if (sources.length) setPdfSources(sources);
  };

  const sectionNumber = String(section.section_number || "");
  const escapedSectionNumber = sectionNumber.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const displayTitle = String(timelineData?.section?.title || section.title || "").replace(
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
  const provisionByLabel = new Map(
    (timelineData?.provisions || []).map((provision) => [normalizeIdentifier(provision.label), provision]),
  );
  const directClauseByLabel = new Map(
    (timelineData?.provisions || [])
      .filter((provision) => provision.provision_type === "clause")
      .map((provision) => [normalizeIdentifier(provision.label), provision]),
  );
  const verifiedParts = timelineData?.section?.version_change_type === "human_verification"
    ? String(timelineData.section.current_text || "").split(/\r?\n/).map((line) => {
        const match = line.match(/^\s*(\([^)]+\)|[A-Za-z0-9]+[.)])\s*(.*)$/);
        return match ? { label: normalizeIdentifier(match[1]), text: match[2] } : null;
      }).filter(Boolean)
    : [];
  const verifiedLines = String(timelineData?.section?.current_text || "").split(/\r?\n/);
  const subsectionLabels = new Set((section.subsections || []).map((item) => normalizeIdentifier(item.subsection_number)).filter((label) => label && label !== "n/a"));
  const clausesInVerifiedOrder = (subsection) => {
    const clauses = subsection.clauses || [];
    if (clauses.length < 2) return clauses;
    const subsectionLabel = normalizeIdentifier(subsection.subsection_number);
    const clauseLabels = new Set(clauses.map((clause) => normalizeIdentifier(clause.clause_number)));
    let inside = false; const orderedLabels = [];
    for (const line of verifiedLines) {
      const match = line.match(/^\s*(\([^)]+\)|[A-Za-z0-9]+[.)])\s*/);
      if (!match) continue;
      const label = normalizeIdentifier(match[1]);
      if (label === subsectionLabel) { inside = true; continue; }
      if (inside && subsectionLabels.has(label)) break;
      if (inside && clauseLabels.has(label) && !orderedLabels.includes(label)) orderedLabels.push(label);
    }
    if (!orderedLabels.length) return clauses;
    const rank = new Map(orderedLabels.map((label, index) => [label, index]));
    return [...clauses].sort((left, right) => (rank.get(normalizeIdentifier(left.clause_number)) ?? Number.MAX_SAFE_INTEGER) - (rank.get(normalizeIdentifier(right.clause_number)) ?? Number.MAX_SAFE_INTEGER));
  };
  let verifiedPartIndex = 0;
  const takeVerifiedText = (label) => {
    const normalized = normalizeIdentifier(label);
    for (let index = verifiedPartIndex; index < verifiedParts.length; index += 1) {
      if (verifiedParts[index].label === normalized) {
        verifiedPartIndex = index + 1;
        return verifiedParts[index].text;
      }
    }
    return null;
  };
  const subsections = (section.subsections || []).map((subsection) => {
    const provision = provisionByLabel.get(normalizeIdentifier(subsection.subsection_number));
    const childByLabel = new Map(
      (provision?.children || []).map((child) => [normalizeIdentifier(child.label), child]),
    );
    const isUnnumbered = String(subsection.subsection_number || "").trim().toUpperCase() === "N/A";
    const clausesByLabel = provision ? childByLabel : isUnnumbered ? directClauseByLabel : new Map();
    const verifiedSubsectionText = isUnnumbered ? null : takeVerifiedText(subsection.subsection_number);

    if (!provision && !isUnnumbered) return subsection;
    return {
      ...subsection,
      _provisionId: provision?.id,
      text: verifiedSubsectionText ?? provision?.current_text ?? subsection.text,
      status: provision?.status || subsection.status,
      related_documents: provision?.relationships || [],
      callouts: provision?.callouts || [],
      clauses: clausesInVerifiedOrder(subsection).map((clause) => {
        const child = clausesByLabel.get(normalizeIdentifier(clause.clause_number));
        const verifiedClauseText = takeVerifiedText(clause.clause_number);
        return child
            ? {
              ...clause,
              _provisionId: child.id,
              text: verifiedClauseText ?? child.current_text ?? clause.text,
              status: child.status || clause.status,
              related_documents: child.relationships || [],
              callouts: child.callouts || [],
            }
          : { ...clause, text: verifiedClauseText ?? clause.text };
      }),
    };
  });
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
  const timelineNodes = [timelineData?.section, ...flattenNodes(timelineData?.provisions || [])].filter(Boolean);
  const uniqueByDocument = (items) => items.filter((item, index, list) => list.findIndex((candidate) => candidate.document?.id === item.document?.id) === index);
  const allRelationships = uniqueByDocument([
    ...(timelineData?.section_relationships || []),
    ...timelineNodes.flatMap((node) => node.relationships || []),
  ]);
  const instrument = (relationship) => String(relationship.document?.instrument_type || "").toLowerCase();
  const categorizedDocuments = {
    Rules: allRelationships.filter((item) => instrument(item).includes("rule")),
    Notifications: allRelationships.filter((item) => /(form|notification|order|circular)/.test(instrument(item))),
  };
  const insightCallouts = [
    ...(timelineData?.section_callouts || []),
    ...timelineNodes.flatMap((node) => node.callouts || []),
  ].filter((callout) => callout.callout_type !== "amendment" && callout.callout_type !== "bulb");
  const tabs = [
    { label: "Act", count: null },
    { label: "Rules", count: categorizedDocuments.Rules.length + (documentCountAdjustments.Rules || 0) },
    { label: "Notifications", count: categorizedDocuments.Notifications.length + (documentCountAdjustments.Notifications || 0) },
    { label: "Actionable Insights", count: insightCallouts.length },
  ];
  const workspaceTabs = (
    <nav aria-label="Content categories" data-no-swipe className="grid w-full grid-cols-4 overflow-hidden bg-white md:flex md:overflow-x-auto">
      {tabs.map((tab) => <button key={tab.label} type="button" aria-label={tab.count === null ? tab.label : `${tab.label}, ${tab.count}`} onClick={() => setWorkspaceTab(tab.label)} className={`content-tab relative flex min-h-14 min-w-0 items-center justify-center border-r border-slate-300 px-1 text-[9px] font-bold leading-[1.05] md:min-h-12 md:shrink-0 md:px-4 md:text-sm ${workspaceTab === tab.label ? "is-active bg-red-50 text-red-900" : "bg-white text-slate-700 hover:bg-slate-50"}`}><span className="max-w-full whitespace-normal text-center">{tab.label}</span>{tab.count !== null && <span className="absolute right-1 top-1 rounded-full bg-slate-200 px-1 py-0.5 text-[8px] leading-none text-slate-700 md:static md:ml-1.5 md:px-1.5 md:text-[10px]">{tab.count}</span>}</button>)}
    </nav>
  );

  return (
    <>
      {readerHeader && (
        <div className="reader-sticky-header sticky top-0 z-30 mb-4 hidden bg-slate-50 shadow-[0_8px_16px_-14px_rgba(15,23,42,0.55)] md:block">
          <div className="border border-slate-300 bg-white">
            {readerHeader}
          </div>
        </div>
      )}
      {showWorkspaceTabs && (tabsPortalTarget
        ? createPortal(workspaceTabs, tabsPortalTarget)
        : <div className="mb-4 border border-slate-300 bg-white">{workspaceTabs}</div>)}
      <article
        id={timelineData?.section?.id || undefined}
        className={`section-content-enter relative mb-4 rounded-xl border p-4 shadow-sm sm:mb-6 sm:p-6 sm:shadow-md ${
          section.historical ? "border-red-200 bg-red-50/40" : "border-gray-200 bg-white"
        }`}
      >
        {timelineLoading && (
          <div className="absolute inset-x-0 top-0 z-10 flex items-center justify-center gap-2 rounded-t-xl bg-blue-950/90 px-3 py-2 text-xs font-bold text-white shadow-sm" role="status">
            <LoaderCircle size={15} className="animate-spin" />
            Updating current section…
          </div>
        )}
        <div className={`mb-3 flex-wrap items-center gap-3 ${section.historical ? "flex" : "hidden md:flex"}`}>
          <h3 className="hidden text-base font-extrabold leading-snug text-gray-900 sm:text-lg md:block">
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

        <div key={workspaceTab} className="workspace-scene">
        {workspaceTab === "Act" && adminMode && <div className="mb-4 flex flex-wrap items-center gap-2 border-y border-slate-200 py-2">
          <button type="button" disabled={adminEditing || adminBusy || !adminRecord} onClick={() => { setAdminDraft(buildSource()); setAdminEditing(true); }} className="inline-flex items-center gap-1.5 rounded-lg bg-blue-950 px-3 py-2 text-xs font-bold text-white disabled:opacity-40"><Pencil size={14}/>Edit</button>
          <button type="button" disabled={!adminEditing || adminBusy} onClick={saveAdminText} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-40"><Save size={14}/>Save</button>
          <button type="button" disabled={adminEditing || adminBusy || !adminRevision} onClick={undoAdminText} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900 disabled:opacity-40"><Undo2 size={14}/>Undo</button>
          <button type="button" disabled={!adminEditing || adminBusy} onClick={() => { setAdminChanges({}); setAdminEditing(false); setAdminMessage(""); }} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold text-slate-700 disabled:opacity-40"><X size={14}/>Cancel</button>
          {adminMessage && <span className="text-xs font-semibold text-blue-800">{adminMessage}</span>}
        </div>}

        {workspaceTab === "Act" && <>
        {adminMode && !adminEditing && <div className="mb-4 flex items-center gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3"><button type="button" draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("application/x-companies-bulb", "bulb"); }} className="grid size-5 cursor-grab place-items-center rounded-full border border-amber-400 bg-amber-100 text-amber-700 shadow-sm active:cursor-grabbing" title="Drag into the section"><Lightbulb size={12}/></button><div><strong className="block text-sm text-amber-950">Drag a bulb into the section</strong><span className="text-xs text-amber-800">Drop it at the point where additional information belongs.</span></div></div>}
        <CalloutList callouts={timelineData?.section_callouts || []} provisionId={timelineData?.section?.id} adminMode={adminMode} onChanged={() => setTimelineRefresh((value) => value + 1)} glossary={glossary} asOfDate={asOfDate}/>
        {subsectionGroups.length > 0 ? (
          subsectionGroups.map((group, groupIndex) => (
            <div key={`subsection-group-${normalizeIdentifier(group.identifier)}-${groupIndex}`}>
              {group.current.map((subsection, index) => (
                <SubsectionRenderer
                  key={`subsec-${section.section_number}-${subsection.subsection_number}-${index}`}
                  subsection={subsection}
                  historicalVersions={group.historical}
                  onOpenAmendment={openAmendment}
                  onOpenDocument={setActiveDocuments}
                  editing={adminMode && adminEditing}
                  onTextChange={(id, value) => setAdminChanges((changes) => ({ ...changes, [id]: value }))}
                  draftTexts={adminChanges}
                  adminMode={adminMode}
                  onCalloutsChanged={() => setTimelineRefresh((value) => value + 1)}
                  glossary={glossary}
                  asOfDate={asOfDate}
                />
              ))}
              {!group.current.length && group.historical[0]?.text && <div className="mb-4 border-l-2 border-gray-200 pl-3 sm:pl-4"><div className="flex items-start gap-2"><span className="font-bold text-gray-700">{group.historical[0].subsection_number}</span><CoalescedAmendment currentText="" earlier={group.historical[0]} onOpenAmendment={openAmendment} glossary={glossary}/></div></div>}
            </div>
          ))
        ) : (
          (adminMode && adminEditing && timelineData?.section?.id) ? <RichTextEditor value={adminChanges[timelineData.section.id] ?? timelineData.section.current_text ?? ""} onChange={(value) => setAdminChanges((changes) => ({ ...changes, [timelineData.section.id]: value }))} className="min-h-32"/> : <p className="text-[15px] leading-7 text-gray-900 sm:text-base"><AnchoredText text={timelineData?.section?.current_text || ""} callouts={timelineData?.section_callouts || []} provisionId={timelineData?.section?.id} adminMode={adminMode} onOpenBulb={setActiveSectionBulb} glossary={glossary}/></p>
        )}
        {subsectionGroups.length > 0 && <div className="mt-4 border-t border-slate-200 pt-3"><AnchoredText text="" callouts={timelineData?.section_callouts || []} provisionId={timelineData?.section?.id} adminMode={adminMode} onOpenBulb={setActiveSectionBulb} glossary={glossary}/></div>}
        </>}
        {categorizedDocuments[workspaceTab] && <DocumentCategoryPanel relationships={categorizedDocuments[workspaceTab]} label={workspaceTab} targetProvisionId={timelineData?.section?.id} adminMode={adminMode} onCountChange={(delta) => setDocumentCountAdjustments((current) => ({ ...current, [workspaceTab]: (current[workspaceTab] || 0) + delta }))} onChanged={() => setTimelineRefresh((value) => value + 1)} onOpen={setActiveDocuments}/>} 
        {workspaceTab === "Actionable Insights" && (insightCallouts.length > 0 ? (
          <CalloutList callouts={insightCallouts} provisionId={timelineData?.section?.id} adminMode={adminMode} onChanged={() => setTimelineRefresh((value) => value + 1)} glossary={glossary} asOfDate={asOfDate}/>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-5 py-10 text-center">
            <Lightbulb className="mx-auto mb-3 text-slate-400" size={26}/>
            <h4 className="font-bold text-slate-800">No actionable insights for this section</h4>
            <p className="mt-1 text-sm text-slate-500">Actionable guidance will appear here when it is added.</p>
            {adminMode && <CalloutList callouts={[]} provisionId={timelineData?.section?.id} adminMode onChanged={() => setTimelineRefresh((value) => value + 1)} glossary={glossary} asOfDate={asOfDate}/>} 
          </div>
        ))}
        </div>
      </article>

      {pdfSources.length > 0 && (
        <AmendmentPdfModal sources={pdfSources} onClose={() => setPdfSources([])} />
      )}
      {activeDocuments && (
        <CorpusDocumentModal context={activeDocuments} onClose={() => setActiveDocuments(null)} adminMode={adminMode} onChanged={() => setTimelineRefresh((value) => value + 1)} />
      )}
      {activeSectionBulb && <BulbNoteModal note={activeSectionBulb.note} provisionId={activeSectionBulb.provisionId} anchor={activeSectionBulb.anchor} adminMode={adminMode} onClose={() => setActiveSectionBulb(null)} onChanged={() => setTimelineRefresh((value) => value + 1)} glossary={glossary} asOfDate={asOfDate}/>} 
    </>
  );
};

export default SectionCard;
