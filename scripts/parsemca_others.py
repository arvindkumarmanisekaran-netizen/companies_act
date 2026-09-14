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

OTHERS_DIRECT_URL = "https://www.mca.gov.in/content/mca/global/en/" "acts-rules/ebooks/others.html"

TARGET_ACT = "The Companies Act, 2013"
TARGET_ACT_DATA_ID = "J105_D"

DOC_CATEGORY = "Others"

INITIAL_TABLE_ID = "notificationCircularTable"
RESULT_TABLE_ID = "notificationCircularResultTable"


# ============================================================
# OUTPUT
# ============================================================

OUTPUT_ROOT = Path("mca_companies_act_2013")

DOWNLOAD_DIR = OUTPUT_ROOT / "Amendments, Orders & Regulations"

DEBUG_DIR = OUTPUT_ROOT / "debug" / "Amendments, Orders & Regulations"

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
# PLAYWRIGHT
# ============================================================

HEADLESS = True

DEFAULT_TIMEOUT = 30000

NAVIGATION_RETRIES = 10

ACT_OPTIONS_TIMEOUT_SECONDS = 60

INITIAL_TABLE_TIMEOUT_SECONDS = 90

FILTERED_RESULTS_TIMEOUT_SECONDS = 90

ALL_RESULTS_TIMEOUT_SECONDS = 90


# ============================================================
# DOWNLOAD / RETRY
# ============================================================

DOWNLOAD_RETRY_ATTEMPTS = 5

RETRY_BASE_DELAY_SECONDS = 2

HTTP_403_BASE_DELAY_SECONDS = 10

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

others_request_urls = []
others_response_urls = []


# ============================================================
# MANIFEST
# ============================================================

MANIFEST_FIELDS = [
    "table_row",
    "document_id",
    "document_date",
    "particulars",
    "category",
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

    document_date = clean_text(
        row_data.get(
            "document_date",
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
                        "document_date",
                        "",
                    )
                )
                == document_date
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


def sortable_document_date(value):

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

    # Examples removed:
    #
    # | 2MB
    # | 400KB
    # | 1.5MB

    return re.sub(
        (r"\s*\|\s*" r"\d+(?:\.\d+)?\s*" r"(?:KB|MB|GB)" r"\s*$"),
        "",
        value,
        flags=re.I,
    ).strip()


def build_filename(
    document_date,
    particulars,
    category,
    max_bytes=245,
):

    # ========================================================
    # REQUIRED NAMING CONVENTION
    #
    # YYYY-MM-DD - PDF Name (Type of Document).pdf
    #
    # Example:
    #
    # 2024-07-15 - S.O. 2751(E)-The Specified Companies ...
    # Amendment Order, 2024 (Orders).pdf
    # ========================================================

    date = sanitize_filename_component(sortable_document_date(document_date))

    pdf_name = sanitize_filename_component(strip_size_suffix(particulars))

    type_of_document = sanitize_filename_component(category)

    prefix = f"{date} - "

    type_suffix = f" ({type_of_document})"

    extension = ".pdf"

    filename = prefix + pdf_name + type_suffix + extension

    if len(filename.encode("utf-8")) <= max_bytes:

        return filename

    # --------------------------------------------------------
    # Preserve:
    #
    # date
    # type
    # extension
    #
    # Truncate only the PDF name.
    # --------------------------------------------------------

    fixed_bytes = len((prefix + type_suffix + extension).encode("utf-8"))

    available = max_bytes - fixed_bytes

    pdf_name = truncate_utf8(
        pdf_name,
        max(
            30,
            available,
        ),
    )

    return prefix + pdf_name + type_suffix + extension


# ============================================================
# DOCUMENT URL
# ============================================================


def encode_document_id(
    document_id,
):

    return base64.b64encode(str(document_id).encode("utf-8")).decode("ascii")


def build_document_url(
    document_id,
):

    encoded = encode_document_id(document_id)

    return (
        "https://www.mca.gov.in/"
        "bin/ebook/dms/getdocument"
        f"?doc={encoded}"
        "&docCategory=Others"
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


def is_others_url(url):

    return bool(
        re.search(
            (r"/acts-rules/" r"ebooks/" r"others\.html" r"(?:$|[?#])"),
            url or "",
            re.I,
        )
    )


def is_filtered_others_url(url):

    decoded = unquote(url or "")

    return (
        "documentMetadata" in decoded
        and "docCategory=Others" in decoded
        and "docGroup=" in decoded
        and TARGET_ACT in decoded
    )


# ============================================================
# PDF HELPERS
# ============================================================


def looks_like_pdf(body):

    return bool(body and b"%PDF-" in body)


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

                    rawRows:
                        0,

                    realRows:
                        0,

                    dmsLinks:
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

            const rows =
                Array.from(
                    table.querySelectorAll(
                        'tbody > tr'
                    )
                );

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
                            ).length > 0
                        );
                    }
                );

            const dmsLinks =
                table.querySelectorAll(
                    'a.dmslink'
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
                .filter(Boolean);

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

            const info =
                document.getElementById(
                    tableId
                    + '_info'
                );

            const processing =
                document.getElementById(
                    tableId
                    + '_processing'
                );

            const processingVisible =
                processing
                ? (
                    getComputedStyle(
                        processing
                    ).display !== 'none'
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

                rawRows:
                    rows.length,

                realRows:
                    realRows.length,

                dmsLinks:
                    dmsLinks,

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


async def get_initial_table_state(
    frame,
):

    return await get_table_state(
        frame,
        INITIAL_TABLE_ID,
    )


async def get_result_table_state(
    frame,
):

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
            f"rawRows={state.get('rawRows')} "
            f"realRows={state.get('realRows')} "
            f"dmsLinks={state.get('dmsLinks')} "
            f"pageLength={state.get('lengthValue')!r} "
            f"processing={state.get('processingVisible')} "
            f"DT={state.get('dataTableAvailable')} "
            f"DTrows={state.get('dataTableRows')} "
            f"DTlen={state.get('dataTablePageLength')} "
            f"DTdisplay={state.get('recordsDisplay')} "
            f"DTtotal={state.get('recordsTotal')}"
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
# WAIT FOR INITIAL TABLE
# ============================================================


async def wait_for_initial_others_load(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("WAITING FOR INITIAL OTHER DOCUMENTS TABLE")

    print("=" * 78)

    loop = asyncio.get_running_loop()

    started = loop.time()

    previous_signature = None
    stable_checks = 0
    last_log = -1

    while loop.time() - started < INITIAL_TABLE_TIMEOUT_SECONDS:

        state = await get_initial_table_state(frame)

        elapsed = loop.time() - started

        second = int(elapsed)

        signature = (
            state.get("realRows"),
            state.get("dmsLinks"),
            state.get("dataTableRows"),
            state.get("recordsDisplay"),
            state.get("recordsTotal"),
            state.get("processingVisible"),
            tuple(state.get("visibleIds", [])),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            stable_checks = 0
            previous_signature = signature

        if second != last_log:

            print_table_state(
                ("[DEBUG INITIAL " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                "[DEBUG INITIAL] " f"stableChecks={stable_checks}",
                flush=True,
            )

            last_log = second

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

            print("INITIAL OTHER DOCUMENTS TABLE POPULATED")

            print("=" * 78)

            print_table_state(
                "[DEBUG INITIAL FINAL] ",
                state,
            )

            await page.wait_for_timeout(1000)

            return

        await page.wait_for_timeout(250)

    await save_debug(
        page,
        "initial_others_timeout",
    )

    raise RuntimeError("Initial Other Documents table " "did not finish loading.")


# ============================================================
# NAVIGATION
# ============================================================


async def open_home(
    page,
):

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

        raise RuntimeError(f"MCA home HTTP {response.status}")

    await page.wait_for_timeout(1200)


async def find_acts_rules_link(
    page,
):

    selectors = [
        ('a[href="/content/mca/global/en/' 'acts-rules.html"]'),
    ]

    for selector in selectors:

        locator = page.locator(selector)

        for index in range(await locator.count()):

            item = locator.nth(index)

            try:

                if await item.is_visible():

                    return item

            except Exception:

                pass

    return None


async def click_others_tab(
    page,
):

    print()
    print("Searching for Other Documents tab...")

    selectors = [
        (".ebooknavigation " "a.menuClick" '[data-doccategory="Others"]'),
        ('a[data-doccategory="Others"]'),
    ]

    for _ in range(100):

        for frame_index, frame in enumerate(page.frames):

            for selector in selectors:

                locator = frame.locator(selector)

                for index in range(await locator.count()):

                    item = locator.nth(index)

                    try:

                        if not await item.is_visible():

                            continue

                    except Exception:

                        continue

                    print("  Other Documents tab found " f"in frame #{frame_index}")

                    print(
                        "  Selector:",
                        selector,
                    )

                    try:

                        await item.click(
                            timeout=10000,
                        )

                    except Exception:

                        await item.click(
                            force=True,
                        )

                    for _ in range(150):

                        if is_others_url(page.url):

                            return True

                        await page.wait_for_timeout(100)

        await page.wait_for_timeout(100)

    return False


async def find_others_context(
    page,
    timeout_seconds=20,
):

    loop = asyncio.get_running_loop()

    started = loop.time()

    while loop.time() - started < timeout_seconds:

        for frame in page.frames:

            try:

                if await frame.locator("#DropDown_Act").count() > 0:

                    return frame

            except Exception:

                pass

        await page.wait_for_timeout(100)

    return None


async def open_others_module(
    page,
):

    for attempt in range(
        1,
        NAVIGATION_RETRIES + 1,
    ):

        print()
        print("=" * 78)

        print("OTHER DOCUMENTS NAVIGATION ATTEMPT " f"{attempt}/" f"{NAVIGATION_RETRIES}")

        print("=" * 78)

        if not is_home_url(page.url):

            await open_home(page)

        acts_link = await find_acts_rules_link(page)

        if acts_link is None:

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

        for _ in range(200):

            if is_ebooks_url(page.url):

                break

            await page.wait_for_timeout(50)

        print(
            "eBooks page detected:",
            page.url,
        )

        await page.wait_for_timeout(500)

        await click_others_tab(page)

        frame = await find_others_context(
            page,
        )

        if frame is not None:

            print()
            print("=" * 78)

            print("OTHER DOCUMENTS MODULE LOADED")

            print("=" * 78)

            print(
                "Current URL:",
                page.url,
            )

            return frame

        await page.goto(
            OTHERS_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        frame = await find_others_context(
            page,
        )

        if frame is not None:

            return frame

    raise RuntimeError("Could not load Other Documents.")


# ============================================================
# SELECT COMPANIES ACT
# ============================================================


async def wait_for_companies_act_option(
    page,
    frame,
):

    print()
    print("Waiting for Companies Act option...")

    loop = asyncio.get_running_loop()

    started = loop.time()

    while loop.time() - started < ACT_OPTIONS_TIMEOUT_SECONDS:

        dropdown = frame.locator("#DropDown_Act")

        if await dropdown.count() > 0:

            dropdown = dropdown.first

            options = dropdown.locator("option")

            count = await options.count()

            for index in range(count):

                option = options.nth(index)

                text = clean_text(await option.inner_text())

                data_id = await option.get_attribute("data-id") or ""

                if text == TARGET_ACT or data_id == TARGET_ACT_DATA_ID:

                    return (
                        dropdown,
                        index,
                    )

        await page.wait_for_timeout(250)

    raise RuntimeError("Companies Act option not found.")


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
        index,
    ) = await wait_for_companies_act_option(
        page,
        frame,
    )

    print(
        "Initial select_option:",
        await dropdown.select_option(
            index=index,
        ),
    )

    await page.wait_for_timeout(2000)

    locked = await frame.evaluate(
        """
        ({targetText, targetDataId}) => {

            const select =
                document.querySelector(
                    '#DropDown_Act'
                );

            if (!select) {
                return {ok:false};
            }

            const options =
                Array.from(
                    select.options
                );

            let index =
                options.findIndex(
                    o =>
                        (
                            o.getAttribute(
                                'data-id'
                            )
                            || ''
                        )
                        === targetDataId
                );

            if (index < 0) {

                index =
                    options.findIndex(
                        o =>
                            (
                                o.textContent
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
                    ok:false
                };
            }

            select.selectedIndex =
                index;

            options.forEach(
                (o, i) => {

                    o.selected =
                        i === index;
                }
            );

            const go =
                document.querySelector(
                    '#clickGo'
                );

            if (go) {

                go.disabled =
                    false;

                go.removeAttribute(
                    'disabled'
                );
            }

            const selected =
                select.options[index];

            return {

                ok:
                    true,

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

                dataId:
                    selected.getAttribute(
                        'data-id'
                    )
                    || ''
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

    if not locked.get("ok"):

        raise RuntimeError("Could not lock Companies Act.")


# ============================================================
# CLICK GO / RESULT TABLE
# ============================================================


async def click_go_and_wait(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("CLICKING GO")

    print("=" * 78)

    others_request_urls.clear()
    others_response_urls.clear()

    go = frame.locator("#clickGo")

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

    print(
        "Monitoring filtered table:",
        f"#{RESULT_TABLE_ID}",
    )

    loop = asyncio.get_running_loop()

    started = loop.time()

    previous_signature = None

    stable_checks = 0

    last_log = -1

    while loop.time() - started < FILTERED_RESULTS_TIMEOUT_SECONDS:

        request_seen = any(is_filtered_others_url(url) for url in others_request_urls)

        response_seen = any(is_filtered_others_url(url) for url in others_response_urls)

        state = await get_result_table_state(frame)

        elapsed = loop.time() - started

        signature = (
            state.get("realRows"),
            state.get("dmsLinks"),
            state.get("dataTableRows"),
            state.get("recordsTotal"),
            tuple(state.get("visibleIds", [])),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            previous_signature = signature
            stable_checks = 0

        if int(elapsed) != last_log:

            print_table_state(
                ("[DEBUG FILTER " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                (
                    "[DEBUG FILTER] "
                    f"request={request_seen} "
                    f"response={response_seen} "
                    f"stable={stable_checks}"
                )
            )

            last_log = int(elapsed)

        if (
            request_seen
            and response_seen
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
            and stable_checks >= 3
        ):

            print()
            print("=" * 78)

            print("FILTERED RESULT TABLE LOADED")

            print("=" * 78)

            print_table_state(
                "[DEBUG FILTER FINAL] ",
                state,
            )

            await page.wait_for_timeout(1000)

            return

        await page.wait_for_timeout(250)

    await save_debug(
        page,
        "filtered_others_timeout",
    )

    raise RuntimeError("Filtered result table did not load.")


# ============================================================
# SELECT ALL
# ============================================================


async def select_all_results(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("SELECTING FILTERED RESULTS PER PAGE = ALL")

    print("=" * 78)

    dropdown = frame.locator(('select[name="' "notificationCircularResultTable_length" '"]'))

    if await dropdown.count() == 0:

        dropdown = frame.locator(('select[aria-controls="' "notificationCircularResultTable" '"]'))

    if await dropdown.count() == 0:

        raise RuntimeError("Filtered page-length dropdown missing.")

    dropdown = dropdown.first

    print(
        "Selecting All:",
        await dropdown.select_option(value="-1"),
    )

    loop = asyncio.get_running_loop()

    started = loop.time()

    previous_signature = None
    stable_checks = 0

    while loop.time() - started < ALL_RESULTS_TIMEOUT_SECONDS:

        state = await get_result_table_state(frame)

        signature = (
            state.get("realRows"),
            state.get("dmsLinks"),
            state.get("dataTablePageLength"),
            state.get("recordsTotal"),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            previous_signature = signature
            stable_checks = 0

        real_rows = (
            state.get(
                "realRows",
                0,
            )
            or 0
        )

        if (
            state.get("dataTablePageLength") == -1
            and real_rows > 0
            and state.get(
                "dmsLinks",
                0,
            )
            >= real_rows
            and stable_checks >= 3
        ):

            print()
            print("=" * 78)

            print("ALL FILTERED RESULTS STABLE")

            print("=" * 78)

            print_table_state(
                "[DEBUG FINAL ALL] ",
                state,
            )

            print(
                "FINAL FILTERED ROWS:",
                real_rows,
            )

            return real_rows

        await page.wait_for_timeout(250)

    raise RuntimeError("All results did not stabilize.")


# ============================================================
# METADATA
# ============================================================


async def collect_metadata(
    frame,
):

    print()
    print("=" * 78)

    print("COLLECTING METADATA")

    print("=" * 78)

    result = await frame.evaluate("""
        () => {

            const table =
                document.querySelector(
                    '#notificationCircularResultTable'
                );

            const rows =
                Array.from(
                    table.querySelectorAll(
                        'tbody > tr'
                    )
                );

            const output = [];

            for (
                let index = 0;
                index < rows.length;
                index++
            ) {

                const row =
                    rows[index];

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

                if (!cells.length) {
                    continue;
                }

                const link =
                    row.querySelector(
                        'a.dmslink[data-doccategory="Others"]'
                    );

                if (!link) {
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

                let category = '';

                if (
                    cells.length > 1
                ) {

                    category =
                        cells[1];
                }

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

                if (
                    documentId
                    &&
                    date
                    &&
                    particulars
                ) {

                    output.push({

                        document_id:
                            documentId,

                        document_date:
                            date,

                        particulars:
                            particulars,

                        category:
                            category
                    });
                }
            }

            return output;
        }
        """)

    metadata = []

    for item in result:

        item["href"] = build_document_url(item["document_id"])

        metadata.append(item)

    print(
        "Usable documents:",
        len(metadata),
    )

    for index, item in enumerate(metadata[:5]):

        print()
        print(f"[{index + 1}]")

        print(
            " Date:",
            item["document_date"],
        )

        print(
            " Type:",
            item["category"],
        )

        print(
            " Name:",
            item["particulars"],
        )

        print(
            " Filename:",
            build_filename(
                item["document_date"],
                item["particulars"],
                item["category"],
            ),
        )

    return metadata


# ============================================================
# DOWNLOAD
# ============================================================


async def download_pdf_direct(
    context,
    metadata,
    destination,
):

    response = await context.request.get(
        metadata["href"],
        timeout=(DIRECT_HTTP_TIMEOUT_MS),
        fail_on_status_code=False,
        headers={
            "Referer": OTHERS_DIRECT_URL,
            "Accept": ("application/pdf," "application/octet-stream," "*/*"),
        },
    )

    status = response.status

    headers = response.headers

    body = await response.body()

    print(
        "  HTTP status:",
        status,
    )

    print(
        "  Response bytes:",
        len(body),
    )

    if status < 200 or status >= 300:

        error = RuntimeError(f"HTTP {status}")

        error.http_status = status

        raise error

    if not looks_like_pdf(body):

        error = RuntimeError("Response is not PDF")

        error.http_status = status

        raise error

    body = normalize_pdf_bytes(body)

    destination.write_bytes(body)

    return {
        "original_pdf": (
            filename_from_content_disposition(headers) or metadata["document_id"] + ".pdf"
        ),
        "bytes": len(body),
    }


def calculate_retry_delay(
    attempt,
    error,
):

    if (
        getattr(
            error,
            "http_status",
            None,
        )
        == 403
    ):

        return HTTP_403_BASE_DELAY_SECONDS * (2 ** (attempt - 1))

    return RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))


async def download_document(
    context,
    metadata,
    index,
    total,
    manifest_rows,
):

    document_id = metadata["document_id"]

    date = metadata["document_date"]

    particulars = metadata["particulars"]

    category = metadata["category"]

    filename = build_filename(
        date,
        particulars,
        category,
    )

    destination = DOWNLOAD_DIR / filename

    print()
    print("#" * 78)

    print(f"DOCUMENT " f"{index + 1}/" f"{total}")

    print("#" * 78)

    print(
        "Date:",
        date,
    )

    print(
        "Type:",
        category,
    )

    print(
        "PDF Name:",
        particulars,
    )

    print(
        "Saved Filename:",
        filename,
    )

    if destination.exists() and destination.stat().st_size > 0:

        print("ALREADY EXISTS - SKIPPING")

        upsert_manifest_row(
            manifest_rows,
            {
                "table_row": index + 1,
                "document_id": document_id,
                "document_date": date,
                "particulars": particulars,
                "category": category,
                "original_pdf": "",
                "saved_filename": filename,
                "document_url": metadata["href"],
                "status": "already-exists",
            },
        )

        return True

    last_error = None

    for attempt in range(
        1,
        DOWNLOAD_RETRY_ATTEMPTS + 1,
    ):

        print("DOWNLOAD ATTEMPT " f"{attempt}/" f"{DOWNLOAD_RETRY_ATTEMPTS}")

        try:

            result = await download_pdf_direct(
                context,
                metadata,
                destination,
            )

            print(
                "  SUCCESS:",
                destination.name,
            )

            upsert_manifest_row(
                manifest_rows,
                {
                    "table_row": index + 1,
                    "document_id": document_id,
                    "document_date": date,
                    "particulars": particulars,
                    "category": category,
                    "original_pdf": result["original_pdf"],
                    "saved_filename": filename,
                    "document_url": metadata["href"],
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

        if attempt < DOWNLOAD_RETRY_ATTEMPTS:

            delay = calculate_retry_delay(
                attempt,
                last_error,
            )

            print(f"  Retrying in {delay}s...")

            await asyncio.sleep(delay)

    upsert_manifest_row(
        manifest_rows,
        {
            "table_row": index + 1,
            "document_id": document_id,
            "document_date": date,
            "particulars": particulars,
            "category": category,
            "original_pdf": "",
            "saved_filename": filename,
            "document_url": metadata["href"],
            "status": ("ERROR: " + clean_text(str(last_error))),
        },
    )

    return False


async def process_all_documents(
    context,
    frame,
):

    manifest = load_manifest()

    metadata = await collect_metadata(frame)

    total = len(metadata)

    print()
    print(
        "Total documents:",
        total,
    )

    success = 0
    failed = 0

    for index, item in enumerate(metadata):

        result = await download_document(
            context,
            item,
            index,
            total,
            manifest,
        )

        if result:
            success += 1
        else:
            failed += 1

        print((f"[PROGRESS] " f"{index + 1}/{total} | " f"success={success} " f"failed={failed}"))

        if index + 1 < total:

            await asyncio.sleep(INTER_DOWNLOAD_DELAY_SECONDS)


# ============================================================
# MAIN
# ============================================================


async def main():

    started = time.monotonic()

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

            def on_request(request):

                try:

                    url = request.url

                    if "documentMetadata" in url and "docCategory=Others" in url:

                        others_request_urls.append(url)

                        if DEBUG_NETWORK:

                            print(
                                "[REQUEST]",
                                url,
                            )

                except Exception:
                    pass

            def on_response(response):

                try:

                    url = response.url

                    if "documentMetadata" in url:

                        print(
                            "[AJAX]",
                            response.status,
                            url,
                        )

                    if "docCategory=Others" in url:

                        others_response_urls.append(url)

                except Exception:
                    pass

            page.on(
                "request",
                on_request,
            )

            page.on(
                "response",
                on_response,
            )

            await open_home(page)

            frame = await open_others_module(page)

            await wait_for_initial_others_load(
                page,
                frame,
            )

            await select_and_lock_companies_act(
                page,
                frame,
            )

            await click_go_and_wait(
                page,
                frame,
            )

            final_count = await select_all_results(
                page,
                frame,
            )

            print()
            print(
                "Companies Act " "Amendments, Orders & Regulations:",
                final_count,
            )

            await process_all_documents(
                context,
                frame,
            )

    finally:

        print()

        debug("Total runtime: " f"{time.monotonic() - started:.2f}s")

        if browser is not None:

            try:
                await browser.close()
            except Exception:
                pass


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print()
        print("Script stopped.")
