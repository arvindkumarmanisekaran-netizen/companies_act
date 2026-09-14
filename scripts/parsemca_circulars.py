#!/usr/bin/env python3

import asyncio
import base64
import csv
import re
import time
from pathlib import Path
from urllib.parse import unquote

from playwright.async_api import async_playwright

# ============================================================
# CONFIGURATION
# ============================================================

START_URL = "https://www.mca.gov.in/content/mca/global/en/home.html"

CIRCULARS_DIRECT_URL = (
    "https://www.mca.gov.in/content/mca/global/en/" "acts-rules/ebooks/circulars.html"
)

TARGET_ACT = "The Companies Act, 2013"
TARGET_ACT_DATA_ID = "J105_D"

DOC_CATEGORY = "Circulars"

# ------------------------------------------------------------
# IMPORTANT
#
# Circulars page has TWO tables.
#
# Initial automatic page load:
#   notificationCircularTable
#
# Filtered Go results:
#   notificationCircularResultTable
# ------------------------------------------------------------

INITIAL_TABLE_ID = "notificationCircularTable"

RESULT_TABLE_ID = "notificationCircularResultTable"


OUTPUT_ROOT = Path("mca_companies_act_2013")

DOWNLOAD_DIR = OUTPUT_ROOT / "circulars"

DEBUG_DIR = OUTPUT_ROOT / "debug" / "circulars"

MANIFEST_FILE = DOWNLOAD_DIR / "downloads.csv"

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DEBUG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# PLAYWRIGHT CONFIGURATION
# ============================================================

HEADLESS = True

DEFAULT_TIMEOUT = 30000

NAVIGATION_RETRIES = 10

ACT_OPTIONS_TIMEOUT_SECONDS = 60

INITIAL_TABLE_TIMEOUT_SECONDS = 90

FILTERED_RESULTS_TIMEOUT_SECONDS = 90

ALL_RESULTS_TIMEOUT_SECONDS = 90


# ============================================================
# DOWNLOAD / RETRY CONFIGURATION
# ============================================================

DOWNLOAD_RETRY_ATTEMPTS = 5

# Normal exponential retry:
#
# 2
# 4
# 8
# 16
RETRY_BASE_DELAY_SECONDS = 2


# HTTP 403 exponential retry:
#
# 10
# 20
# 40
# 80
HTTP_403_BASE_DELAY_SECONDS = 10


# Delay between different PDFs
INTER_DOWNLOAD_DELAY_SECONDS = 5


DIRECT_HTTP_TIMEOUT_MS = 120000


# ============================================================
# DEBUG
# ============================================================

DEBUG_NETWORK = True

DEBUG_TABLE = True


# ============================================================
# NETWORK TRACKING
# ============================================================

circular_request_urls = []

circular_response_urls = []


# ============================================================
# MANIFEST
# ============================================================

MANIFEST_FIELDS = [
    "table_row",
    "document_id",
    "circular_date",
    "particulars",
    "original_pdf",
    "saved_filename",
    "document_url",
    "status",
]


def clean_text(value):

    value = value or ""

    value = value.replace(
        "\xa0",
        " ",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def load_manifest():

    if not MANIFEST_FILE.exists():

        return []

    try:

        with MANIFEST_FILE.open(
            "r",
            newline="",
            encoding="utf-8-sig",
        ) as file:

            return list(csv.DictReader(file))

    except Exception as exc:

        print(
            "[DEBUG] Manifest load failed:",
            repr(exc),
        )

        return []


def save_manifest(rows):

    with MANIFEST_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=MANIFEST_FIELDS,
            extrasaction="ignore",
        )

        writer.writeheader()

        writer.writerows(rows)


def upsert_manifest_row(
    manifest_rows,
    row_data,
):

    document_id = clean_text(
        row_data.get(
            "document_id",
            "",
        )
    )

    date = clean_text(
        row_data.get(
            "circular_date",
            "",
        )
    )

    particulars = clean_text(
        row_data.get(
            "particulars",
            "",
        )
    )

    for index, existing in enumerate(manifest_rows):

        existing_id = clean_text(
            existing.get(
                "document_id",
                "",
            )
        )

        if document_id and existing_id:

            same = document_id == existing_id

        else:

            same = (
                clean_text(
                    existing.get(
                        "circular_date",
                        "",
                    )
                )
                == date
                and clean_text(
                    existing.get(
                        "particulars",
                        "",
                    )
                )
                == particulars
            )

        if same:

            manifest_rows[index] = row_data

            save_manifest(manifest_rows)

            return

    manifest_rows.append(row_data)

    save_manifest(manifest_rows)


# ============================================================
# FILENAME HELPERS
# ============================================================


def sanitize_filename_component(value):

    value = clean_text(value)

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

    value = value.strip(" .")

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

            return raw.decode("utf-8").rstrip()

        except UnicodeDecodeError:

            raw = raw[:-1]

    return ""


def sortable_circular_date(value):

    value = clean_text(value)

    patterns = [
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
        r"(\d{1,2})-(\d{1,2})-(\d{4})",
    ]

    for pattern in patterns:

        match = re.fullmatch(
            pattern,
            value,
        )

        if not match:

            continue

        day = int(match.group(1))

        month = int(match.group(2))

        year = int(match.group(3))

        return f"{year:04d}-" f"{month:02d}-" f"{day:02d}"

    return sanitize_filename_component(value)


def strip_size_suffix(value):

    value = clean_text(value)

    return re.sub(
        (r"\s*\|\s*" r"\d+(?:\.\d+)?\s*" r"(?:KB|MB|GB)" r"\s*$"),
        "",
        value,
        flags=re.I,
    ).strip()


def build_filename(
    circular_date,
    particulars,
    max_bytes=245,
):

    date = sanitize_filename_component(sortable_circular_date(circular_date))

    particulars = sanitize_filename_component(strip_size_suffix(particulars))

    prefix = f"{date} - "

    suffix = ".pdf"

    filename = prefix + particulars + suffix

    if len(filename.encode("utf-8")) <= max_bytes:

        return filename

    available = max_bytes - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8"))

    available = max(
        30,
        available,
    )

    particulars = truncate_utf8(
        particulars,
        available,
    )

    return prefix + particulars + suffix


# ============================================================
# DOCUMENT URL
# ============================================================


def encode_document_id(document_id):

    return base64.b64encode(str(document_id).encode("utf-8")).decode("ascii")


def build_document_url(
    document_id,
    doc_category=DOC_CATEGORY,
):

    encoded = encode_document_id(document_id)

    return (
        "https://www.mca.gov.in/"
        "bin/ebook/dms/getdocument"
        f"?doc={encoded}"
        f"&docCategory={doc_category}"
        "&type=open"
    )


# ============================================================
# URL HELPERS
# ============================================================


def is_home_url(url):

    return bool(
        re.search(
            r"/home\.html(?:$|[?#])",
            url or "",
            re.I,
        )
    )


def is_ebooks_url(url):

    return bool(
        re.search(
            r"/acts-rules/ebooks\.html(?:$|[?#])",
            url or "",
            re.I,
        )
    )


def is_circulars_url(url):

    return bool(
        re.search(
            (r"/acts-rules/" r"ebooks/" r"circulars\.html" r"(?:$|[?#])"),
            url or "",
            re.I,
        )
    )


def is_filtered_circular_url(url):

    decoded = unquote(url or "")

    return (
        "documentMetadata" in decoded
        and "docCategory=Circulars" in decoded
        and "docGroup=" in decoded
        and TARGET_ACT in decoded
    )


# ============================================================
# PDF HELPERS
# ============================================================


def looks_like_pdf(body):

    if not body:

        return False

    return b"%PDF-" in body


def normalize_pdf_bytes(body):

    position = body.find(b"%PDF-")

    if position < 0:

        return body

    return body[position:]


def filename_from_content_disposition(
    headers,
):

    if not headers:

        return ""

    disposition = clean_text(
        headers.get(
            "content-disposition",
            "",
        )
    )

    if not disposition:

        return ""

    match = re.search(
        (r"filename\*\s*=\s*" r"(?:UTF-8''|utf-8'')?" r"([^;]+)"),
        disposition,
        re.I,
    )

    if match:

        return clean_text(unquote(match.group(1).strip().strip("\"'")))

    match = re.search(
        r'filename\s*=\s*"([^"]+)"',
        disposition,
        re.I,
    )

    if match:

        return clean_text(match.group(1))

    match = re.search(
        r"filename\s*=\s*([^;]+)",
        disposition,
        re.I,
    )

    if match:

        return clean_text(match.group(1).strip().strip("\"'"))

    return ""


# ============================================================
# DEBUG
# ============================================================


def debug(message):

    print(
        f"[DEBUG] {message}",
        flush=True,
    )


async def save_debug(
    page,
    name,
):

    safe_name = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        name,
    )

    try:

        screenshot = DEBUG_DIR / f"{safe_name}.png"

        await page.screenshot(
            path=str(screenshot),
            full_page=True,
        )

        print(
            "[DEBUG] Screenshot:",
            screenshot.resolve(),
        )

    except Exception as exc:

        print(
            "[DEBUG] Screenshot failed:",
            repr(exc),
        )

    for frame_index, frame in enumerate(page.frames):

        try:

            html = await frame.content()

            path = DEBUG_DIR / (f"{safe_name}_" f"frame_{frame_index}.html")

            path.write_text(
                html,
                encoding="utf-8",
            )

            print(
                "[DEBUG] HTML:",
                path.resolve(),
            )

        except Exception as exc:

            print(
                "[DEBUG] HTML save failed:",
                repr(exc),
            )


# ============================================================
# GENERIC DATATABLE STATE
# ============================================================


async def get_table_state(
    frame,
    table_id,
):

    return await frame.evaluate(
        """
        (tableId) => {

            const table =
                document.getElementById(
                    tableId
                );

            if (!table) {

                return {

                    tableFound:
                        false,

                    tableId:
                        tableId,

                    tableVisible:
                        false,

                    containerVisible:
                        false,

                    rawRows:
                        0,

                    realRows:
                        0,

                    dmsLinks:
                        0,

                    circularLinks:
                        0,

                    lengthValue:
                        null,

                    infoText:
                        '',

                    processingVisible:
                        false,

                    dataTableAvailable:
                        false,

                    dataTableRows:
                        null,

                    dataTablePageLength:
                        null,

                    recordsDisplay:
                        null,

                    recordsTotal:
                        null,

                    visibleIds:
                        []
                };
            }

            const rect =
                table.getBoundingClientRect();

            const style =
                getComputedStyle(
                    table
                );

            const tableVisible =
                (
                    style.display
                    !== 'none'
                    &&
                    style.visibility
                    !== 'hidden'
                    &&
                    rect.width > 0
                    &&
                    rect.height > 0
                );

            const container =
                table.closest(
                    '.notificationCircularResultTableContainer'
                )
                ||
                table.closest(
                    '.notificationCircularTableContainer'
                )
                ||
                table.parentElement;

            let containerVisible =
                true;

            if (container) {

                const containerStyle =
                    getComputedStyle(
                        container
                    );

                const containerRect =
                    container
                    .getBoundingClientRect();

                containerVisible =
                    (
                        containerStyle.display
                        !== 'none'
                        &&
                        containerStyle.visibility
                        !== 'hidden'
                        &&
                        containerRect.width > 0
                        &&
                        containerRect.height > 0
                    );
            }

            const tbody =
                table.querySelector(
                    'tbody'
                );

            const rows =
                tbody
                ? Array.from(
                    tbody.querySelectorAll(
                        ':scope > tr'
                    )
                )
                : [];

            const realRows =
                rows.filter(
                    row => {

                        const text =
                            (
                                row.innerText
                                || ''
                            )
                            .replace(
                                /\\s+/g,
                                ' '
                            )
                            .trim();

                        if (!text) {

                            return false;
                        }

                        const lower =
                            text.toLowerCase();

                        if (
                            lower.includes(
                                'no data available'
                            )
                            ||
                            lower.includes(
                                'no matching records'
                            )
                            ||
                            lower.includes(
                                'no entries to show'
                            )
                            ||
                            lower.includes(
                                'processing...'
                            )
                            ||
                            lower.includes(
                                'loading...'
                            )
                        ) {

                            return false;
                        }

                        return (
                            row.querySelectorAll(
                                'td'
                            ).length
                            > 0
                        );
                    }
                );

            const dmsLinks =
                table.querySelectorAll(
                    'a.dmslink'
                ).length;

            const circularLinks =
                table.querySelectorAll(
                    'a.dmslink[data-doccategory="Circulars"]'
                ).length;

            const visibleIds =
                realRows
                .map(
                    row => {

                        const link =
                            row.querySelector(
                                'a.dmslink'
                            );

                        if (!link) {

                            return '';
                        }

                        return (
                            link.getAttribute(
                                'val'
                            )
                            || ''
                        )
                        .trim();
                    }
                )
                .filter(
                    Boolean
                );

            let lengthSelect =
                document.querySelector(
                    `select[name="${tableId}_length"]`
                );

            if (!lengthSelect) {

                lengthSelect =
                    document.querySelector(
                        `select[aria-controls="${tableId}"]`
                    );
            }

            let info =
                document.getElementById(
                    tableId
                    + '_info'
                );

            let processing =
                document.getElementById(
                    tableId
                    + '_processing'
                );

            const processingVisible =
                processing
                ? (
                    getComputedStyle(
                        processing
                    ).display
                    !== 'none'
                    &&
                    getComputedStyle(
                        processing
                    ).visibility
                    !== 'hidden'
                )
                : false;

            let dataTableAvailable =
                false;

            let dataTableRows =
                null;

            let dataTablePageLength =
                null;

            let recordsDisplay =
                null;

            let recordsTotal =
                null;

            try {

                if (
                    window.jQuery
                    &&
                    jQuery.fn
                    &&
                    jQuery.fn.dataTable
                    &&
                    jQuery.fn.dataTable.isDataTable(
                        '#' + tableId
                    )
                ) {

                    dataTableAvailable =
                        true;

                    const dt =
                        jQuery(
                            '#' + tableId
                        )
                        .DataTable();

                    const pageInfo =
                        dt.page.info();

                    dataTableRows =
                        dt.rows().count();

                    dataTablePageLength =
                        dt.page.len();

                    recordsDisplay =
                        pageInfo.recordsDisplay;

                    recordsTotal =
                        pageInfo.recordsTotal;
                }

            }
            catch (error) {}

            return {

                tableFound:
                    true,

                tableId:
                    tableId,

                tableVisible:
                    tableVisible,

                containerVisible:
                    containerVisible,

                rawRows:
                    rows.length,

                realRows:
                    realRows.length,

                dmsLinks:
                    dmsLinks,

                circularLinks:
                    circularLinks,

                lengthValue:
                    lengthSelect
                    ? lengthSelect.value
                    : null,

                infoText:
                    info
                    ? (
                        info.innerText
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim()
                    : '',

                processingVisible:
                    processingVisible,

                dataTableAvailable:
                    dataTableAvailable,

                dataTableRows:
                    dataTableRows,

                dataTablePageLength:
                    dataTablePageLength,

                recordsDisplay:
                    recordsDisplay,

                recordsTotal:
                    recordsTotal,

                visibleIds:
                    visibleIds
            };
        }
        """,
        table_id,
    )


async def get_initial_table_state(frame):

    return await get_table_state(
        frame,
        INITIAL_TABLE_ID,
    )


async def get_result_table_state(frame):

    return await get_table_state(
        frame,
        RESULT_TABLE_ID,
    )


def print_table_state(
    prefix,
    state,
):

    print(
        (
            f"{prefix}"
            f"table={state.get('tableFound')} "
            f"id={state.get('tableId')!r} "
            f"visible={state.get('tableVisible')} "
            f"containerVisible="
            f"{state.get('containerVisible')} "
            f"rawRows={state.get('rawRows')} "
            f"realRows={state.get('realRows')} "
            f"circularLinks="
            f"{state.get('circularLinks')} "
            f"dmsLinks={state.get('dmsLinks')} "
            f"pageLength="
            f"{state.get('lengthValue')!r} "
            f"processing="
            f"{state.get('processingVisible')} "
            f"DT={state.get('dataTableAvailable')} "
            f"DTrows="
            f"{state.get('dataTableRows')} "
            f"DTlen="
            f"{state.get('dataTablePageLength')} "
            f"DTdisplay="
            f"{state.get('recordsDisplay')} "
            f"DTtotal="
            f"{state.get('recordsTotal')}"
        ),
        flush=True,
    )

    info = clean_text(
        state.get(
            "infoText",
            "",
        )
    )

    if info:

        print(
            f"{prefix}info={info!r}",
            flush=True,
        )


# ============================================================
# WAIT FOR INITIAL AUTOMATIC TABLE
# ============================================================


async def wait_for_initial_circulars_load(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("WAITING FOR INITIAL CIRCULARS TABLE TO POPULATE")

    print("=" * 78)

    loop = asyncio.get_running_loop()

    start = loop.time()

    previous_signature = None

    stable_checks = 0

    last_log_time = -1

    while loop.time() - start < INITIAL_TABLE_TIMEOUT_SECONDS:

        state = await get_initial_table_state(frame)

        elapsed = loop.time() - start

        elapsed_second = int(elapsed)

        signature = (
            state.get("tableFound"),
            state.get("realRows"),
            state.get("dmsLinks"),
            state.get("dataTableRows"),
            state.get("dataTablePageLength"),
            state.get("recordsDisplay"),
            state.get("recordsTotal"),
            state.get("processingVisible"),
            tuple(state.get("visibleIds", [])),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            debug("Initial table changed: " f"{previous_signature!r} " "-> " f"{signature!r}")

            previous_signature = signature

            stable_checks = 0

        if elapsed_second != last_log_time:

            print_table_state(
                ("[DEBUG INITIAL " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                ("[DEBUG INITIAL] " f"stableChecks=" f"{stable_checks}"),
                flush=True,
            )

            last_log_time = elapsed_second

        if (
            state.get("tableFound")
            and state.get(
                "realRows",
                0,
            )
            > 0
            and state.get(
                "dmsLinks",
                0,
            )
            > 0
            and state.get("dataTableRows") is not None
            and state.get("dataTableRows") > 0
            and not state.get("processingVisible")
            and stable_checks >= 5
        ):

            print()
            print("=" * 78)

            print("INITIAL CIRCULARS TABLE POPULATED")

            print("=" * 78)

            print_table_state(
                "[DEBUG INITIAL FINAL] ",
                state,
            )

            print(
                "[DEBUG] Initial visible IDs:",
                state.get("visibleIds", []),
            )

            print()
            print("Initial automatic load complete.")

            await page.wait_for_timeout(1000)

            return

        await page.wait_for_timeout(250)

    await save_debug(
        page,
        "initial_circular_table_timeout",
    )

    raise RuntimeError("Initial Circulars table " "did not finish loading.")


# ============================================================
# HOME
# ============================================================


async def open_home(page):

    print()
    print("=" * 78)

    print("OPENING MCA HOME")

    print("=" * 78)

    response = await page.goto(
        START_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    if response:

        print(
            "HTTP status:",
            response.status,
        )

    print(
        "URL:",
        page.url,
    )

    if response and response.status >= 400:

        raise RuntimeError("MCA home returned " f"HTTP {response.status}")

    await page.wait_for_timeout(1200)


# ============================================================
# ACTS & RULES LINK
# ============================================================


async def find_acts_rules_link(page):

    selectors = [
        (".second-navigation " 'a[href="/content/mca/global/en/' 'acts-rules.html"]'),
        ('a[href="/content/mca/global/en/' 'acts-rules.html"]'),
    ]

    for selector in selectors:

        locator = page.locator(selector)

        for index in range(await locator.count()):

            candidate = locator.nth(index)

            try:

                if await candidate.is_visible():

                    return candidate

            except Exception:

                pass

    return None


# ============================================================
# CIRCULAR TAB
# ============================================================


async def click_circulars_tab(page):

    print()
    print("Searching for Circulars tab...")

    selectors = [
        (".ebooknavigation " "a.menuClick" '[data-doccategory="Circulars"]'),
        ("a.menuClick" '[data-doccategory="Circulars"]'),
        ('a[data-doccategory="Circulars"]'),
    ]

    for _ in range(100):

        for frame_index, frame in enumerate(page.frames):

            for selector in selectors:

                try:

                    locator = frame.locator(selector)

                    count = await locator.count()

                except Exception:

                    continue

                for index in range(count):

                    candidate = locator.nth(index)

                    try:

                        if not await candidate.is_visible():

                            continue

                    except Exception:

                        continue

                    print("  Circulars tab found " f"in frame #{frame_index}")

                    print(
                        "  Selector:",
                        selector,
                    )

                    try:

                        await candidate.click(
                            timeout=10000,
                        )

                    except Exception:

                        await candidate.click(
                            force=True,
                        )

                    for _ in range(150):

                        if is_circulars_url(page.url):

                            return True

                        await page.wait_for_timeout(100)

        await page.wait_for_timeout(100)

    return False


# ============================================================
# CIRCULAR CONTEXT
# ============================================================


async def find_circulars_context(
    page,
    timeout_seconds=20,
):

    loop = asyncio.get_running_loop()

    start = loop.time()

    while loop.time() - start < timeout_seconds:

        for frame in page.frames:

            try:

                if await frame.locator("#DropDown_Act").count() > 0:

                    return frame

            except Exception:

                pass

        await page.wait_for_timeout(100)

    return None


# ============================================================
# OPEN CIRCULARS
# ============================================================


async def open_circulars_module(page):

    for attempt in range(
        1,
        NAVIGATION_RETRIES + 1,
    ):

        print()
        print("=" * 78)

        print("CIRCULARS NAVIGATION ATTEMPT " f"{attempt}/" f"{NAVIGATION_RETRIES}")

        print("=" * 78)

        if not is_home_url(page.url):

            await open_home(page)

        acts_link = await find_acts_rules_link(page)

        if acts_link is None:

            debug("Acts & Rules link not found.")

            continue

        print("Clicking Acts & Rules...")

        try:

            await acts_link.click(
                timeout=10000,
            )

        except Exception:

            await acts_link.click(
                force=True,
            )

        ebooks_seen = False

        for _ in range(200):

            if is_ebooks_url(page.url):

                ebooks_seen = True

                break

            await page.wait_for_timeout(50)

        if not ebooks_seen:

            continue

        print(
            "eBooks page detected:",
            page.url,
        )

        await page.wait_for_timeout(500)

        await click_circulars_tab(page)

        frame = await find_circulars_context(
            page,
            timeout_seconds=20,
        )

        if frame is not None:

            print()
            print("=" * 78)

            print("CIRCULARS MODULE LOADED")

            print("=" * 78)

            print(
                "Current URL:",
                page.url,
            )

            print(
                "Circulars context:",
                frame.url,
            )

            return frame

        print("Using direct Circulars URL...")

        await page.goto(
            CIRCULARS_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        frame = await find_circulars_context(
            page,
            timeout_seconds=20,
        )

        if frame is not None:

            return frame

    raise RuntimeError("Could not load Circulars module.")


# ============================================================
# COMPANIES ACT DROPDOWN
# ============================================================


async def wait_for_companies_act_option(
    page,
    frame,
):

    print()
    print("Waiting for Companies Act option...")

    loop = asyncio.get_running_loop()

    start = loop.time()

    last_count = None

    while loop.time() - start < ACT_OPTIONS_TIMEOUT_SECONDS:

        dropdown = frame.locator("#DropDown_Act")

        if await dropdown.count() > 0:

            dropdown = dropdown.first

            options = dropdown.locator("option")

            count = await options.count()

            if count != last_count:

                debug("Act dropdown option count: " f"{count}")

                last_count = count

            for index in range(count):

                option = options.nth(index)

                text = clean_text(await option.inner_text())

                data_id = await option.get_attribute("data-id") or ""

                if text == TARGET_ACT or data_id == TARGET_ACT_DATA_ID:

                    debug("Companies Act found at " f"option index {index}")

                    return (
                        dropdown,
                        index,
                    )

        await page.wait_for_timeout(250)

    raise RuntimeError("Companies Act option not found.")


# ============================================================
# SELECT + LOCK ACT
# ============================================================


async def select_and_lock_companies_act(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("SELECTING THE COMPANIES ACT, 2013")

    print("=" * 78)

    (
        dropdown,
        target_index,
    ) = await wait_for_companies_act_option(
        page,
        frame,
    )

    result = await dropdown.select_option(
        index=target_index,
    )

    print(
        "Initial select_option:",
        result,
    )

    debug("Waiting 2 seconds for " "MCA onchange handler...")

    await page.wait_for_timeout(2000)

    before = await frame.evaluate("""
        () => {

            const select =
                document.querySelector(
                    '#DropDown_Act'
                );

            if (!select) {

                return null;
            }

            const option =
                select.options[
                    select.selectedIndex
                ];

            return {

                index:
                    select.selectedIndex,

                text:
                    option
                    ? (
                        option.textContent
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim()
                    : '',

                value:
                    option
                    ? option.value || ''
                    : '',

                dataId:
                    option
                    ? (
                        option.getAttribute(
                            'data-id'
                        )
                        || ''
                    )
                    : ''
            };
        }
        """)

    print(
        "After MCA onchange:",
        before,
    )

    locked = await frame.evaluate(
        """
        ({targetText, targetDataId}) => {

            const select =
                document.querySelector(
                    '#DropDown_Act'
                );

            if (!select) {

                return {
                    ok:
                        false
                };
            }

            const options =
                Array.from(
                    select.options
                );

            let index =
                options.findIndex(
                    option =>
                        (
                            option.getAttribute(
                                'data-id'
                            )
                            || ''
                        )
                        === targetDataId
                );

            if (index < 0) {

                index =
                    options.findIndex(
                        option =>
                            (
                                option.textContent
                                || ''
                            )
                            .replace(
                                /\\s+/g,
                                ' '
                            )
                            .trim()
                            === targetText
                    );
            }

            if (index < 0) {

                return {
                    ok:
                        false
                };
            }

            options.forEach(
                (
                    option,
                    optionIndex
                ) => {

                    option.selected =
                        (
                            optionIndex
                            === index
                        );
                }
            );

            select.selectedIndex =
                index;

            const go =
                document.querySelector(
                    '#clickGo'
                );

            if (go) {

                try {

                    go.disabled =
                        false;

                }
                catch (error) {}

                try {

                    go.removeAttribute(
                        'disabled'
                    );

                }
                catch (error) {}
            }

            const selected =
                select.options[
                    select.selectedIndex
                ];

            return {

                ok:
                    true,

                index:
                    select.selectedIndex,

                text:
                    (
                        selected.textContent
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim(),

                value:
                    selected.value
                    || '',

                dataId:
                    selected.getAttribute(
                        'data-id'
                    )
                    || '',

                goFound:
                    !!go,

                goDisabled:
                    go
                    ? !!go.disabled
                    : null
            };
        }
        """,
        {
            "targetText": TARGET_ACT,
            "targetDataId": TARGET_ACT_DATA_ID,
        },
    )

    print(
        "LOCKED SELECTION:",
        locked,
    )

    if not locked or not locked.get("ok"):

        raise RuntimeError("Failed to lock Companies Act.")


# ============================================================
# CLICK GO
# ============================================================


async def click_go_and_wait(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("CLICKING GO")

    print("=" * 78)

    selected = await frame.evaluate("""
        () => {

            const select =
                document.querySelector(
                    '#DropDown_Act'
                );

            if (!select) {

                return null;
            }

            const option =
                select.options[
                    select.selectedIndex
                ];

            return {

                index:
                    select.selectedIndex,

                text:
                    option
                    ? (
                        option.textContent
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim()
                    : '',

                dataId:
                    option
                    ? (
                        option.getAttribute(
                            'data-id'
                        )
                        || ''
                    )
                    : ''
            };
        }
        """)

    print(
        "Selection immediately before Go:",
        selected,
    )

    if not selected or (
        selected.get("text") != TARGET_ACT and selected.get("dataId") != TARGET_ACT_DATA_ID
    ):

        raise RuntimeError("Companies Act selection lost " "before Go.")

    # --------------------------------------------------------
    # Show state of INITIAL table immediately before Go.
    # --------------------------------------------------------

    initial_state = await get_initial_table_state(frame)

    print_table_state(
        "[DEBUG INITIAL BEFORE GO] ",
        initial_state,
    )

    circular_request_urls.clear()
    circular_response_urls.clear()

    go = frame.locator("#clickGo")

    if await go.count() == 0:

        raise RuntimeError("Go button missing.")

    print("Clicking Go...")

    try:

        await go.first.click(
            timeout=15000,
        )

    except Exception:

        await go.first.click(
            force=True,
        )

    print("Go clicked.")

    print()
    print("Waiting for FILTERED RESULT TABLE...")

    print(
        "Monitoring:",
        f"#{RESULT_TABLE_ID}",
    )

    loop = asyncio.get_running_loop()

    start = loop.time()

    filtered_request_seen = False
    filtered_response_seen = False

    previous_signature = None
    stable_checks = 0

    last_log = -1

    while loop.time() - start < FILTERED_RESULTS_TIMEOUT_SECONDS:

        filtered_request_seen = any(is_filtered_circular_url(url) for url in circular_request_urls)

        filtered_response_seen = any(
            is_filtered_circular_url(url) for url in circular_response_urls
        )

        result_state = await get_result_table_state(frame)

        elapsed = loop.time() - start

        elapsed_second = int(elapsed)

        signature = (
            result_state.get("tableFound"),
            result_state.get("containerVisible"),
            result_state.get("realRows"),
            result_state.get("dmsLinks"),
            result_state.get("dataTableRows"),
            result_state.get("dataTablePageLength"),
            result_state.get("recordsDisplay"),
            result_state.get("recordsTotal"),
            result_state.get("processingVisible"),
            tuple(result_state.get("visibleIds", [])),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            debug(
                "Filtered RESULT table changed: " f"{previous_signature!r} " "-> " f"{signature!r}"
            )

            previous_signature = signature

            stable_checks = 0

        if elapsed_second != last_log:

            print_table_state(
                ("[DEBUG FILTERED RESULT " f"+{elapsed:05.2f}s] "),
                result_state,
            )

            print(
                (
                    "[DEBUG FILTERED RESULT] "
                    f"requestSeen="
                    f"{filtered_request_seen} "
                    f"responseSeen="
                    f"{filtered_response_seen} "
                    f"stableChecks="
                    f"{stable_checks}"
                ),
                flush=True,
            )

            last_log = elapsed_second

        # ----------------------------------------------------
        # We specifically require RESULT TABLE.
        #
        # We no longer care what notificationCircularTable
        # contains after Go.
        # --------------------------------------------------------

        if (
            filtered_request_seen
            and filtered_response_seen
            and result_state.get("tableFound")
            and result_state.get("dataTableAvailable")
            and result_state.get(
                "realRows",
                0,
            )
            > 0
            and result_state.get(
                "dmsLinks",
                0,
            )
            > 0
            and not result_state.get("processingVisible")
            and stable_checks >= 3
        ):

            print()
            print("=" * 78)

            print("FILTERED RESULT TABLE LOADED")

            print("=" * 78)

            print_table_state(
                "[DEBUG FILTERED FINAL] ",
                result_state,
            )

            print(
                "[DEBUG] Filtered visible IDs:",
                result_state.get("visibleIds", []),
            )

            # ------------------------------------------------
            # Debug both tables so we can see the transition.
            # ------------------------------------------------

            hidden_initial = await get_initial_table_state(frame)

            print()
            print("TABLE TRANSITION CHECK")

            print_table_state(
                "[INITIAL TABLE] ",
                hidden_initial,
            )

            print_table_state(
                "[RESULT TABLE]  ",
                result_state,
            )

            print()
            print("Filtered result is ready.")

            print("Now selecting All on " "the RESULT table.")

            await page.wait_for_timeout(1000)

            return

        await page.wait_for_timeout(250)

    await save_debug(
        page,
        "filtered_result_table_timeout",
    )

    raise RuntimeError("Filtered Circular RESULT table " "did not finish loading.")


# ============================================================
# SELECT ALL ON FILTERED RESULT TABLE
# ============================================================


async def select_all_results(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("SELECTING FILTERED CIRCULAR RESULTS PER PAGE = ALL")

    print("=" * 78)

    before = await get_result_table_state(frame)

    print_table_state(
        "[DEBUG BEFORE ALL] ",
        before,
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # All selector belongs to RESULT TABLE,
    # not initial table.
    # --------------------------------------------------------

    dropdown = frame.locator(('select[name="' "notificationCircularResultTable_length" '"]'))

    print(
        "[DEBUG] Exact result length dropdown count:",
        await dropdown.count(),
    )

    if await dropdown.count() == 0:

        dropdown = frame.locator(('select[aria-controls="' "notificationCircularResultTable" '"]'))

        print(
            "[DEBUG] aria-controls result dropdown count:",
            await dropdown.count(),
        )

    if await dropdown.count() == 0:

        await save_debug(
            page,
            "result_length_dropdown_missing",
        )

        raise RuntimeError("Filtered Circular RESULT " "page-length dropdown missing.")

    visible_dropdown = None

    for index in range(await dropdown.count()):

        candidate = dropdown.nth(index)

        try:

            if await candidate.is_visible():

                visible_dropdown = candidate

                break

        except Exception:

            pass

    if visible_dropdown is None:

        visible_dropdown = dropdown.first

    dropdown = visible_dropdown

    details = await dropdown.evaluate("""
        select => ({

            id:
                select.id || '',

            name:
                select.name || '',

            ariaControls:
                select.getAttribute(
                    'aria-controls'
                )
                || '',

            value:
                select.value,

            options:
                Array.from(
                    select.options
                )
                .map(
                    option => ({

                        value:
                            option.value,

                        text:
                            (
                                option.textContent
                                || ''
                            )
                            .replace(
                                /\\s+/g,
                                ' '
                            )
                            .trim(),

                        selected:
                            option.selected
                    })
                )
        })
        """)

    print(
        "[DEBUG] RESULT table page-length control:",
        details,
    )

    print()
    print("Selecting All...")

    started = time.monotonic()

    try:

        selected = await dropdown.select_option(value="-1")

    except Exception:

        selected = await dropdown.select_option(label="All")

    print(
        "Selected All:",
        selected,
    )

    try:

        value = await dropdown.input_value()

    except Exception:

        value = None

    print(
        "[DEBUG] Same RESULT dropdown value:",
        repr(value),
    )

    # ========================================================
    # WAIT FOR FULL FILTERED RESULT TABLE
    # ========================================================

    loop = asyncio.get_running_loop()

    start = loop.time()

    previous_signature = None

    stable_checks = 0

    last_log = -1

    final_state = None

    while loop.time() - start < ALL_RESULTS_TIMEOUT_SECONDS:

        state = await get_result_table_state(frame)

        final_state = state

        elapsed = loop.time() - start

        elapsed_second = int(elapsed)

        signature = (
            state.get("realRows"),
            state.get("circularLinks"),
            state.get("dmsLinks"),
            state.get("lengthValue"),
            state.get("dataTableRows"),
            state.get("dataTablePageLength"),
            state.get("recordsDisplay"),
            state.get("recordsTotal"),
            state.get("processingVisible"),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            debug("Filtered All table changed: " f"{previous_signature!r} " "-> " f"{signature!r}")

            previous_signature = signature

            stable_checks = 0

        if elapsed_second != last_log:

            print_table_state(
                ("[DEBUG ALL " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                ("[DEBUG ALL] " f"stableChecks=" f"{stable_checks}"),
                flush=True,
            )

            last_log = elapsed_second

        real_rows = (
            state.get(
                "realRows",
                0,
            )
            or 0
        )

        dms_links = (
            state.get(
                "dmsLinks",
                0,
            )
            or 0
        )

        dt_length = state.get("dataTablePageLength")

        html_length = str(
            state.get(
                "lengthValue",
                "",
            )
        )

        processing = bool(state.get("processingVisible"))

        # ----------------------------------------------------
        # Because filtered table may contain <=5 records in
        # some future case, we don't require realRows > 5.
        #
        # We instead require:
        #
        # - All selected
        # - DataTable API says -1
        # - all rows have links
        # - processing finished
        # - stable
        # --------------------------------------------------------

        if (
            html_length == "-1"
            and dt_length == -1
            and real_rows > 0
            and dms_links >= real_rows
            and not processing
            and stable_checks >= 3
        ):

            break

        await page.wait_for_timeout(250)

    if final_state is None:

        raise RuntimeError("Could not read final " "filtered result table.")

    if final_state.get("dataTablePageLength") != -1:

        await save_debug(
            page,
            "filtered_all_timeout",
        )

        raise RuntimeError("Filtered Circular Result table " "did not switch to All.")

    final_count = (
        final_state.get(
            "realRows",
            0,
        )
        or 0
    )

    print()
    print("=" * 78)

    print("ALL FILTERED CIRCULAR RESULTS STABLE")

    print("=" * 78)

    print_table_state(
        "[DEBUG FINAL ALL] ",
        final_state,
    )

    print(
        "FINAL FILTERED CIRCULAR ROWS:",
        final_count,
    )

    print(
        "Time to select/render All:",
        (f"{time.monotonic() - started:.2f}s"),
    )

    if final_count <= 0:

        raise RuntimeError("Filtered Circular result " "contains no rows.")

    return final_count


# ============================================================
# METADATA FROM FILTERED RESULT TABLE
# ============================================================


async def collect_circular_metadata(
    frame,
):

    print()
    print("=" * 78)

    print("COLLECTING FILTERED CIRCULAR METADATA")

    print("=" * 78)

    started = time.monotonic()

    result = await frame.evaluate("""
        () => {

            /*
             * IMPORTANT:
             * Read FILTERED RESULT TABLE.
             */
            const table =
                document.querySelector(
                    '#notificationCircularResultTable'
                );

            if (!table) {

                return {

                    ok:
                        false,

                    error:
                        'Filtered Circular result table not found',

                    rows:
                        []
                };
            }

            const tableRows =
                Array.from(
                    table.querySelectorAll(
                        'tbody > tr'
                    )
                );

            const rows = [];

            const errors = [];

            for (
                let index = 0;
                index < tableRows.length;
                index++
            ) {

                const row =
                    tableRows[index];

                const rowText =
                    (
                        row.innerText
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim();

                if (!rowText) {

                    continue;
                }

                const lower =
                    rowText.toLowerCase();

                if (
                    lower.includes(
                        'no data available'
                    )
                    ||
                    lower.includes(
                        'no matching records'
                    )
                    ||
                    lower.includes(
                        'no entries to show'
                    )
                    ||
                    lower.includes(
                        'processing...'
                    )
                    ||
                    lower.includes(
                        'loading...'
                    )
                ) {

                    continue;
                }

                const cells =
                    Array.from(
                        row.querySelectorAll(
                            'td'
                        )
                    )
                    .map(
                        td =>
                            (
                                td.innerText
                                || ''
                            )
                            .replace(
                                /\\s+/g,
                                ' '
                            )
                            .trim()
                    );

                if (
                    cells.length
                    === 0
                ) {

                    continue;
                }

                let link =
                    row.querySelector(
                        'a.notifications.dmslink'
                    );

                if (!link) {

                    link =
                        row.querySelector(
                            'a.dmslink[data-doccategory="Circulars"]'
                        );
                }

                if (!link) {

                    errors.push({

                        rowIndex:
                            index,

                        reason:
                            'Circular dmslink missing',

                        html:
                            row.outerHTML.substring(
                                0,
                                1000
                            )
                    });

                    continue;
                }

                const documentId =
                    (
                        link.getAttribute(
                            'val'
                        )
                        || ''
                    )
                    .trim();

                const docCategory =
                    (
                        link.getAttribute(
                            'data-doccategory'
                        )
                        || ''
                    )
                    .trim();

                const particulars =
                    (
                        link.innerText
                        ||
                        link.textContent
                        ||
                        ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim();

                const ariaLabel =
                    (
                        link.getAttribute(
                            'aria-label'
                        )
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim();

                let date = '';

                for (
                    const cell
                    of cells
                ) {

                    const match =
                        cell.match(
                            /\\b(\\d{1,2}\\/\\d{1,2}\\/\\d{4})\\b/
                        );

                    if (match) {

                        date =
                            match[1];

                        break;
                    }
                }

                if (!date) {

                    const match =
                        rowText.match(
                            /\\b(\\d{1,2}\\/\\d{1,2}\\/\\d{4})\\b/
                        );

                    if (match) {

                        date =
                            match[1];
                    }
                }

                if (!documentId) {

                    errors.push({

                        rowIndex:
                            index,

                        reason:
                            'document ID missing',

                        text:
                            rowText
                    });

                    continue;
                }

                if (!date) {

                    errors.push({

                        rowIndex:
                            index,

                        reason:
                            'date missing',

                        text:
                            rowText
                    });

                    continue;
                }

                rows.push({

                    source_index:
                        index,

                    document_id:
                        documentId,

                    circular_date:
                        date,

                    particulars:
                        particulars
                        || ariaLabel,

                    doc_category:
                        docCategory
                        || 'Circulars',

                    cells:
                        cells
                });
            }

            return {

                ok:
                    true,

                rawTableRows:
                    tableRows.length,

                parsedRows:
                    rows.length,

                errors:
                    errors,

                rows:
                    rows
            };
        }
        """)

    if not result.get("ok"):

        raise RuntimeError("Circular metadata extraction " f"failed: {result!r}")

    print(
        "Raw FILTERED table rows:",
        result.get("rawTableRows"),
    )

    print(
        "Parsed Circular rows:",
        result.get("parsedRows"),
    )

    errors = result.get("errors") or []

    print(
        "Metadata errors:",
        len(errors),
    )

    for error in errors[:10]:

        print(
            "[DEBUG METADATA ERROR]",
            error,
        )

    metadata = []

    for item in result.get("rows") or []:

        document_id = clean_text(
            item.get(
                "document_id",
                "",
            )
        )

        doc_category = clean_text(
            item.get(
                "doc_category",
                "",
            )
        )

        if not doc_category:

            doc_category = DOC_CATEGORY

        item["href"] = build_document_url(
            document_id,
            doc_category,
        )

        metadata.append(item)

    print(
        "Usable Circulars:",
        len(metadata),
    )

    print(
        "Metadata extraction time:",
        (f"{time.monotonic() - started:.2f}s"),
    )

    if not metadata:

        raise RuntimeError("No filtered Circular metadata " "was extracted.")

    table_state = await get_result_table_state(frame)

    expected_rows = (
        table_state.get(
            "realRows",
            0,
        )
        or 0
    )

    if len(metadata) != expected_rows:

        print()
        print("WARNING:")

        print(
            "  Filtered table rows:",
            expected_rows,
        )

        print(
            "  Parsed metadata:",
            len(metadata),
        )

        print(
            "  Difference:",
            (expected_rows - len(metadata)),
        )

        if abs(expected_rows - len(metadata)) > 5:

            raise RuntimeError("Too many filtered Circular rows " "failed metadata extraction.")

    print()
    print("FIRST PARSED CIRCULARS")

    for index, item in enumerate(metadata[:3]):

        print()
        print(f"  [{index + 1}]")

        print(
            "    Date:",
            item.get("circular_date"),
        )

        print(
            "    Document ID:",
            item.get("document_id"),
        )

        print(
            "    Category:",
            item.get("doc_category"),
        )

        print(
            "    Particulars:",
            repr(item.get("particulars")),
        )

        print(
            "    URL:",
            item.get("href"),
        )

    return metadata


# ============================================================
# DIRECT PDF DOWNLOAD
# ============================================================


async def download_pdf_direct(
    context,
    metadata,
    destination,
):

    url = metadata["href"]

    request_started = time.monotonic()

    response = await context.request.get(
        url,
        timeout=(DIRECT_HTTP_TIMEOUT_MS),
        fail_on_status_code=False,
        headers={
            "Referer": CIRCULARS_DIRECT_URL,
            "Accept": ("application/pdf," "application/octet-stream," "*/*"),
        },
    )

    status = response.status

    headers = response.headers

    content_type = clean_text(
        headers.get(
            "content-type",
            "",
        )
    )

    content_disposition = clean_text(
        headers.get(
            "content-disposition",
            "",
        )
    )

    body = await response.body()

    elapsed = time.monotonic() - request_started

    print(
        "  HTTP status:",
        status,
    )

    print(
        "  Content-Type:",
        repr(content_type),
    )

    if content_disposition:

        print(
            "  Content-Disposition:",
            repr(content_disposition),
        )

    print(
        "  Response bytes:",
        len(body),
    )

    print(
        "  HTTP time:",
        f"{elapsed:.2f}s",
    )

    if status < 200 or status >= 300:

        error = RuntimeError(f"HTTP {status}")

        error.http_status = status

        raise error

    if not looks_like_pdf(body):

        preview = clean_text(
            body[:500].decode(
                "utf-8",
                errors="ignore",
            )
        )

        error = RuntimeError(
            "Response is not PDF. " f"Content-Type={content_type!r}; " f"preview={preview!r}"
        )

        error.http_status = status

        raise error

    body = normalize_pdf_bytes(body)

    destination.write_bytes(body)

    original_pdf = filename_from_content_disposition(headers)

    if not original_pdf:

        original_pdf = metadata["document_id"] + ".pdf"

    return {
        "original_pdf": original_pdf,
        "bytes": len(body),
        "http_status": status,
        "elapsed": elapsed,
    }


# ============================================================
# RETRY DELAY
# ============================================================


def calculate_retry_delay(
    attempt,
    error,
):

    http_status = getattr(
        error,
        "http_status",
        None,
    )

    if http_status == 403:

        delay = HTTP_403_BASE_DELAY_SECONDS * (2 ** (attempt - 1))

        return (
            delay,
            "HTTP 403 exponential backoff",
        )

    delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))

    return (
        delay,
        "exponential backoff",
    )


# ============================================================
# DOWNLOAD ONE CIRCULAR
# ============================================================


async def download_circular(
    context,
    metadata,
    index,
    total,
    manifest_rows,
):

    document_id = clean_text(metadata["document_id"])

    date = clean_text(metadata["circular_date"])

    particulars = clean_text(metadata["particulars"])

    url = clean_text(metadata["href"])

    filename = build_filename(
        date,
        particulars,
    )

    destination = DOWNLOAD_DIR / filename

    print()
    print("#" * 78)

    print(f"CIRCULAR " f"{index + 1}/" f"{total}")

    print("#" * 78)

    print(
        "Document ID:",
        document_id,
    )

    print(
        "Circular Date:",
        date,
    )

    print(
        "Particulars:",
        repr(particulars),
    )

    print("Document URL:")

    print(
        " ",
        url,
    )

    # ========================================================
    # RESUME
    # ========================================================

    if destination.exists():

        try:

            size = destination.stat().st_size

        except Exception:

            size = 0

        if size > 0:

            print("ALREADY EXISTS - SKIPPING")

            print(
                "Existing bytes:",
                size,
            )

            upsert_manifest_row(
                manifest_rows,
                {
                    "table_row": index + 1,
                    "document_id": document_id,
                    "circular_date": date,
                    "particulars": particulars,
                    "original_pdf": "",
                    "saved_filename": destination.name,
                    "document_url": url,
                    "status": "already-exists",
                },
            )

            return True

    last_error = None

    # ========================================================
    # RETRIES
    # ========================================================

    for attempt in range(
        1,
        DOWNLOAD_RETRY_ATTEMPTS + 1,
    ):

        print()
        print("DOWNLOAD ATTEMPT " f"{attempt}/" f"{DOWNLOAD_RETRY_ATTEMPTS}")

        try:

            result = await download_pdf_direct(
                context,
                metadata,
                destination,
            )

            print("  SUCCESS")

            print(
                "  Original PDF:",
                repr(result["original_pdf"]),
            )

            print(
                "  Saved bytes:",
                result["bytes"],
            )

            print("  SAVED:")

            print(
                " ",
                destination.name,
            )

            upsert_manifest_row(
                manifest_rows,
                {
                    "table_row": index + 1,
                    "document_id": document_id,
                    "circular_date": date,
                    "particulars": particulars,
                    "original_pdf": result["original_pdf"],
                    "saved_filename": destination.name,
                    "document_url": url,
                    "status": "downloaded",
                },
            )

            return True

        except Exception as exc:

            last_error = exc

            print(
                "  FAILED:",
                repr(exc),
            )

            http_status = getattr(
                exc,
                "http_status",
                None,
            )

            if http_status is not None:

                print(
                    "  HTTP status from error:",
                    http_status,
                )

            try:

                if destination.exists():

                    destination.unlink()

            except Exception:

                pass

        if attempt < DOWNLOAD_RETRY_ATTEMPTS:

            (
                retry_delay,
                retry_reason,
            ) = calculate_retry_delay(
                attempt,
                last_error,
            )

            print(
                "  Retry strategy:",
                retry_reason,
            )

            print(
                (f"  Retrying in " f"{retry_delay}s..."),
                flush=True,
            )

            await asyncio.sleep(retry_delay)

    # ========================================================
    # PERMANENT FAILURE
    # ========================================================

    error_text = clean_text(str(last_error or "Unknown failure"))

    print()
    print("ERROR: all download " "attempts failed.")

    upsert_manifest_row(
        manifest_rows,
        {
            "table_row": index + 1,
            "document_id": document_id,
            "circular_date": date,
            "particulars": particulars,
            "original_pdf": "",
            "saved_filename": filename,
            "document_url": url,
            "status": ("ERROR: " + error_text),
        },
    )

    return False


# ============================================================
# PROCESS ALL
# ============================================================


async def process_all_circulars(
    context,
    frame,
):

    print()
    print("=" * 78)

    print("CIRCULAR DOWNLOAD")

    print("=" * 78)

    manifest_rows = load_manifest()

    print(
        "Existing manifest rows:",
        len(manifest_rows),
    )

    print(
        "Output:",
        DOWNLOAD_DIR.resolve(),
    )

    print(
        "Download retry attempts:",
        DOWNLOAD_RETRY_ATTEMPTS,
    )

    print(
        "Normal retry base delay:",
        f"{RETRY_BASE_DELAY_SECONDS}s",
    )

    print(
        "403 retry base delay:",
        f"{HTTP_403_BASE_DELAY_SECONDS}s",
    )

    print(
        "Delay between downloads:",
        f"{INTER_DOWNLOAD_DELAY_SECONDS}s",
    )

    metadata = await collect_circular_metadata(frame)

    total = len(metadata)

    print()
    print(
        "Total filtered Circular documents:",
        total,
    )

    download_started = time.monotonic()

    successes = 0

    failures = 0

    for index, item in enumerate(metadata):

        result = await download_circular(
            context,
            item,
            index,
            total,
            manifest_rows,
        )

        if result:

            successes += 1

        else:

            failures += 1

        completed = index + 1

        elapsed = time.monotonic() - download_started

        average = elapsed / completed

        remaining = total - completed

        eta_seconds = average * remaining

        if remaining > 0:

            eta_seconds += INTER_DOWNLOAD_DELAY_SECONDS * remaining

        print()
        print(
            (
                "[PROGRESS] "
                f"{completed}/{total} "
                f"("
                f"{completed / total * 100:.1f}%"
                f") | "
                f"success={successes} "
                f"failed={failures} | "
                f"elapsed={elapsed / 60:.1f}m | "
                f"ETA≈{eta_seconds / 60:.1f}m"
            ),
            flush=True,
        )

        # ====================================================
        # 5 SECOND DELAY BETWEEN DOWNLOADS
        # ====================================================

        if completed < total:

            print(
                ("[DELAY] Waiting " f"{INTER_DOWNLOAD_DELAY_SECONDS}s " "before next Circular..."),
                flush=True,
            )

            await asyncio.sleep(INTER_DOWNLOAD_DELAY_SECONDS)

    print()
    print("=" * 78)

    print("FINAL SUMMARY")

    print("=" * 78)

    print(
        "Filtered Circulars discovered:",
        total,
    )

    print(
        "Successful/skipped:",
        successes,
    )

    print(
        "Failed:",
        failures,
    )

    print(
        "Output:",
        DOWNLOAD_DIR.resolve(),
    )

    print(
        "Manifest:",
        MANIFEST_FILE.resolve(),
    )


# ============================================================
# MAIN
# ============================================================


async def main():

    program_started = time.monotonic()

    browser = None

    try:

        async with async_playwright() as p:

            print()

            print("Launching HEADLESS Firefox...")

            browser = await p.firefox.launch(
                headless=HEADLESS,
            )

            context = await browser.new_context(
                accept_downloads=True,
                viewport={
                    "width": 1920,
                    "height": 1080,
                },
                locale="en-US",
            )

            page = await context.new_page()

            page.set_default_timeout(DEFAULT_TIMEOUT)

            # =================================================
            # REQUEST LISTENER
            # =================================================

            def on_request(request):

                try:

                    url = request.url

                    if "documentMetadata" in url and "docCategory=Circulars" in url:

                        circular_request_urls.append(url)

                        if DEBUG_NETWORK:

                            print(
                                "[REQUEST]",
                                url,
                                flush=True,
                            )

                except Exception:

                    pass

            page.on(
                "request",
                on_request,
            )

            # =================================================
            # RESPONSE LISTENER
            # =================================================

            async def on_response_async(
                response,
            ):

                try:

                    request = response.request

                    if request.resource_type not in {
                        "xhr",
                        "fetch",
                    }:

                        return

                    url = response.url

                    if "documentMetadata" not in url:

                        return

                    if DEBUG_NETWORK:

                        print(
                            "[AJAX]",
                            response.status,
                            url,
                            flush=True,
                        )

                    if "docCategory=Circulars" in url:

                        circular_response_urls.append(url)

                except Exception:

                    pass

            def on_response(response):

                asyncio.create_task(on_response_async(response))

            page.on(
                "response",
                on_response,
            )

            # =================================================
            # FLOW
            # =================================================

            await open_home(page)

            frame = await open_circulars_module(page)

            # =================================================
            # STEP 1
            #
            # WAIT FOR AUTOMATIC INITIAL TABLE
            #
            # #notificationCircularTable
            # =================================================

            await wait_for_initial_circulars_load(
                page,
                frame,
            )

            # =================================================
            # STEP 2
            #
            # SELECT COMPANIES ACT
            # =================================================

            await select_and_lock_companies_act(
                page,
                frame,
            )

            # =================================================
            # STEP 3
            #
            # CLICK GO
            #
            # Go destroys/recreates:
            #
            # #notificationCircularResultTable
            #
            # We now monitor THAT table.
            # =================================================

            await click_go_and_wait(
                page,
                frame,
            )

            # =================================================
            # STEP 4
            #
            # SELECT ALL ON FILTERED RESULT TABLE
            #
            # notificationCircularResultTable_length
            # =================================================

            final_count = await select_all_results(
                page,
                frame,
            )

            print()
            print(
                "Companies Act Circulars:",
                final_count,
            )

            # =================================================
            # FINAL DEBUG
            # =================================================

            if DEBUG_TABLE:

                initial_state = await get_initial_table_state(frame)

                result_state = await get_result_table_state(frame)

                print()
                print("FINAL TABLE STATES")

                print_table_state(
                    "[INITIAL] ",
                    initial_state,
                )

                print_table_state(
                    "[FILTERED RESULT] ",
                    result_state,
                )

            # =================================================
            # STEP 5
            #
            # DOWNLOAD ONLY FROM FILTERED RESULT TABLE
            # =================================================

            await process_all_circulars(
                context,
                frame,
            )

    except KeyboardInterrupt:

        print()
        print("Script stopped by user.")

    except Exception as exc:

        print()
        print("=" * 78)

        print(
            "FATAL ERROR:",
            repr(exc),
        )

        print("=" * 78)

        raise

    finally:

        print()

        debug("Total program runtime: " f"{time.monotonic() - program_started:.2f}s")

        if browser is not None:

            try:

                await browser.close()

            except Exception:

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
