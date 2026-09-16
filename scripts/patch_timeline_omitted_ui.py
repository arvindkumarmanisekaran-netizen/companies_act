#!/usr/bin/env python3
from pathlib import Path


def main() -> int:
    path = Path('frontend/src/components/SectionViewer.jsx')
    text = path.read_text()

    old = '''  const sectionSources = amendmentPdfSources(section.source_note);\n\n  return (\n'''
    new = '''  const sectionSources = amendmentPdfSources(section.source_note);\n  const timelineMeta = section.timeline || {};\n  const timelineMetadata = timelineMeta.metadata || {};\n  const isOmittedAtSelectedDate = String(section.status || "").toLowerCase() === "omitted";\n  const omissionNote =\n    timelineMetadata.source_note ||\n    section.source_note ||\n    section.amendments?.[0]?.note ||\n    "";\n  const omissionEffectiveDate = timelineMetadata.effective_date || timelineMeta.valid_from;\n\n  return (\n'''
    if old not in text:
        raise SystemExit('SectionCard metadata anchor not found')
    text = text.replace(old, new, 1)

    old = '''        {section.historical && section.source_note && (\n          <p className="mb-4 break-words rounded-lg border border-red-200 bg-red-50 p-2.5 text-xs leading-relaxed text-red-800">\n            <strong>Amendment note:</strong> {section.source_note}\n          </p>\n        )}\n\n        {subsectionGroups.length > 0 ? (\n'''
    new = '''        {section.historical && section.source_note && (\n          <p className="mb-4 break-words rounded-lg border border-red-200 bg-red-50 p-2.5 text-xs leading-relaxed text-red-800">\n            <strong>Amendment note:</strong> {section.source_note}\n          </p>\n        )}\n\n        {isOmittedAtSelectedDate && (\n          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm leading-relaxed text-red-900">\n            <div className="font-bold">Omitted as of the selected date</div>\n            {omissionEffectiveDate && (\n              <div className="mt-1 text-xs font-semibold text-red-800">\n                Effective from {omissionEffectiveDate}\n              </div>\n            )}\n            {omissionNote && (\n              <p className="mt-2 break-words text-xs text-red-800">{omissionNote}</p>\n            )}\n          </div>\n        )}\n\n        {subsectionGroups.length > 0 ? (\n'''
    if old not in text:
        raise SystemExit('SectionCard omission-callout anchor not found')
    text = text.replace(old, new, 1)

    old = '''        ) : (\n          <p className="italic text-gray-500">No subsections available.</p>\n        )}\n'''
    new = '''        ) : isOmittedAtSelectedDate ? (\n          <p className="text-sm font-medium text-red-700">\n            No operative wording applies because this section stood omitted on this date.\n          </p>\n        ) : (\n          <p className="italic text-gray-500">No date-supported provision text is available for this section.</p>\n        )}\n'''
    if old not in text:
        raise SystemExit('SectionCard empty-state anchor not found')
    text = text.replace(old, new, 1)

    path.write_text(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
