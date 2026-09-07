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

NOTIFICATIONS_DIRECT_URL = (
    "https://www.mca.gov.in/content/mca/global/en/" "acts-rules/ebooks/notifications.html"
)

TARGET_ACT = "The Companies Act, 2013"
TARGET_ACT_DATA_ID = "J105_D"

OUTPUT_ROOT = Path("mca_companies_act_2013")

DOWNLOAD_DIR = OUTPUT_ROOT / "notifications"

DEBUG_DIR = OUTPUT_ROOT / "debug" / "notifications"

MANIFEST_FILE = DOWNLOAD_DIR / "downloads.csv"

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DEBUG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

HEADLESS = True

DEFAULT_TIMEOUT = 30000

NAVIGATION_RETRIES = 10
ACT_OPTIONS_TIMEOUT_SECONDS = 60
RESULTS_TIMEOUT_SECONDS = 60
ALL_RESULTS_TIMEOUT_SECONDS = 60

# ============================================================
# DOWNLOAD / RETRY CONFIGURATION
# ============================================================

DOWNLOAD_RETRY_ATTEMPTS = 5

# Normal exponential backoff:
# attempt 1 failure -> 2s
# attempt 2 failure -> 4s
# attempt 3 failure -> 8s
# attempt 4 failure -> 16s
RETRY_BASE_DELAY_SECONDS = 2

# HTTP 403 gets a more conservative delay:
# attempt 1 -> 10s
# attempt 2 -> 20s
# attempt 3 -> 40s
# attempt 4 -> 80s
HTTP_403_BASE_DELAY_SECONDS = 10

# Delay between separate documents
INTER_DOWNLOAD_DELAY_SECONDS = 5

DIRECT_HTTP_TIMEOUT_MS = 120000

DEBUG_NETWORK = True
DEBUG_TABLE = True


# ============================================================
# GLOBAL REQUEST TRACKING
# ============================================================

notification_request_urls = []


# ============================================================
# MANIFEST
# ============================================================

MANIFEST_FIELDS = [
    "table_row",
    "document_id",
    "notification_date",
    "particulars",
    "original_pdf",
    "saved_filename",
    "document_url",
    "status",
]


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


def save_manifest(
    rows,
):

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
            "notification_date",
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
                        "notification_date",
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
# TEXT HELPERS
# ============================================================


def clean_text(
    value,
):

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


def sanitize_filename_component(
    value,
):

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


def sortable_notification_date(
    value,
):

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


def strip_size_suffix(
    value,
):

    value = clean_text(value)

    return re.sub(
        (r"\s*\|\s*" r"\d+(?:\.\d+)?\s*" r"(?:KB|MB|GB)" r"\s*$"),
        "",
        value,
        flags=re.I,
    ).strip()


def build_filename(
    notification_date,
    particulars,
    max_bytes=245,
):

    date = sortable_notification_date(notification_date)

    date = sanitize_filename_component(date)

    particulars = strip_size_suffix(particulars)

    particulars = sanitize_filename_component(particulars)

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
# MCA DOCUMENT URL
# ============================================================


def encode_document_id(
    document_id,
):

    return base64.b64encode(str(document_id).encode("utf-8")).decode("ascii")


def build_document_url(
    document_id,
    doc_category="Notifications",
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


def is_home_url(
    url,
):

    return bool(
        re.search(
            r"/home\.html(?:$|[?#])",
            url or "",
            re.I,
        )
    )


def is_ebooks_url(
    url,
):

    return bool(
        re.search(
            r"/acts-rules/ebooks\.html(?:$|[?#])",
            url or "",
            re.I,
        )
    )


def is_notifications_url(
    url,
):

    return bool(
        re.search(
            (r"/acts-rules/" r"ebooks/" r"notifications\.html" r"(?:$|[?#])"),
            url or "",
            re.I,
        )
    )


# ============================================================
# PDF HELPERS
# ============================================================


def looks_like_pdf(
    body,
):

    if not body:
        return False

    return b"%PDF-" in body


def normalize_pdf_bytes(
    body,
):

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


def debug(
    message,
):

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
# FAST DATATABLE STATE
# ============================================================


async def get_notification_table_state(
    frame,
):

    return await frame.evaluate("""
        () => {

            const table =
                document.querySelector(
                    '#notificationCircularResultTable'
                );

            const tbody =
                table
                ? table.querySelector(
                    'tbody'
                )
                : null;

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

            const notificationLinks =
                table
                    ? table.querySelectorAll(
                        'a.notifications.dmslink'
                    ).length
                    : 0;

            const dmsLinks =
                table
                    ? table.querySelectorAll(
                        'a.dmslink'
                    ).length
                    : 0;

            const lengthSelect =
                document.querySelector(
                    'select[name="notificationCircularResultTable_length"]'
                )
                ||
                document.querySelector(
                    'select[aria-controls="notificationCircularResultTable"]'
                );

            const info =
                document.querySelector(
                    '#notificationCircularResultTable_info'
                );

            const processing =
                document.querySelector(
                    '#notificationCircularResultTable_processing'
                );

            const processingVisible =
                processing
                ? (
                    getComputedStyle(
                        processing
                    ).display !== 'none'
                    &&
                    getComputedStyle(
                        processing
                    ).visibility !== 'hidden'
                )
                : false;

            let dataTableAvailable =
                false;

            let dataTableRows =
                null;

            let dataTablePageLength =
                null;

            let dataTableInfo =
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
                        '#notificationCircularResultTable'
                    )
                ) {

                    dataTableAvailable =
                        true;

                    const dt =
                        jQuery(
                            '#notificationCircularResultTable'
                        )
                        .DataTable();

                    dataTableRows =
                        dt.rows().count();

                    dataTablePageLength =
                        dt.page.len();

                    dataTableInfo =
                        dt.page.info();
                }

            }
            catch (error) {

                dataTableInfo = {
                    error:
                        String(error)
                };
            }

            return {

                tableFound:
                    !!table,

                rawRows:
                    rows.length,

                realRows:
                    realRows.length,

                notificationLinks:
                    notificationLinks,

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

                processingFound:
                    !!processing,

                processingVisible:
                    processingVisible,

                processingText:
                    processing
                    ? (
                        processing.innerText
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim()
                    : '',

                dataTableAvailable:
                    dataTableAvailable,

                dataTableRows:
                    dataTableRows,

                dataTablePageLength:
                    dataTablePageLength,

                dataTableInfo:
                    dataTableInfo
            };
        }
        """)


def print_table_state(
    prefix,
    state,
):

    print(
        (
            f"{prefix}"
            f"table={state.get('tableFound')} "
            f"rawRows={state.get('rawRows')} "
            f"realRows={state.get('realRows')} "
            f"notificationLinks="
            f"{state.get('notificationLinks')} "
            f"dmsLinks={state.get('dmsLinks')} "
            f"pageLength={state.get('lengthValue')!r} "
            f"processing="
            f"{state.get('processingVisible')} "
            f"DT={state.get('dataTableAvailable')} "
            f"DTrows={state.get('dataTableRows')} "
            f"DTlen={state.get('dataTablePageLength')}"
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
# HOME
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

        raise RuntimeError("MCA home returned " f"HTTP {response.status}")

    await page.wait_for_timeout(1200)


# ============================================================
# ACTS & RULES
# ============================================================


async def find_acts_rules_link(
    page,
):

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
# NOTIFICATIONS TAB
# ============================================================


async def click_notifications_tab(
    page,
):

    print()
    print("Searching for Notifications tab...")

    selectors = [
        (".ebooknavigation " "a.menuClick" '[data-doccategory="Notifications"]'),
        ("a.menuClick" '[data-doccategory="Notifications"]'),
        ('a[data-doccategory="Notifications"]'),
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

                    print("  Notifications tab found " f"in frame #{frame_index}")

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

                        if is_notifications_url(page.url):

                            return True

                        await page.wait_for_timeout(100)

        await page.wait_for_timeout(100)

    return False


# ============================================================
# FIND NOTIFICATIONS CONTEXT
# ============================================================


async def find_notifications_context(
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
# OPEN NOTIFICATIONS MODULE
# ============================================================


async def open_notifications_module(
    page,
):

    for attempt in range(
        1,
        NAVIGATION_RETRIES + 1,
    ):

        print()
        print("=" * 78)

        print("NOTIFICATIONS NAVIGATION ATTEMPT " f"{attempt}/" f"{NAVIGATION_RETRIES}")

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

            debug("eBooks URL not detected.")

            continue

        print(
            "eBooks page detected:",
            page.url,
        )

        await page.wait_for_timeout(500)

        clicked = await click_notifications_tab(page)

        if not clicked:

            debug("Notifications tab did not navigate.")

        frame = await find_notifications_context(
            page,
            timeout_seconds=20,
        )

        if frame is not None:

            print()
            print("=" * 78)

            print("NOTIFICATIONS MODULE LOADED")

            print("=" * 78)

            print(
                "Current URL:",
                page.url,
            )

            print(
                "Notifications context:",
                frame.url,
            )

            return frame

        print("Using direct Notifications URL...")

        response = await page.goto(
            NOTIFICATIONS_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        print(
            "[DEBUG] Direct notifications HTTP:",
            response.status if response else None,
        )

        frame = await find_notifications_context(
            page,
            timeout_seconds=20,
        )

        if frame is not None:

            return frame

    raise RuntimeError("Could not load Notifications module.")


# ============================================================
# COMPANIES ACT OPTION
# ============================================================


async def wait_for_companies_act_option(
    page,
    frame,
):

    print()
    print("Waiting for Companies Act option...")

    loop = asyncio.get_running_loop()

    start = loop.time()

    last_option_count = None

    while loop.time() - start < ACT_OPTIONS_TIMEOUT_SECONDS:

        dropdown = frame.locator("#DropDown_Act")

        if await dropdown.count() > 0:

            dropdown = dropdown.first

            options = dropdown.locator("option")

            option_count = await options.count()

            if option_count != last_option_count:

                debug("Act dropdown option count: " f"{option_count}")

                last_option_count = option_count

            for index in range(option_count):

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
# SELECT + LOCK COMPANIES ACT
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

    debug("Waiting 2 seconds for MCA " "onchange handler...")

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
                    .replace(/\\s+/g, ' ')
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
                    ok: false,
                    reason:
                        'dropdown missing'
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
                    ok: false,
                    reason:
                        'target option missing'
                };
            }

            options.forEach(
                (option, optionIndex) => {

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
                    go.disabled = false;
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
                    .replace(/\\s+/g, ' ')
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

    if locked.get("text") != TARGET_ACT and locked.get("dataId") != TARGET_ACT_DATA_ID:

        raise RuntimeError("Wrong Act selected after lock.")


# ============================================================
# CLICK GO + VERIFY FILTER
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
                    .replace(/\\s+/g, ' ')
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

    go = frame.locator("#clickGo")

    if await go.count() == 0:

        raise RuntimeError("Go button missing.")

    notification_request_urls.clear()

    started = time.monotonic()

    try:

        await go.first.click(
            timeout=15000,
        )

    except Exception:

        await go.first.click(
            force=True,
        )

    print("Go clicked.")

    loop = asyncio.get_running_loop()

    start = loop.time()

    filtered_seen = False
    last_print = -1

    while loop.time() - start < RESULTS_TIMEOUT_SECONDS:

        for request_url in notification_request_urls:

            decoded = unquote(request_url)

            if (
                "docCategory=Notifications" in decoded
                and "docGroup=" in decoded
                and TARGET_ACT in decoded
            ):

                filtered_seen = True
                break

        state = await get_notification_table_state(frame)

        elapsed = int(loop.time() - start)

        if elapsed != last_print:

            print_table_state(
                (f"[DEBUG GO +{elapsed:02d}s] "),
                state,
            )

            last_print = elapsed

        if (
            filtered_seen
            and state.get(
                "realRows",
                0,
            )
            > 0
        ):

            print()
            print("FILTERED REQUEST VERIFIED")

            for request_url in notification_request_urls:

                decoded = unquote(request_url)

                if "docGroup=" in decoded:

                    print(
                        " ",
                        request_url,
                    )

            debug("Go/filter stage finished in " f"{time.monotonic() - started:.2f}s")

            return

        await page.wait_for_timeout(250)

    raise RuntimeError("Companies Act filtered " "results did not load.")


# ============================================================
# SELECT ALL
# ============================================================


async def select_all_results(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("SELECTING RESULTS PER PAGE = ALL")

    print("=" * 78)

    before = await get_notification_table_state(frame)

    print_table_state(
        "[DEBUG BEFORE ALL] ",
        before,
    )

    dropdown = frame.locator(('select[name="' "notificationCircularResultTable_length" '"]'))

    if await dropdown.count() == 0:

        dropdown = frame.locator(('select[aria-controls="' "notificationCircularResultTable" '"]'))

    if await dropdown.count() == 0:

        raise RuntimeError("Results-per-page " "dropdown missing.")

    dropdown = dropdown.first

    options = await dropdown.evaluate("""
        select =>
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
                        .replace(/\\s+/g, ' ')
                        .trim(),

                    selected:
                        option.selected
                })
            )
        """)

    debug(f"Page-length options: {options!r}")

    started = time.monotonic()

    try:

        selected = await dropdown.select_option(value="-1")

    except Exception:

        selected = await dropdown.select_option(label="All")

    print(
        "Selected All:",
        selected,
    )

    loop = asyncio.get_running_loop()

    start = loop.time()

    previous_signature = None
    stable_checks = 0
    last_log_time = -1

    final_state = None

    while loop.time() - start < ALL_RESULTS_TIMEOUT_SECONDS:

        state = await get_notification_table_state(frame)

        final_state = state

        elapsed_float = loop.time() - start

        elapsed_second = int(elapsed_float)

        signature = (
            state.get("realRows"),
            state.get("notificationLinks"),
            state.get("lengthValue"),
            state.get("processingVisible"),
            state.get("dataTableRows"),
            state.get("dataTablePageLength"),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            stable_checks = 0

            debug("Table state changed: " f"{previous_signature!r} " "-> " f"{signature!r}")

            previous_signature = signature

        if elapsed_second != last_log_time:

            print_table_state(
                (f"[DEBUG ALL " f"+{elapsed_float:05.2f}s] "),
                state,
            )

            print(
                ("[DEBUG ALL] " f"stableChecks={stable_checks}"),
                flush=True,
            )

            last_log_time = elapsed_second

        real_rows = (
            state.get(
                "realRows",
                0,
            )
            or 0
        )

        page_length = str(
            state.get(
                "lengthValue",
                "",
            )
        )

        processing = bool(
            state.get(
                "processingVisible",
                False,
            )
        )

        if real_rows > 5 and page_length == "-1" and not processing and stable_checks >= 3:

            debug("All-results table is stable.")

            break

        await page.wait_for_timeout(250)

    if final_state is None:

        raise RuntimeError("Could not read final " "DataTable state.")

    final_count = (
        final_state.get(
            "realRows",
            0,
        )
        or 0
    )

    print()
    print("=" * 78)

    print("ALL RESULTS STABLE")

    print("=" * 78)

    print_table_state(
        "[DEBUG FINAL ALL] ",
        final_state,
    )

    print(
        "FINAL FILTERED NOTIFICATION ROWS:",
        final_count,
    )

    print(
        "Time to select/render All:",
        f"{time.monotonic() - started:.2f}s",
    )

    if final_count <= 5:

        await save_debug(
            page,
            "all_results_did_not_expand",
        )

        raise RuntimeError("Selecting All did not " "expand the result table.")

    if final_count >= 800:

        await save_debug(
            page,
            "unfiltered_all_acts_results",
        )

        raise RuntimeError(
            f"Got {final_count} rows. "
            "This appears to be "
            "all-Acts data. "
            "Refusing to download."
        )

    return final_count


# ============================================================
# FAST METADATA EXTRACTION
# ============================================================


async def collect_notification_metadata(
    frame,
):

    print()
    print("=" * 78)

    print("COLLECTING NOTIFICATION METADATA")

    print("=" * 78)

    started = time.monotonic()

    result = await frame.evaluate("""
        () => {

            const table =
                document.querySelector(
                    '#notificationCircularResultTable'
                );

            if (!table) {

                return {
                    ok: false,
                    error:
                        'notification table not found',
                    rows: []
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
                            'a.dmslink[data-doccategory="Notifications"]'
                        );
                }

                if (!link) {

                    errors.push({
                        rowIndex:
                            index,

                        reason:
                            'notification link missing',

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
                        || link.textContent
                        || ''
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
                            'val/document ID missing',

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

                    notification_date:
                        date,

                    particulars:
                        particulars
                        || ariaLabel,

                    doc_category:
                        docCategory
                        || 'Notifications',

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

        raise RuntimeError("Metadata extraction failed: " f"{result!r}")

    print(
        "Raw table rows:",
        result.get("rawTableRows"),
    )

    print(
        "Parsed notification rows:",
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

    rows = result.get("rows") or []

    metadata = []

    for item in rows:

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

            doc_category = "Notifications"

        item["href"] = build_document_url(
            document_id,
            doc_category,
        )

        metadata.append(item)

    print(
        "Usable notifications:",
        len(metadata),
    )

    print(
        "Metadata extraction time:",
        f"{time.monotonic() - started:.2f}s",
    )

    if not metadata:

        raise RuntimeError("No notification metadata " "was extracted.")

    table_state = await get_notification_table_state(frame)

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
            "  Real table rows:",
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

            raise RuntimeError("Too many notification rows " "failed metadata extraction.")

    print()
    print("FIRST PARSED NOTIFICATIONS")

    for index, item in enumerate(metadata[:3]):

        print()
        print(f"  [{index + 1}]")

        print(
            "    Date:",
            item.get("notification_date"),
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
# DIRECT DOWNLOAD
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
            "Referer": NOTIFICATIONS_DIRECT_URL,
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
# CALCULATE RETRY DELAY
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
# DOWNLOAD ONE
# ============================================================


async def download_notification(
    context,
    metadata,
    index,
    total,
    manifest_rows,
):

    document_id = clean_text(metadata["document_id"])

    date = clean_text(metadata["notification_date"])

    particulars = clean_text(metadata["particulars"])

    url = clean_text(metadata["href"])

    filename = build_filename(
        date,
        particulars,
    )

    destination = DOWNLOAD_DIR / filename

    print()
    print("#" * 78)

    print(f"NOTIFICATION " f"{index + 1}/" f"{total}")

    print("#" * 78)

    print(
        "Document ID:",
        document_id,
    )

    print(
        "Notification Date:",
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
    # RESUME / EXISTING FILE
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
                    "notification_date": date,
                    "particulars": particulars,
                    "original_pdf": "",
                    "saved_filename": destination.name,
                    "document_url": url,
                    "status": "already-exists",
                },
            )

            return True

    # ========================================================
    # DOWNLOAD WITH EXPONENTIAL RETRIES
    # ========================================================

    last_error = None

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
                    "notification_date": date,
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
                f"  Retrying in " f"{retry_delay}s...",
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
            "notification_date": date,
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


async def process_all_notifications(
    context,
    frame,
):

    print()
    print("=" * 78)

    print("NOTIFICATION DOWNLOAD")

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

    metadata = await collect_notification_metadata(frame)

    total = len(metadata)

    print()
    print(
        "Total notification documents:",
        total,
    )

    download_started = time.monotonic()

    successes = 0
    failures = 0

    for index, item in enumerate(metadata):

        result = await download_notification(
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

        elapsed = time.monotonic() - download_started

        completed = index + 1

        average = elapsed / completed

        remaining = total - completed

        # Add expected 5-second inter-document delay
        # to make ETA more realistic.
        eta_seconds = average * remaining

        if remaining > 0:

            eta_seconds += INTER_DOWNLOAD_DELAY_SECONDS * remaining

        print()
        print(
            (
                "[PROGRESS] "
                f"{completed}/{total} "
                f"({completed / total * 100:.1f}%) | "
                f"success={successes} "
                f"failed={failures} | "
                f"elapsed={elapsed / 60:.1f}m | "
                f"ETA≈{eta_seconds / 60:.1f}m"
            ),
            flush=True,
        )

        # ====================================================
        # 5 SECOND DELAY BETWEEN DOCUMENTS
        # ====================================================

        if completed < total:

            print(
                ("[DELAY] Waiting " f"{INTER_DOWNLOAD_DELAY_SECONDS}s " "before next document..."),
                flush=True,
            )

            await asyncio.sleep(INTER_DOWNLOAD_DELAY_SECONDS)

    rows = load_manifest()

    downloaded = sum(1 for row in rows if (row.get("status") == "downloaded"))

    skipped = sum(1 for row in rows if (row.get("status") == "already-exists"))

    errors = sum(1 for row in rows if (row.get("status", "").startswith("ERROR")))

    print()
    print("=" * 78)

    print("FINAL SUMMARY")

    print("=" * 78)

    print(
        "Documents discovered:",
        total,
    )

    print(
        "Downloaded:",
        downloaded,
    )

    print(
        "Already existed:",
        skipped,
    )

    print(
        "Errors:",
        errors,
    )

    print(
        "Output:",
        DOWNLOAD_DIR.resolve(),
    )

    print(
        "Manifest:",
        MANIFEST_FILE.resolve(),
    )

    print(
        "Total download runtime:",
        f"{(time.monotonic() - download_started) / 60:.2f} minutes",
    )


# ============================================================
# MAIN
# ============================================================


async def main():

    program_started = time.monotonic()

    async with async_playwright() as p:

        print()

        print("Launching " + ("HEADLESS" if HEADLESS else "VISIBLE") + " Firefox...")

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

        # ====================================================
        # REQUEST DEBUG
        # ====================================================

        def on_request(
            request,
        ):

            try:

                url = request.url

                if (
                    "/bin/ebook/service/" "documentMetadata" in url
                    and "docCategory=Notifications" in url
                ):

                    notification_request_urls.append(url)

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

        # ====================================================
        # RESPONSE DEBUG
        # ====================================================

        async def on_response(
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

            except Exception:

                pass

        page.on(
            "response",
            on_response,
        )

        try:

            # =================================================
            # HOME
            # =================================================

            await open_home(page)

            # =================================================
            # NOTIFICATIONS MODULE
            # =================================================

            frame = await open_notifications_module(page)

            # =================================================
            # SELECT COMPANIES ACT
            # =================================================

            await select_and_lock_companies_act(
                page,
                frame,
            )

            # =================================================
            # GO
            # =================================================

            await click_go_and_wait(
                page,
                frame,
            )

            # =================================================
            # SELECT ALL
            # =================================================

            final_count = await select_all_results(
                page,
                frame,
            )

            print()
            print(
                "Companies Act notifications:",
                final_count,
            )

            # =================================================
            # FINAL TABLE DEBUG
            # =================================================

            if DEBUG_TABLE:

                state = await get_notification_table_state(frame)

                print_table_state(
                    "[DEBUG BEFORE DOWNLOAD] ",
                    state,
                )

            # =================================================
            # DOWNLOAD
            # =================================================

            await process_all_notifications(
                context,
                frame,
            )

        except Exception as exc:

            print()
            print("=" * 78)

            print(
                "FATAL ERROR:",
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

            raise

        finally:

            print()

            debug("Total program runtime: " f"{time.monotonic() - program_started:.2f}s")

            await browser.close()


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print()
        print("Script stopped.")
