#!/usr/bin/env python3

import asyncio
import csv
import re
import ssl
import urllib.request

from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://egazette.gov.in/"

FROM_DATE = "01-Jan-2013"
TO_DATE = datetime.now().strftime("%d-%b-%Y")

OUTPUT_DIR = Path("egazette_debug")
DOWNLOAD_DIR = Path("egazette_mca_pdfs")
MANIFEST_FILE = DOWNLOAD_DIR / "downloads.csv"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

PDF_SELECTOR = 'input[type="image"]' '[id^="gvGazetteList_imgbtndownload_"]'


# ============================================================
# RESULT COLUMNS
# ============================================================

RESULT_FIELDS = [
    "S. No.",
    "Ministry / Organization",
    "Department",
    "Office",
    "Subject",
    "Category",
    "Part & Section",
    "Issue Date",
    "Publish Date",
    "Gazette ID",
]


HEADER_ALIASES = {
    "s. no.": {
        "s. no.",
        "s.no.",
        "s.no",
        "s. no",
        "s no",
        "sno",
        "serial no",
        "serial no.",
        "serial number",
        "sr no",
        "sr. no.",
        "sr.no.",
    },
    "ministry / organization": {
        "ministry / organization",
        "ministry/organization",
        "ministry / organisation",
        "ministry/organisation",
        "ministry organization",
        "ministry organisation",
        "ministry",
    },
    "department": {
        "department",
    },
    "office": {
        "office",
    },
    "subject": {
        "subject",
    },
    "category": {
        "category",
    },
    "part & section": {
        "part & section",
        "part and section",
        "part/section",
        "part &section",
        "part section",
    },
    "issue date": {
        "issue date",
        "date of issue",
        "issue date of notification",
    },
    "publish date": {
        "publish date",
        "publication date",
        "date of publication",
        "published date",
    },
    "gazette id": {
        "gazette id",
        "gazette id.",
        "gazetteid",
        "gazette no",
        "gazette no.",
    },
}


# ============================================================
# PAGE UTILITIES
# ============================================================


async def wait_for_page_stable(
    page,
    extra_ms=1000,
):
    try:
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=20000,
        )
    except Exception:
        pass

    try:
        await page.wait_for_load_state(
            "load",
            timeout=10000,
        )
    except Exception:
        pass

    await page.wait_for_timeout(extra_ms)


async def save_debug(
    page,
    name,
):
    safe_name = re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        name,
    )

    try:
        await page.screenshot(
            path=str(OUTPUT_DIR / f"{safe_name}.png"),
            full_page=True,
        )

    except Exception as exc:
        print(
            "Screenshot error:",
            repr(exc),
        )

    for index, frame in enumerate(page.frames):
        try:
            html = await frame.content()

            (OUTPUT_DIR / f"{safe_name}_frame_{index}.html").write_text(
                html,
                encoding="utf-8",
            )

        except Exception:
            pass

    print(f"Debug snapshot saved: {name}")


async def find_frame_with_selector(
    page,
    selector,
):
    for index, frame in enumerate(page.frames):
        try:
            locator = frame.locator(selector)

            if await locator.count() > 0:
                return (
                    frame,
                    locator.first,
                )

        except Exception:
            pass

    return (
        None,
        None,
    )


# ============================================================
# SESSION
# ============================================================


def extract_session_token(
    url,
):
    match = re.search(
        r"/\(S\(([^)]+)\)\)/",
        url,
        re.I,
    )

    if not match:
        return None

    return match.group(1)


async def wait_for_session_token(
    page,
    timeout_seconds=30,
):
    print()
    print("Waiting for eGazette server session token...")

    loop = asyncio.get_running_loop()

    start = loop.time()

    previous_url = None

    while True:
        current_url = page.url

        if current_url != previous_url:
            print(
                "  URL:",
                current_url,
            )

            previous_url = current_url

        token = extract_session_token(current_url)

        if token:
            print()
            print("=" * 78)
            print("SESSION TOKEN ACQUIRED")
            print("=" * 78)

            print(
                "Token:",
                token,
            )

            print(
                "URL  :",
                page.url,
            )

            print("=" * 78)

            return token

        if loop.time() - start >= timeout_seconds:
            raise RuntimeError("Timed out waiting for " "eGazette ASP.NET session token.")

        await page.wait_for_timeout(500)


# ============================================================
# OPEN SEARCH MENU
# ============================================================


async def click_search(
    page,
):
    print()
    print("Opening Search...")

    await wait_for_page_stable(
        page,
        extra_ms=1000,
    )

    for frame_index, frame in enumerate(page.frames):
        search = frame.locator("#sgzt")

        if await search.count() == 0:
            continue

        control = search.first

        print(f"  Search found " f"in frame #{frame_index}")

        before_url = page.url

        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=30000,
            ):
                await control.click()

        except PlaywrightTimeoutError:
            print("  No conventional navigation event.")

        except Exception as exc:
            print(
                "  Normal Search click failed:",
                repr(exc),
            )

            await control.click(force=True)

        await wait_for_page_stable(
            page,
            extra_ms=2500,
        )

        print(
            "  Before:",
            before_url,
        )

        print(
            "  After :",
            page.url,
        )

        if re.search(
            r"SearchMenu\.aspx",
            page.url,
            re.I,
        ):
            print("  Search Menu loaded.")

            return

        # ASP.NET can complete navigation slightly later.
        for _ in range(10):
            await page.wait_for_timeout(500)

            if re.search(
                r"SearchMenu\.aspx",
                page.url,
                re.I,
            ):
                print("  Search Menu loaded.")

                return

        print("  SearchMenu.aspx URL was not " "confirmed, continuing with DOM detection.")

        return

    raise RuntimeError("Could not find eGazette Search control.")


# ============================================================
# SEARCH BY MINISTRY
# ============================================================


async def click_search_by_ministry(
    page,
):
    print()
    print("Opening Search by Ministry...")

    await wait_for_page_stable(
        page,
        extra_ms=1500,
    )

    print(
        "  Current URL:",
        page.url,
    )

    # ========================================================
    # METHOD 1
    # Search every anchor using all useful attributes.
    # ========================================================

    for frame_index, frame in enumerate(page.frames):
        try:
            links = frame.locator("a")

            link_count = await links.count()

            print(f"  Frame #{frame_index}: " f"{link_count} link(s)")

            for index in range(link_count):
                link = links.nth(index)

                try:
                    text = (await link.inner_text()).strip()

                except Exception:
                    text = ""

                href = await link.get_attribute("href") or ""

                onclick = await link.get_attribute("onclick") or ""

                title = await link.get_attribute("title") or ""

                element_id = await link.get_attribute("id") or ""

                combined = " ".join(
                    [
                        text,
                        href,
                        onclick,
                        title,
                        element_id,
                    ]
                )

                if not re.search(
                    r"SearchMinistry|" r"Search\s*by\s*Ministry|" r"Ministry\s*Search",
                    combined,
                    re.I,
                ):
                    continue

                print()
                print("  Search by Ministry " "candidate found:")

                print(
                    "    Frame:",
                    frame_index,
                )

                print(
                    "    Text :",
                    repr(text),
                )

                print(
                    "    ID   :",
                    repr(element_id),
                )

                print(
                    "    Href :",
                    repr(href),
                )

                before_url = page.url

                try:
                    await link.scroll_into_view_if_needed()

                except Exception:
                    pass

                try:
                    await link.click(
                        timeout=10000,
                    )

                except Exception as normal_exc:
                    print(
                        "    Normal click failed:",
                        repr(normal_exc),
                    )

                    try:
                        await link.click(
                            force=True,
                            timeout=10000,
                        )

                    except Exception as force_exc:
                        print(
                            "    Force click failed:",
                            repr(force_exc),
                        )

                        continue

                await wait_for_page_stable(
                    page,
                    extra_ms=2000,
                )

                print(
                    "    Before:",
                    before_url,
                )

                print(
                    "    After :",
                    page.url,
                )

                if re.search(
                    r"SearchMinistry\.aspx",
                    page.url,
                    re.I,
                ):
                    dynamic_id = re.search(
                        r"[?&]id=(\d+)",
                        page.url,
                        re.I,
                    )

                    if dynamic_id:
                        print(
                            "    Dynamic ID:",
                            dynamic_id.group(1),
                        )

                    print("  Search by Ministry opened.")

                    return

        except Exception as exc:
            print(
                f"  Frame #{frame_index} " f"inspection failed:",
                repr(exc),
            )

    # ========================================================
    # METHOD 2
    # Visible text search.
    # ========================================================

    print()
    print("  Trying visible-text fallback...")

    for frame_index, frame in enumerate(page.frames):
        try:
            locator = frame.get_by_text(
                re.compile(
                    r"Search\s*by\s*Ministry",
                    re.I,
                )
            )

            count = await locator.count()

            for index in range(count):
                element = locator.nth(index)

                try:
                    if not await element.is_visible():
                        continue

                except Exception:
                    continue

                try:
                    text = (await element.inner_text()).strip()

                except Exception:
                    text = ""

                print(
                    "  Visible candidate " f"in frame #{frame_index}:",
                    repr(text),
                )

                try:
                    await element.scroll_into_view_if_needed()

                except Exception:
                    pass

                try:
                    await element.click(
                        timeout=10000,
                    )

                except Exception:
                    try:
                        await element.click(
                            force=True,
                            timeout=10000,
                        )

                    except Exception:
                        continue

                await wait_for_page_stable(
                    page,
                    extra_ms=2000,
                )

                if re.search(
                    r"SearchMinistry\.aspx",
                    page.url,
                    re.I,
                ):
                    dynamic_id = re.search(
                        r"[?&]id=(\d+)",
                        page.url,
                        re.I,
                    )

                    if dynamic_id:
                        print(
                            "  Dynamic ID:",
                            dynamic_id.group(1),
                        )

                    return

        except Exception:
            pass

    # ========================================================
    # METHOD 3
    # Generic elements for old ASP.NET markup.
    # ========================================================

    print()
    print("  Trying generic element fallback...")

    for frame_index, frame in enumerate(page.frames):
        try:
            candidates = frame.locator("""
                a,
                button,
                input,
                span,
                div,
                td
                """)

            count = await candidates.count()

            for index in range(count):
                element = candidates.nth(index)

                try:
                    text = (await element.inner_text()).strip()

                except Exception:
                    text = ""

                value = await element.get_attribute("value") or ""

                title = await element.get_attribute("title") or ""

                href = await element.get_attribute("href") or ""

                onclick = await element.get_attribute("onclick") or ""

                combined = " ".join(
                    [
                        text,
                        value,
                        title,
                        href,
                        onclick,
                    ]
                )

                if not re.search(
                    r"Search\s*by\s*Ministry|" r"SearchMinistry",
                    combined,
                    re.I,
                ):
                    continue

                try:
                    if not await element.is_visible():
                        continue

                except Exception:
                    continue

                print(
                    f"  Generic candidate " f"in frame #{frame_index}:",
                    repr(combined[:300]),
                )

                try:
                    await element.click(
                        timeout=10000,
                    )

                except Exception:
                    try:
                        await element.click(
                            force=True,
                            timeout=10000,
                        )

                    except Exception:
                        continue

                await wait_for_page_stable(
                    page,
                    extra_ms=2000,
                )

                if re.search(
                    r"SearchMinistry\.aspx",
                    page.url,
                    re.I,
                ):
                    dynamic_id = re.search(
                        r"[?&]id=(\d+)",
                        page.url,
                        re.I,
                    )

                    if dynamic_id:
                        print(
                            "  Dynamic ID:",
                            dynamic_id.group(1),
                        )

                    return

        except Exception:
            pass

    # ========================================================
    # DEBUG DUMP
    # ========================================================

    await save_debug(
        page,
        "search_by_ministry_not_found",
    )

    print()
    print("Available links:")

    for frame_index, frame in enumerate(page.frames):
        try:
            links = frame.locator("a")

            for index in range(await links.count()):
                link = links.nth(index)

                try:
                    text = (await link.inner_text()).strip()

                except Exception:
                    text = ""

                href = await link.get_attribute("href") or ""

                element_id = await link.get_attribute("id") or ""

                if text or href or element_id:
                    print(
                        f"  Frame {frame_index}, "
                        f"link {index}: "
                        f"text={text!r} "
                        f"id={element_id!r} "
                        f"href={href!r}"
                    )

        except Exception:
            pass

    raise RuntimeError("Search by Ministry not found.")


# ============================================================
# SEARCH FORM
# ============================================================


async def find_search_form_frame(
    page,
):
    print()
    print("Locating Ministry search form...")

    frame, _ = await find_frame_with_selector(
        page,
        "#rdb_Option_0",
    )

    if frame:
        return frame

    for frame in page.frames:
        selects = frame.locator("select")

        for index in range(await selects.count()):
            try:
                options = await selects.nth(index).locator("option").all_text_contents()

            except Exception:
                continue

            if any("Ministry of Corporate Affairs" in option for option in options):
                return frame

    raise RuntimeError("Ministry search form not found.")


async def select_mca(
    frame,
):
    print()
    print("Selecting Ministry of Corporate Affairs...")

    selects = frame.locator("select")

    for index in range(await selects.count()):
        dropdown = selects.nth(index)

        try:
            options = await dropdown.locator("option").all_text_contents()

        except Exception:
            continue

        for option in options:
            option_text = option.strip()

            if "Ministry of Corporate Affairs" not in option_text:
                continue

            await dropdown.select_option(label=option_text)

            print("  MCA selected.")

            return

    raise RuntimeError("Ministry of Corporate Affairs " "option not found.")


async def select_date_wise(
    frame,
):
    print("Selecting Date Wise...")

    radio = frame.locator("#rdb_Option_1")

    if await radio.count() == 0:
        raise RuntimeError("Date Wise control not found.")

    await radio.check(force=True)

    await frame.page.wait_for_timeout(750)


async def set_input_value(
    locator,
    value,
):
    await locator.evaluate(
        """
        (element, value) => {
            element.value = value;

            element.dispatchEvent(
                new Event(
                    "input",
                    {bubbles: true}
                )
            );

            element.dispatchEvent(
                new Event(
                    "change",
                    {bubbles: true}
                )
            );

            element.dispatchEvent(
                new Event(
                    "blur",
                    {bubbles: true}
                )
            );
        }
        """,
        value,
    )


async def enter_dates(
    page,
):
    print()
    print("Setting notification dates:")

    print(
        "  From:",
        FROM_DATE,
    )

    print(
        "  To  :",
        TO_DATE,
    )

    _, from_input = await find_frame_with_selector(
        page,
        "#txtDateFrom",
    )

    _, to_input = await find_frame_with_selector(
        page,
        "#txtDateTo",
    )

    if from_input is None:
        raise RuntimeError("txtDateFrom not found.")

    if to_input is None:
        raise RuntimeError("txtDateTo not found.")

    await set_input_value(
        from_input,
        FROM_DATE,
    )

    await set_input_value(
        to_input,
        TO_DATE,
    )

    actual_from = await from_input.input_value()

    actual_to = await to_input.input_value()

    print(
        "  Actual From:",
        actual_from,
    )

    print(
        "  Actual To  :",
        actual_to,
    )

    if actual_from != FROM_DATE:
        raise RuntimeError("Could not set From date.")

    if actual_to != TO_DATE:
        raise RuntimeError("Could not set To date.")


async def submit_search(
    page,
):
    print()
    print("Submitting search...")

    for frame_index, frame in enumerate(page.frames):
        button = frame.locator("#ImgSubmitDetails")

        if await button.count() == 0:
            continue

        print(f"  Submit found " f"in frame #{frame_index}")

        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=30000,
            ):
                await button.first.click(
                    position={
                        "x": 10,
                        "y": 10,
                    }
                )

        except PlaywrightTimeoutError:
            pass

        except Exception:
            await button.first.click(force=True)

        await wait_for_page_stable(
            page,
            extra_ms=3000,
        )

        print(
            "  Results URL:",
            page.url,
        )

        return

    raise RuntimeError("Search Submit control not found.")


# ============================================================
# RESULTS
# ============================================================


async def find_pdf_frame(
    page,
):
    for index, frame in enumerate(page.frames):
        controls = frame.locator(PDF_SELECTOR)

        count = await controls.count()

        if count:
            return (
                index,
                frame,
                count,
            )

    return (
        None,
        None,
        0,
    )


# ============================================================
# METADATA
# ============================================================


def normalize_header(
    value,
):
    value = value or ""

    value = value.replace("\xa0", " ")

    value = (
        re.sub(
            r"\s+",
            " ",
            value,
        )
        .strip()
        .lower()
    )

    value = value.replace(
        "organisation",
        "organization",
    )

    return value


def canonical_header(
    value,
):
    normalized = normalize_header(value)

    for canonical, aliases in HEADER_ALIASES.items():
        if normalized in aliases:
            return canonical

    return normalized


async def extract_result_row_metadata(
    button,
):
    data = await button.evaluate("""
        (button) => {
            const clean = text =>
                (text || "")
                    .replace(/\\u00a0/g, " ")
                    .replace(/\\s+/g, " ")
                    .trim();

            const row =
                button.closest("tr");

            if (!row) {
                return {
                    headers: [],
                    cells: []
                };
            }

            const table =
                row.closest("table");

            if (!table) {
                return {
                    headers: [],
                    cells: []
                };
            }

            const rows =
                Array.from(
                    table.querySelectorAll("tr")
                );

            const cells =
                Array.from(
                    row.children
                ).map(
                    cell =>
                        clean(cell.innerText)
                );

            const currentIndex =
                rows.indexOf(row);

            let headers = [];

            for (
                let i = 0;
                i < currentIndex;
                i++
            ) {
                const children =
                    Array.from(
                        rows[i].children
                    );

                if (!children.length) {
                    continue;
                }

                const texts =
                    children.map(
                        element =>
                            clean(
                                element.innerText
                            )
                    );

                const thCount =
                    children.filter(
                        element =>
                            element.tagName
                                .toLowerCase()
                            === "th"
                    ).length;

                if (
                    thCount
                    &&
                    texts.length
                    >= headers.length
                ) {
                    headers = texts;
                }
            }

            if (!headers.length) {
                for (
                    let i = 0;
                    i < currentIndex;
                    i++
                ) {
                    const texts =
                        Array.from(
                            rows[i].children
                        ).map(
                            element =>
                                clean(
                                    element.innerText
                                )
                        );

                    const joined =
                        texts.join(" ")
                            .toLowerCase();

                    if (
                        joined.includes("subject")
                        &&
                        (
                            joined.includes("gazette")
                            ||
                            joined.includes("publish")
                        )
                    ) {
                        headers = texts;
                    }
                }
            }

            return {
                headers,
                cells
            };
        }
        """)

    headers = data.get(
        "headers",
        [],
    )

    cells = data.get(
        "cells",
        [],
    )

    metadata = {field: "" for field in RESULT_FIELDS}

    for index, header in enumerate(headers):
        if index >= len(cells):
            break

        canonical = canonical_header(header)

        for field in RESULT_FIELDS:
            if canonical == canonical_header(field):
                metadata[field] = cells[index]

    # S.No fallback
    if not metadata["S. No."] and cells:
        first_cell = cells[0].strip()

        if re.fullmatch(
            r"\d+",
            first_cell,
        ):
            metadata["S. No."] = first_cell

    print()
    print("  Metadata:")

    for field in RESULT_FIELDS:
        print(f"    {field}: " f"{metadata[field]!r}")

    return metadata


# ============================================================
# FILE NAME
# ============================================================


def sanitize_filename_component(
    value,
):
    value = value or ""

    value = value.replace("\xa0", " ")

    value = re.sub(
        r"[\r\n\t]+",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    value = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "-",
        value,
    )

    value = re.sub(
        r"-{2,}",
        "-",
        value,
    )

    value = value.strip(" .-_")

    return value or "NA"


def truncate_utf8(
    value,
    max_bytes,
):
    raw = value.encode("utf-8")

    if len(raw) <= max_bytes:
        return value

    raw = raw[:max_bytes]

    while raw:
        try:
            return raw.decode("utf-8").rstrip() + "…"

        except UnicodeDecodeError:
            raw = raw[:-1]

    return ""


def build_metadata_filename(
    metadata,
    original_pdf,
    max_bytes=240,
):
    original_stem = sanitize_filename_component(Path(original_pdf).stem)

    values = [
        sanitize_filename_component(
            metadata.get(
                field,
                "",
            )
        )
        for field in RESULT_FIELDS
    ]

    separator = " - "

    suffix = f" ({original_stem}).pdf"

    def compose():
        return separator.join(values) + suffix

    if len(compose().encode("utf-8")) <= max_bytes:
        return compose()

    # Prefer truncating descriptive text,
    # not S.No/date/Gazette ID.
    truncatable_fields = [
        "Subject",
        "Office",
        "Department",
        "Ministry / Organization",
        "Category",
        "Part & Section",
    ]

    truncatable_indices = [RESULT_FIELDS.index(field) for field in truncatable_fields]

    while len(compose().encode("utf-8")) > max_bytes:
        candidates = [
            index for index in truncatable_indices if len(values[index].encode("utf-8")) > 12
        ]

        if not candidates:
            break

        largest = max(
            candidates,
            key=lambda index: len(values[index].encode("utf-8")),
        )

        current_size = len(values[largest].encode("utf-8"))

        values[largest] = truncate_utf8(
            values[largest],
            max(
                12,
                current_size - 8,
            ),
        )

    filename = compose()

    if len(filename.encode("utf-8")) > max_bytes:
        available = max_bytes - len(suffix.encode("utf-8"))

        body = separator.join(values)

        filename = (
            truncate_utf8(
                body,
                available,
            )
            + suffix
        )

    return filename


def build_pdf_destination(
    pdf_url,
    metadata,
):
    original_pdf = Path(urlparse(pdf_url).path).name

    filename = build_metadata_filename(
        metadata,
        original_pdf,
    )

    return DOWNLOAD_DIR / filename


# ============================================================
# PHYSICAL DOWNLOAD FOLDER DUPLICATE CHECK
# ============================================================


def load_existing_original_pdfs_from_folder():
    originals = set()

    if not DOWNLOAD_DIR.exists():
        return originals

    for path in DOWNLOAD_DIR.glob("*.pdf"):
        filename = path.name

        # New format:
        #
        # .... (274201).pdf
        #
        # Old duplicate:
        #
        # .... (274201) [2].pdf

        match = re.search(
            r"\(([^()]+)\)" r"(?:\s*\[\d+\])?" r"\.pdf$",
            filename,
            re.I,
        )

        if match:
            original_stem = match.group(1).strip()

            if original_stem:
                originals.add((original_stem + ".pdf").lower())

            continue

        # Raw original:
        #
        # 274201.pdf

        raw_match = re.fullmatch(
            r"(\d+)\.pdf",
            filename,
            re.I,
        )

        if raw_match:
            originals.add((raw_match.group(1) + ".pdf").lower())

    return originals


# ============================================================
# SSL FALLBACK
# ============================================================


def urllib_fetch_pdf_insecure(
    url,
    referer,
    user_agent,
):
    parsed = urlparse(url)

    host = (parsed.hostname or "").lower()

    if host not in {
        "egazette.gov.in",
        "www.egazette.gov.in",
    }:
        raise RuntimeError(f"Unexpected insecure " f"download host: {host}")

    ssl_context = ssl._create_unverified_context()

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Referer": referer,
            "Accept": "application/pdf," "application/octet-stream," "*/*",
            "Connection": "close",
        },
    )

    with urllib.request.urlopen(
        request,
        context=ssl_context,
        timeout=90,
    ) as response:
        return (
            getattr(
                response,
                "status",
                200,
            ),
            response.headers.get(
                "Content-Type",
                "",
            ),
            response.read(),
        )


async def fetch_pdf_bytes(
    context,
    viewer_page,
    pdf_url,
):
    # ========================================================
    # Playwright request first
    # ========================================================

    for attempt in range(
        1,
        4,
    ):
        try:
            print(f"  Playwright PDF fetch " f"{attempt}/3...")

            response = await context.request.get(
                pdf_url,
                timeout=90000,
                fail_on_status_code=False,
                headers={
                    "Referer": viewer_page.url,
                },
            )

            print(
                "  HTTP:",
                response.status,
            )

            if not response.ok:
                raise RuntimeError(f"HTTP {response.status}")

            body = await response.body()

            if body and body.startswith(b"%PDF"):
                return (
                    body,
                    "playwright",
                )

            raise RuntimeError("Response is not a PDF.")

        except Exception as exc:
            print(
                "  Playwright PDF fetch failed:",
                repr(exc),
            )

            if attempt < 3:
                await asyncio.sleep(attempt * 1.5)

    # ========================================================
    # eGazette TLS workaround
    # ========================================================

    print("  Using eGazette TLS fallback...")

    user_agent = await viewer_page.evaluate("() => navigator.userAgent")

    status, content_type, body = await asyncio.to_thread(
        urllib_fetch_pdf_insecure,
        pdf_url,
        viewer_page.url,
        user_agent,
    )

    print(
        "  Fallback HTTP:",
        status,
    )

    print(
        "  Content-Type:",
        content_type,
    )

    if not body or not body.startswith(b"%PDF"):
        raise RuntimeError("TLS fallback did not " "return a valid PDF.")

    return (
        body,
        "urllib-tls-fallback",
    )


# ============================================================
# ViewPDF.aspx -> REAL PDF
# ============================================================


async def save_pdf_from_viewer(
    context,
    viewer_page,
    metadata,
    existing_original_pdfs,
):
    print(
        "  Viewer URL:",
        viewer_page.url,
    )

    iframe = viewer_page.locator("#framePDFDisplay")

    await iframe.wait_for(
        state="attached",
        timeout=30000,
    )

    src = await iframe.get_attribute("src")

    if not src:
        raise RuntimeError("framePDFDisplay contains no src.")

    pdf_url = urljoin(
        viewer_page.url,
        src,
    )

    original_pdf = Path(urlparse(pdf_url).path).name

    if not re.fullmatch(
        r".+\.pdf",
        original_pdf,
        re.I,
    ):
        raise RuntimeError("Could not determine original " f"PDF filename from {pdf_url}")

    original_key = original_pdf.lower()

    print(
        "  Actual PDF URL:",
        pdf_url,
    )

    print(
        "  Original PDF:",
        original_pdf,
    )

    # ========================================================
    # DUPLICATE CHECK BEFORE DOWNLOAD
    # ========================================================

    if original_key in existing_original_pdfs:
        print(
            "  DUPLICATE - ALREADY EXISTS:",
            original_pdf,
        )

        return {
            "duplicate": True,
            "original_pdf": original_pdf,
            "pdf_url": pdf_url,
            "destination": None,
            "bytes": 0,
            "method": "folder-duplicate-skip",
        }

    body, method = await fetch_pdf_bytes(
        context,
        viewer_page,
        pdf_url,
    )

    # Re-scan folder immediately before saving.
    existing_original_pdfs.update(load_existing_original_pdfs_from_folder())

    if original_key in existing_original_pdfs:
        print("  Duplicate found during " "folder refresh. Skipping.")

        return {
            "duplicate": True,
            "original_pdf": original_pdf,
            "pdf_url": pdf_url,
            "destination": None,
            "bytes": 0,
            "method": "folder-duplicate-skip",
        }

    destination = build_pdf_destination(
        pdf_url,
        metadata,
    )

    if destination.exists():
        raise RuntimeError(
            "Destination already exists but "
            "original identifier was not "
            "detected:\n"
            f"{destination}"
        )

    destination.write_bytes(body)

    existing_original_pdfs.add(original_key)

    print(
        "  SAVED:",
        destination.name,
    )

    print(
        "  Size:",
        f"{len(body) / 1024:.1f} KB",
    )

    return {
        "duplicate": False,
        "original_pdf": original_pdf,
        "pdf_url": pdf_url,
        "destination": destination,
        "bytes": len(body),
        "method": method,
    }


# ============================================================
# MANIFEST
# ============================================================

MANIFEST_FIELDS = [
    "result_page",
    "row",
    "s_no",
    "ministry_organization",
    "department",
    "office",
    "subject",
    "category",
    "part_section",
    "issue_date",
    "publish_date",
    "gazette_id",
    "control_id",
    "control_name",
    "pdf_url",
    "original_pdf",
    "filename",
    "bytes",
    "download_method",
    "status",
]


def make_manifest_row(
    result_page,
    row,
    metadata,
    control_id,
    control_name,
):
    return {
        "result_page": result_page,
        "row": row,
        "s_no": metadata.get(
            "S. No.",
            "",
        ),
        "ministry_organization": metadata.get(
            "Ministry / Organization",
            "",
        ),
        "department": metadata.get(
            "Department",
            "",
        ),
        "office": metadata.get(
            "Office",
            "",
        ),
        "subject": metadata.get(
            "Subject",
            "",
        ),
        "category": metadata.get(
            "Category",
            "",
        ),
        "part_section": metadata.get(
            "Part & Section",
            "",
        ),
        "issue_date": metadata.get(
            "Issue Date",
            "",
        ),
        "publish_date": metadata.get(
            "Publish Date",
            "",
        ),
        "gazette_id": metadata.get(
            "Gazette ID",
            "",
        ),
        "control_id": control_id,
        "control_name": control_name,
        "pdf_url": "",
        "original_pdf": "",
        "filename": "",
        "bytes": "",
        "download_method": "",
        "status": "",
    }


def save_manifest(
    rows,
):
    with MANIFEST_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=MANIFEST_FIELDS,
            extrasaction="ignore",
        )

        writer.writeheader()

        writer.writerows(rows)


# ============================================================
# DOWNLOAD CURRENT RESULT PAGE
# ============================================================


async def download_current_page(
    page,
    result_page_number,
    manifest_rows,
    existing_original_pdfs,
):
    print()
    print("=" * 78)

    print(f"DOWNLOADING RESULT PAGE " f"{result_page_number}")

    print("=" * 78)

    _, frame, count = await find_pdf_frame(page)

    if frame is None:
        print("No PDF controls found.")

        return (
            0,
            0,
        )

    print(f"Found {count} PDF button(s).")

    context = page.context

    downloaded = 0
    duplicates = 0

    for index in range(count):
        row_number = index + 1

        print()
        print("-" * 78)

        print(f"PDF {row_number}/{count}")

        print("-" * 78)

        # DOM may have been rebuilt.
        _, frame, current_count = await find_pdf_frame(page)

        if frame is None:
            raise RuntimeError("Results table disappeared.")

        controls = frame.locator(PDF_SELECTOR)

        actual_count = await controls.count()

        if index >= actual_count:
            print("  Result control no longer exists.")

            continue

        button = controls.nth(index)

        metadata = await extract_result_row_metadata(button)

        control_id = await button.get_attribute("id") or ""

        control_name = await button.get_attribute("name") or ""

        print(
            "  ID  :",
            control_id,
        )

        print(
            "  Name:",
            control_name,
        )

        pages_before = set(context.pages)

        viewer_page = None

        row_record = make_manifest_row(
            result_page_number,
            row_number,
            metadata,
            control_id,
            control_name,
        )

        try:
            # =================================================
            # OPEN VIEWER
            # =================================================

            await button.click(
                position={
                    "x": 5,
                    "y": 5,
                }
            )

            await page.wait_for_timeout(1200)

            new_pages = [
                candidate_page
                for candidate_page in context.pages
                if candidate_page not in pages_before
            ]

            if new_pages:
                viewer_page = new_pages[-1]

                try:
                    await viewer_page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=20000,
                    )

                except Exception:
                    pass

                print("  ViewPDF opened " "in new tab.")

            elif "ViewPDF.aspx" in page.url:
                viewer_page = page

                print("  ViewPDF opened " "in current tab.")

            if viewer_page is None:
                raise RuntimeError("ViewPDF.aspx did not open.")

            # =================================================
            # SAVE / SKIP
            # =================================================

            result = await save_pdf_from_viewer(
                context,
                viewer_page,
                metadata,
                existing_original_pdfs,
            )

            if result["duplicate"]:
                duplicates += 1

                row_record.update(
                    {
                        "pdf_url": result["pdf_url"],
                        "original_pdf": result["original_pdf"],
                        "bytes": 0,
                        "download_method": result["method"],
                        "status": "duplicate-skipped",
                    }
                )

            else:
                downloaded += 1

                destination = result["destination"]

                row_record.update(
                    {
                        "pdf_url": result["pdf_url"],
                        "original_pdf": result["original_pdf"],
                        "filename": destination.name,
                        "bytes": result["bytes"],
                        "download_method": result["method"],
                        "status": "downloaded",
                    }
                )

            manifest_rows.append(row_record)

            save_manifest(manifest_rows)

            # =================================================
            # CLOSE VIEWER
            # =================================================

            if viewer_page is not page:
                await viewer_page.close()

                await page.bring_to_front()

                await page.wait_for_timeout(500)

            else:
                await page.go_back(wait_until="domcontentloaded")

                await wait_for_page_stable(
                    page,
                    extra_ms=1500,
                )

            # Verify results restored.
            _, result_frame, result_count = await find_pdf_frame(page)

            if result_frame is None or result_count == 0:
                raise RuntimeError("Result page could not " "be restored after PDF.")

        except Exception as exc:
            print(
                "  ERROR:",
                repr(exc),
            )

            row_record["status"] = f"ERROR: {exc}"

            manifest_rows.append(row_record)

            save_manifest(manifest_rows)

            try:
                if (
                    viewer_page is not None
                    and viewer_page is not page
                    and not viewer_page.is_closed()
                ):
                    await viewer_page.close()

                    await page.bring_to_front()

            except Exception:
                pass

            try:
                if "ViewPDF.aspx" in page.url:
                    await page.go_back(wait_until="domcontentloaded")

                    await wait_for_page_stable(
                        page,
                        extra_ms=1500,
                    )

            except Exception:
                pass

    print()
    print("=" * 78)

    print(
        "New PDFs downloaded:",
        downloaded,
    )

    print(
        "Duplicates skipped:",
        duplicates,
    )

    print(
        "Rows processed:",
        count,
    )

    print("=" * 78)

    return (
        downloaded,
        duplicates,
    )


# ============================================================
# ASK START PAGE
# ============================================================


def ask_start_page():
    while True:
        print()
        print("=" * 78)
        print("START PAGE")
        print("=" * 78)

        value = input(
            "Enter result page to start downloading from " "[press Enter for page 1]: "
        ).strip()

        if value == "":
            print("Starting from result page 1.")

            return 1

        try:
            page_number = int(value)

            if page_number < 1:
                raise ValueError

            print(f"Starting from result page " f"{page_number}.")

            return page_number

        except ValueError:
            print("Invalid page number. " "Enter a positive integer or " "press Enter for page 1.")


# ============================================================
# ASP.NET PAGER DISCOVERY
# ============================================================


async def discover_pagination(
    page,
):
    """
    Find real ASP.NET Page$N links.

    Avoids treating unrelated numeric links on the
    eGazette page as result pagination.
    """

    pages = {}

    for frame_index, frame in enumerate(page.frames):
        links = frame.locator("a")

        for index in range(await links.count()):
            link = links.nth(index)

            href = await link.get_attribute("href") or ""

            onclick = await link.get_attribute("onclick") or ""

            try:
                text = (await link.inner_text()).strip()

            except Exception:
                text = ""

            combined = " ".join(
                [
                    href,
                    onclick,
                    text,
                ]
            )

            match = re.search(
                r"Page\$(\d+)",
                combined,
                re.I,
            )

            if not match:
                continue

            number = int(match.group(1))

            pages[number] = {
                "frame_index": frame_index,
                "text": text,
                "href": href,
                "onclick": onclick,
            }

    return pages


# ============================================================
# CLICK REAL VISIBLE PAGER LINK
# ============================================================


async def click_visible_result_page(
    page,
    target_number,
):
    """
    Click the real ASP.NET page-number anchor.

    Important:
    __doPostBack is NEVER called manually.
    """

    for frame_index, frame in enumerate(page.frames):
        links = frame.locator("a")

        for index in range(await links.count()):
            link = links.nth(index)

            href = await link.get_attribute("href") or ""

            onclick = await link.get_attribute("onclick") or ""

            try:
                text = (await link.inner_text()).strip()

            except Exception:
                text = ""

            combined = " ".join(
                [
                    href,
                    onclick,
                    text,
                ]
            )

            match = re.search(
                r"Page\$(\d+)",
                combined,
                re.I,
            )

            if not match:
                continue

            page_number = int(match.group(1))

            if page_number != target_number:
                continue

            try:
                if not await link.is_visible():
                    continue

            except Exception:
                continue

            print(
                f"  Clicking visible pager " f"page {target_number} " f"in frame #{frame_index}..."
            )

            try:
                await link.click(force=True)

            except Exception as exc:
                print(
                    "  Pager click failed:",
                    repr(exc),
                )

                return False

            await wait_for_page_stable(
                page,
                extra_ms=1800,
            )

            _, result_frame, result_count = await find_pdf_frame(page)

            if result_frame is None or result_count == 0:
                print("  Results table disappeared " "after pager click.")

                return False

            return True

    return False


# ============================================================
# CLICK NEXT/PREVIOUS PAGER BLOCK CONTROL
# ============================================================


async def click_pager_block_control(
    page,
    forward=True,
):
    """
    Search for ASP.NET pager controls such as:

        ...
        …
        >
        >>
        Next

    or backward equivalents.
    """

    candidates = []

    for frame_index, frame in enumerate(page.frames):
        links = frame.locator("a")

        for index in range(await links.count()):
            link = links.nth(index)

            try:
                text = (await link.inner_text()).strip()

            except Exception:
                text = ""

            href = await link.get_attribute("href") or ""

            onclick = await link.get_attribute("onclick") or ""

            title = await link.get_attribute("title") or ""

            combined = " ".join(
                [
                    text,
                    href,
                    onclick,
                    title,
                ]
            )

            if forward:
                match = text in {
                    "...",
                    "…",
                    ">",
                    ">>",
                } or re.search(
                    r"Page\$Next|" r"\bNext\b",
                    combined,
                    re.I,
                )

            else:
                match = text in {
                    "<",
                    "<<",
                } or re.search(
                    r"Page\$Prev|" r"Page\$Previous|" r"\bPrev(?:ious)?\b",
                    combined,
                    re.I,
                )

            if not match:
                continue

            try:
                if not await link.is_visible():
                    continue

            except Exception:
                continue

            candidates.append(
                (
                    frame_index,
                    link,
                    text,
                )
            )

    if not candidates:
        return False

    if forward:
        candidate = candidates[-1]
    else:
        candidate = candidates[0]

    frame_index, link, text = candidate

    print(
        "  Clicking pager-block control:",
        repr(text),
    )

    try:
        await link.click(force=True)

    except Exception as exc:
        print(
            "  Pager-block click failed:",
            repr(exc),
        )

        return False

    await wait_for_page_stable(
        page,
        extra_ms=1800,
    )

    return True


# ============================================================
# NAVIGATE TO ARBITRARY RESULT PAGE
# ============================================================


async def click_result_page(
    page,
    target_number,
):
    """
    Navigate to target page entirely using the
    site's actual pager anchors.

    No direct JS __doPostBack invocation.
    """

    if target_number < 1:
        raise ValueError("Result page must be >= 1.")

    if target_number == 1:
        return True

    print()
    print(f"Navigating to result page " f"{target_number}...")

    seen_states = set()

    for step in range(
        1,
        300,
    ):
        pagination = await discover_pagination(page)

        numbers = sorted(pagination.keys())

        print(
            f"  Pager step {step}:",
            numbers,
        )

        if not numbers:
            print("  No ASP.NET result pager " "page links were detected.")

            return False

        # ====================================================
        # TARGET IS CURRENTLY VISIBLE
        # ====================================================

        if target_number in numbers:
            print(f"  Target page " f"{target_number} is visible.")

            success = await click_visible_result_page(
                page,
                target_number,
            )

            if success:
                print(f"  Reached result page " f"{target_number}.")

            return success

        state = tuple(numbers)

        if state in seen_states:
            print("  Pager state repeated.")

            return False

        seen_states.add(state)

        minimum = min(numbers)

        maximum = max(numbers)

        # ====================================================
        # TARGET IS AHEAD
        # ====================================================

        if target_number > maximum:
            print(f"  Target {target_number} " f"is beyond visible pages " f"{minimum}-{maximum}.")

            # First try highest page.
            success = await click_visible_result_page(
                page,
                maximum,
            )

            if not success:
                success = await click_pager_block_control(
                    page,
                    forward=True,
                )

            if not success:
                print("  Could not advance " "the result pager.")

                return False

            await wait_for_page_stable(
                page,
                extra_ms=1200,
            )

            updated = await discover_pagination(page)

            updated_numbers = sorted(updated.keys())

            # Clicking max page may only navigate to that
            # page and leave the same pager block.
            if updated_numbers == numbers and target_number not in updated_numbers:
                print(
                    "  Current pager block did " "not change; trying next " "pager-block control..."
                )

                advanced = await click_pager_block_control(
                    page,
                    forward=True,
                )

                if not advanced:
                    return False

            continue

        # ====================================================
        # TARGET IS BEHIND
        # ====================================================

        if target_number < minimum:
            print(f"  Target {target_number} " f"is before visible pages " f"{minimum}-{maximum}.")

            success = await click_pager_block_control(
                page,
                forward=False,
            )

            if not success:
                success = await click_visible_result_page(
                    page,
                    minimum,
                )

            if not success:
                print("  Could not move " "backward in pager.")

                return False

            continue

        # Target is numerically within min/max
        # but missing from actual Page$ links.
        print("  Target is within the pager " "range but no matching link exists.")

        return False

    print("  Pagination safety limit reached.")

    return False


# ============================================================
# PROCESS RESULT PAGES
# ============================================================


async def process_all_result_pages(
    page,
    start_page=1,
):
    manifest_rows = []

    existing_original_pdfs = load_existing_original_pdfs_from_folder()

    print()
    print("=" * 78)
    print("DOWNLOAD SCAN")
    print("=" * 78)

    print(
        "Unique original PDFs already present:",
        len(existing_original_pdfs),
    )

    print("=" * 78)

    current_page = start_page

    # ========================================================
    # JUMP TO START PAGE
    # ========================================================

    if start_page > 1:
        print()
        print("=" * 78)

        print(f"JUMPING TO START PAGE " f"{start_page}")

        print("=" * 78)

        success = await click_result_page(
            page,
            start_page,
        )

        if not success:
            raise RuntimeError(f"Could not navigate to " f"requested start page " f"{start_page}.")

    total_downloaded = 0
    total_duplicates = 0
    pages_processed = 0

    while True:
        print()
        print("#" * 78)

        print(f"PROCESSING RESULT PAGE " f"{current_page}")

        print("#" * 78)

        (
            downloaded,
            duplicates,
        ) = await download_current_page(
            page,
            current_page,
            manifest_rows,
            existing_original_pdfs,
        )

        total_downloaded += downloaded

        total_duplicates += duplicates

        pages_processed += 1

        next_page = current_page + 1

        print()
        print(f"Checking for result page " f"{next_page}...")

        success = await click_result_page(
            page,
            next_page,
        )

        if not success:
            print()
            print("No additional result " "page found.")

            break

        current_page = next_page

    save_manifest(manifest_rows)

    print()
    print("=" * 78)
    print("FINAL DOWNLOAD SUMMARY")
    print("=" * 78)

    print(
        "Started from page:",
        start_page,
    )

    print(
        "Last page processed:",
        current_page,
    )

    print(
        "Pages processed:",
        pages_processed,
    )

    print(
        "New PDFs downloaded:",
        total_downloaded,
    )

    print(
        "Duplicates skipped:",
        total_duplicates,
    )

    print(
        "Unique originals now present:",
        len(existing_original_pdfs),
    )

    print(
        "Download folder:",
        DOWNLOAD_DIR.resolve(),
    )

    print(
        "Manifest:",
        MANIFEST_FILE.resolve(),
    )

    print("=" * 78)


# ============================================================
# RESULT INSPECTION
# ============================================================


async def inspect_results(
    page,
):
    print()
    print("=" * 78)
    print("RESULT PAGE")
    print("=" * 78)

    print(
        "URL:",
        page.url,
    )

    _, _, pdf_count = await find_pdf_frame(page)

    print(
        "PDF controls:",
        pdf_count,
    )

    pagination = await discover_pagination(page)

    print(
        "Visible GridView pages:",
        sorted(pagination.keys()),
    )

    _, page_input = await find_frame_with_selector(
        page,
        "#txtPageNo",
    )

    if page_input is not None:
        print("txtPageNo detected.")

    print("=" * 78)


# ============================================================
# KEEP BROWSER OPEN
# ============================================================


async def keep_browser_open():
    print()
    print("=" * 78)
    print("BROWSER WILL REMAIN OPEN")
    print("=" * 78)

    print("Press Ctrl+C to exit.")

    await asyncio.Event().wait()


# ============================================================
# MAIN
# ============================================================


async def main():
    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--start-maximized",
                "--ignore-certificate-errors",
            ],
        )

        context = await browser.new_context(
            viewport=None,
            accept_downloads=True,
            ignore_https_errors=True,
        )

        page = await context.new_page()

        page.set_default_timeout(30000)

        try:
            # =================================================
            # 1. OPEN eGAZETTE
            # =================================================

            print()
            print("=" * 78)
            print("OPENING eGAZETTE")
            print("=" * 78)

            await page.goto(
                BASE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await wait_for_page_stable(
                page,
                extra_ms=1000,
            )

            # =================================================
            # 2. SESSION
            # =================================================

            token = await wait_for_session_token(page)

            # =================================================
            # 3. SEARCH
            # =================================================

            await click_search(page)

            # =================================================
            # 4. SEARCH BY MINISTRY
            # =================================================

            await click_search_by_ministry(page)

            # =================================================
            # 5. SEARCH FORM
            # =================================================

            search_frame = await find_search_form_frame(page)

            # =================================================
            # 6. MCA
            # =================================================

            await select_mca(search_frame)

            # =================================================
            # 7. DATE WISE
            # =================================================

            await select_date_wise(search_frame)

            # =================================================
            # 8. DATES
            # =================================================

            await enter_dates(page)

            print()
            print("=" * 78)
            print("SEARCH CONFIGURATION")
            print("=" * 78)

            print(
                "Session :",
                token,
            )

            print(
                "Ministry:",
                "Ministry of Corporate Affairs",
            )

            print(
                "Mode    :",
                "Date Wise",
            )

            print(
                "From    :",
                FROM_DATE,
            )

            print(
                "To      :",
                TO_DATE,
            )

            print("=" * 78)

            # =================================================
            # 9. SUBMIT
            # =================================================

            await submit_search(page)

            # =================================================
            # 10. INSPECT RESULTS
            # =================================================

            await inspect_results(page)

            # =================================================
            # 11. ASK START PAGE
            # =================================================

            start_page = ask_start_page()

            # =================================================
            # 12. DOWNLOAD
            # =================================================

            await process_all_result_pages(
                page,
                start_page=start_page,
            )

            # =================================================
            # 13. KEEP OPEN
            # =================================================

            await keep_browser_open()

        except Exception as exc:
            print()
            print("=" * 78)

            print(
                "ERROR:",
                repr(exc),
            )

            print("=" * 78)

            try:
                await save_debug(
                    page,
                    "fatal_error",
                )

            except Exception:
                pass

            try:
                await keep_browser_open()

            except KeyboardInterrupt:
                pass


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print()
        print("Script stopped.")
