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

FORMS_DIRECT_URL = "https://www.mca.gov.in/content/mca/global/en/" "acts-rules/ebooks/forms.html"

TARGET_ACT = "The Companies Act, 2013"

DOC_CATEGORY = "Forms"

# ------------------------------------------------------------
# Forms-specific selectors taken from MCA JavaScript
# ------------------------------------------------------------

ACT_DROPDOWN_SELECTOR = "#DropDown_FormsAct"

CHAPTER_DROPDOWN_SELECTOR = "#DropDown_FormsChapter"

SECTION_DROPDOWN_SELECTOR = "#DropDown_FormsSection"

GO_BUTTON_SELECTOR = "#clickGo"

INITIAL_CONTAINER_SELECTOR = ".formsTableContainer"

RESULT_CONTAINER_SELECTOR = ".formsResultTableContainer"

RESULT_TABLE_ID = "filteredResulttable"


# ============================================================
# OUTPUT
# ============================================================

OUTPUT_ROOT = Path("mca_companies_act_2013")

DOWNLOAD_DIR = OUTPUT_ROOT / "forms"

DEBUG_DIR = OUTPUT_ROOT / "debug" / "forms"

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

# Normal:
#
# 2 -> 4 -> 8 -> 16
RETRY_BASE_DELAY_SECONDS = 2

# HTTP 403:
#
# 10 -> 20 -> 40 -> 80
HTTP_403_BASE_DELAY_SECONDS = 10

# Delay between different forms
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

forms_request_urls = []

forms_response_urls = []


# ============================================================
# MANIFEST
# ============================================================

MANIFEST_FIELDS = [
    "table_row",
    "document_id",
    "form_name",
    "original_file",
    "saved_filename",
    "document_url",
    "status",
]


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

    form_name = clean_text(
        row_data.get(
            "form_name",
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
                        "form_name",
                        "",
                    )
                )
                == form_name
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
    form_name,
    extension=".pdf",
    max_bytes=245,
):

    name = sanitize_filename_component(strip_size_suffix(form_name))

    extension = extension or ".pdf"

    if not extension.startswith("."):

        extension = "." + extension

    filename = name + extension

    if len(filename.encode("utf-8")) <= max_bytes:

        return filename

    available = max_bytes - len(extension.encode("utf-8"))

    name = truncate_utf8(
        name,
        max(
            30,
            available,
        ),
    )

    return name + extension


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

    # --------------------------------------------------------
    # Forms are downloaded using actionType=download.
    #
    # This matches MCA's dmslink handler for Forms.
    # --------------------------------------------------------

    return (
        "https://www.mca.gov.in/"
        "bin/ebook/dms/getdocument"
        f"?doc={encoded}"
        "&docCategory=Forms"
        "&actionType=download"
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


def is_forms_url(
    url,
):

    return bool(
        re.search(
            (r"/acts-rules/" r"ebooks/" r"forms\.html" r"(?:$|[?#])"),
            url or "",
            re.I,
        )
    )


def is_filtered_forms_url(
    url,
):

    decoded = unquote(url or "")

    return (
        "documentMetadata" in decoded
        and "docCategory=Forms" in decoded
        and "docGroup=" in decoded
        and TARGET_ACT in decoded
    )


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

                    visible:
                        false,

                    rawRows:
                        0,

                    realRows:
                        0,

                    formLinks:
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

            const rect =
                table.getBoundingClientRect();

            const style =
                getComputedStyle(
                    table
                );

            const visible =
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
                            ).length
                            > 0
                        );
                    }
                );

            const formLinks =
                table.querySelectorAll(
                    'a.dmslink[data-doccategory="Forms"]'
                ).length;

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
                                'a.dmslink[data-doccategory="Forms"]'
                            )
                            ||
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

                    const info =
                        dt.page.info();

                    dataTableRows =
                        dt.rows().count();

                    dataTablePageLength =
                        dt.page.len();

                    recordsDisplay =
                        info.recordsDisplay;

                    recordsTotal =
                        info.recordsTotal;
                }

            }
            catch (error) {}

            return {

                tableFound:
                    true,

                tableId:
                    tableId,

                visible:
                    visible,

                rawRows:
                    rows.length,

                realRows:
                    realRows.length,

                formLinks:
                    formLinks,

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


def print_table_state(
    prefix,
    state,
):

    print(
        (
            f"{prefix}"
            f"table={state.get('tableFound')} "
            f"id={state.get('tableId')!r} "
            f"visible={state.get('visible')} "
            f"rawRows={state.get('rawRows')} "
            f"realRows={state.get('realRows')} "
            f"formLinks={state.get('formLinks')} "
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
# FIND INITIAL FORMS TABLE
# ============================================================


async def get_initial_forms_table_state(
    frame,
):

    # --------------------------------------------------------
    # We intentionally do not assume the initial Forms table ID.
    #
    # Find populated/visible table in .formsTableContainer.
    # --------------------------------------------------------

    details = await frame.evaluate("""
        () => {

            const container =
                document.querySelector(
                    '.formsTableContainer'
                );

            if (!container) {

                return {

                    found:
                        false,

                    reason:
                        'formsTableContainer missing'
                };
            }

            const tables =
                Array.from(
                    container.querySelectorAll(
                        'table'
                    )
                );

            if (!tables.length) {

                return {

                    found:
                        false,

                    reason:
                        'no table in formsTableContainer'
                };
            }

            let best = null;

            for (
                let index = 0;
                index < tables.length;
                index++
            ) {

                const table =
                    tables[index];

                const rows =
                    Array.from(
                        table.querySelectorAll(
                            'tbody > tr'
                        )
                    );

                const dmsLinks =
                    table.querySelectorAll(
                        'a.dmslink'
                    ).length;

                const formLinks =
                    table.querySelectorAll(
                        'a.dmslink[data-doccategory="Forms"]'
                    ).length;

                let dtRows =
                    null;

                let dtLength =
                    null;

                let recordsDisplay =
                    null;

                let recordsTotal =
                    null;

                let dtAvailable =
                    false;

                try {

                    if (
                        table.id
                        &&
                        window.jQuery
                        &&
                        jQuery.fn
                        &&
                        jQuery.fn.dataTable
                        &&
                        jQuery.fn.dataTable.isDataTable(
                            '#' + table.id
                        )
                    ) {

                        const dt =
                            jQuery(
                                '#' + table.id
                            )
                            .DataTable();

                        const info =
                            dt.page.info();

                        dtAvailable =
                            true;

                        dtRows =
                            dt.rows().count();

                        dtLength =
                            dt.page.len();

                        recordsDisplay =
                            info.recordsDisplay;

                        recordsTotal =
                            info.recordsTotal;
                    }

                }
                catch (error) {}

                const rect =
                    table.getBoundingClientRect();

                const style =
                    getComputedStyle(
                        table
                    );

                const visible =
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

                const candidate = {

                    index:
                        index,

                    id:
                        table.id || '',

                    visible:
                        visible,

                    rawRows:
                        rows.length,

                    dmsLinks:
                        dmsLinks,

                    formLinks:
                        formLinks,

                    dtAvailable:
                        dtAvailable,

                    dtRows:
                        dtRows,

                    dtLength:
                        dtLength,

                    recordsDisplay:
                        recordsDisplay,

                    recordsTotal:
                        recordsTotal
                };

                if (!best) {

                    best =
                        candidate;

                    continue;
                }

                const candidateScore =
                    (
                        (candidate.visible ? 1000000 : 0)
                        +
                        (candidate.dtRows || 0)
                        +
                        candidate.dmsLinks
                    );

                const bestScore =
                    (
                        (best.visible ? 1000000 : 0)
                        +
                        (best.dtRows || 0)
                        +
                        best.dmsLinks
                    );

                if (
                    candidateScore
                    > bestScore
                ) {

                    best =
                        candidate;
                }
            }

            return {

                found:
                    !!best,

                table:
                    best
            };
        }
        """)

    if not details or not details.get("found"):

        return {
            "tableFound": False,
            "tableId": "",
            "visible": False,
            "rawRows": 0,
            "realRows": 0,
            "formLinks": 0,
            "dmsLinks": 0,
            "lengthValue": None,
            "infoText": "",
            "processingVisible": False,
            "dataTableAvailable": False,
            "dataTableRows": None,
            "dataTablePageLength": None,
            "recordsDisplay": None,
            "recordsTotal": None,
            "visibleIds": [],
        }

    table = details.get("table") or {}

    table_id = clean_text(
        table.get(
            "id",
            "",
        )
    )

    if table_id:

        return await get_table_state(
            frame,
            table_id,
        )

    # --------------------------------------------------------
    # Initial table does not have an ID.
    # Return useful state from discovered object.
    # --------------------------------------------------------

    return {
        "tableFound": True,
        "tableId": "",
        "visible": bool(table.get("visible")),
        "rawRows": table.get(
            "rawRows",
            0,
        ),
        "realRows": table.get(
            "rawRows",
            0,
        ),
        "formLinks": table.get(
            "formLinks",
            0,
        ),
        "dmsLinks": table.get(
            "dmsLinks",
            0,
        ),
        "lengthValue": (str(table.get("dtLength")) if table.get("dtLength") is not None else None),
        "infoText": "",
        "processingVisible": False,
        "dataTableAvailable": bool(table.get("dtAvailable")),
        "dataTableRows": table.get("dtRows"),
        "dataTablePageLength": table.get("dtLength"),
        "recordsDisplay": table.get("recordsDisplay"),
        "recordsTotal": table.get("recordsTotal"),
        "visibleIds": [],
    }


# ============================================================
# RESULT TABLE STATE
# ============================================================


async def get_result_table_state(
    frame,
):

    return await get_table_state(
        frame,
        RESULT_TABLE_ID,
    )


# ============================================================
# WAIT FOR AUTOMATIC INITIAL FORMS LOAD
# ============================================================


async def wait_for_initial_forms_load(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("WAITING FOR INITIAL FORMS TABLE TO POPULATE")

    print("=" * 78)

    loop = asyncio.get_running_loop()

    started = loop.time()

    previous_signature = None

    stable_checks = 0

    last_log = -1

    while loop.time() - started < INITIAL_TABLE_TIMEOUT_SECONDS:

        state = await get_initial_forms_table_state(frame)

        elapsed = loop.time() - started

        second = int(elapsed)

        signature = (
            state.get("tableFound"),
            state.get("tableId"),
            state.get("visible"),
            state.get("realRows"),
            state.get("dmsLinks"),
            state.get("dataTableRows"),
            state.get("dataTablePageLength"),
            state.get("recordsDisplay"),
            state.get("recordsTotal"),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            debug("Initial Forms table changed: " f"{previous_signature!r} " "-> " f"{signature!r}")

            previous_signature = signature

            stable_checks = 0

        if second != last_log:

            print_table_state(
                ("[DEBUG INITIAL " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                ("[DEBUG INITIAL] " f"stableChecks=" f"{stable_checks}"),
                flush=True,
            )

            last_log = second

        rows = (
            state.get(
                "realRows",
                0,
            )
            or 0
        )

        dt_rows = state.get("dataTableRows")

        if (
            state.get("tableFound")
            and rows > 0
            and dt_rows is not None
            and dt_rows > 0
            and not state.get("processingVisible")
            and stable_checks >= 5
        ):

            print()
            print("=" * 78)

            print("INITIAL FORMS TABLE POPULATED")

            print("=" * 78)

            print_table_state(
                "[DEBUG INITIAL FINAL] ",
                state,
            )

            print()
            print("Initial automatic Forms load " "has finished.")

            await page.wait_for_timeout(1000)

            return

        await page.wait_for_timeout(250)

    await save_debug(
        page,
        "initial_forms_load_timeout",
    )

    raise RuntimeError("Initial Forms table " "did not finish populating.")


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
# FORMS TAB
# ============================================================


async def click_forms_tab(
    page,
):

    print()
    print("Searching for Forms tab...")

    selectors = [
        (".ebooknavigation " "a.menuClick" '[data-doccategory="Forms"]'),
        ("a.menuClick" '[data-doccategory="Forms"]'),
        ('a[data-doccategory="Forms"]'),
    ]

    for _ in range(100):

        for frame_index, frame in enumerate(page.frames):

            for selector in selectors:

                locator = frame.locator(selector)

                for index in range(await locator.count()):

                    candidate = locator.nth(index)

                    try:

                        if not await candidate.is_visible():

                            continue

                    except Exception:

                        continue

                    print("  Forms tab found " f"in frame #{frame_index}")

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

                        if is_forms_url(page.url):

                            return True

                        await page.wait_for_timeout(100)

        await page.wait_for_timeout(100)

    return False


# ============================================================
# FIND FORMS CONTEXT
# ============================================================


async def find_forms_context(
    page,
    timeout_seconds=20,
):

    loop = asyncio.get_running_loop()

    started = loop.time()

    while loop.time() - started < timeout_seconds:

        for frame in page.frames:

            try:

                if await frame.locator(ACT_DROPDOWN_SELECTOR).count() > 0:

                    return frame

            except Exception:

                pass

        await page.wait_for_timeout(100)

    return None


# ============================================================
# OPEN FORMS MODULE
# ============================================================


async def open_forms_module(
    page,
):

    for attempt in range(
        1,
        NAVIGATION_RETRIES + 1,
    ):

        print()
        print("=" * 78)

        print("FORMS NAVIGATION ATTEMPT " f"{attempt}/" f"{NAVIGATION_RETRIES}")

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

        await click_forms_tab(page)

        frame = await find_forms_context(
            page,
            timeout_seconds=20,
        )

        if frame is not None:

            print()
            print("=" * 78)

            print("FORMS MODULE LOADED")

            print("=" * 78)

            print(
                "Current URL:",
                page.url,
            )

            print(
                "Forms context:",
                frame.url,
            )

            return frame

        print("Using direct Forms URL...")

        response = await page.goto(
            FORMS_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        print(
            "[DEBUG] Direct Forms HTTP:",
            (response.status if response else None),
        )

        frame = await find_forms_context(
            page,
            timeout_seconds=20,
        )

        if frame is not None:

            return frame

    raise RuntimeError("Could not load Forms module.")


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

    started = loop.time()

    previous_count = None

    while loop.time() - started < ACT_OPTIONS_TIMEOUT_SECONDS:

        dropdown = frame.locator(ACT_DROPDOWN_SELECTOR)

        if await dropdown.count() > 0:

            dropdown = dropdown.first

            options = dropdown.locator("option")

            count = await options.count()

            if count != previous_count:

                debug("Forms Act dropdown option count: " f"{count}")

                previous_count = count

            for index in range(count):

                option = options.nth(index)

                text = clean_text(await option.inner_text())

                value = await option.get_attribute("value") or ""

                if text == TARGET_ACT or value == TARGET_ACT:

                    debug("Companies Act found at " f"option index {index}")

                    return (
                        dropdown,
                        index,
                    )

        await page.wait_for_timeout(250)

    raise RuntimeError("Companies Act option " "not found in Forms dropdown.")


# ============================================================
# SELECT COMPANIES ACT
# ============================================================


async def select_companies_act(
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
        "select_option:",
        result,
    )

    # --------------------------------------------------------
    # Forms uses:
    #
    # var docGroup =
    # $("#DropDown_FormsAct option:selected").val();
    #
    # Therefore selection value itself must be Companies Act.
    # --------------------------------------------------------

    await page.wait_for_timeout(1500)

    selected = await frame.evaluate("""
        () => {

            const select =
                document.querySelector(
                    '#DropDown_FormsAct'
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
                    : ''
            };
        }
        """)

    print(
        "Selected Forms Act:",
        selected,
    )

    if not selected or (selected.get("text") != TARGET_ACT and selected.get("value") != TARGET_ACT):

        raise RuntimeError("Companies Act selection " "was not retained.")


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
                    '#DropDown_FormsAct'
                );

            if (!select) {

                return null;
            }

            const option =
                select.options[
                    select.selectedIndex
                ];

            return {

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
                    : ''
            };
        }
        """)

    print(
        "Selection immediately before Go:",
        selected,
    )

    if not selected or (selected.get("text") != TARGET_ACT and selected.get("value") != TARGET_ACT):

        raise RuntimeError("Companies Act selection " "lost before Go.")

    forms_request_urls.clear()
    forms_response_urls.clear()

    go = frame.locator(GO_BUTTON_SELECTOR)

    if await go.count() == 0:

        raise RuntimeError("Forms Go button missing.")

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
    print("Waiting for filtered Forms RESULT table...")

    print(
        "Monitoring:",
        f"#{RESULT_TABLE_ID}",
    )

    loop = asyncio.get_running_loop()

    started = loop.time()

    request_seen = False

    response_seen = False

    previous_signature = None

    stable_checks = 0

    last_log = -1

    while loop.time() - started < FILTERED_RESULTS_TIMEOUT_SECONDS:

        request_seen = any(is_filtered_forms_url(url) for url in forms_request_urls)

        response_seen = any(is_filtered_forms_url(url) for url in forms_response_urls)

        state = await get_result_table_state(frame)

        elapsed = loop.time() - started

        second = int(elapsed)

        signature = (
            state.get("tableFound"),
            state.get("visible"),
            state.get("realRows"),
            state.get("formLinks"),
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

            debug(
                "Filtered Forms table changed: " f"{previous_signature!r} " "-> " f"{signature!r}"
            )

            previous_signature = signature

            stable_checks = 0

        if second != last_log:

            print_table_state(
                ("[DEBUG FILTERED " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                (
                    "[DEBUG FILTERED] "
                    f"requestSeen="
                    f"{request_seen} "
                    f"responseSeen="
                    f"{response_seen} "
                    f"stableChecks="
                    f"{stable_checks}"
                ),
                flush=True,
            )

            last_log = second

        if (
            request_seen
            and response_seen
            and state.get("tableFound")
            and state.get("dataTableAvailable")
            and state.get(
                "realRows",
                0,
            )
            > 0
            and state.get(
                "formLinks",
                0,
            )
            > 0
            and not state.get("processingVisible")
            and stable_checks >= 3
        ):

            print()
            print("=" * 78)

            print("FILTERED FORMS RESULT TABLE LOADED")

            print("=" * 78)

            print_table_state(
                "[DEBUG FILTER FINAL] ",
                state,
            )

            print(
                "[DEBUG] Visible Form IDs:",
                state.get("visibleIds", []),
            )

            print()
            print("Now selecting All on " "the filtered Forms table...")

            await page.wait_for_timeout(1000)

            return

        await page.wait_for_timeout(250)

    await save_debug(
        page,
        "filtered_forms_timeout",
    )

    print()
    print("Forms requests:")

    for url in forms_request_urls:

        print(
            " REQUEST:",
            url,
        )

    print()
    print("Forms responses:")

    for url in forms_response_urls:

        print(
            " RESPONSE:",
            url,
        )

    raise RuntimeError("Filtered Forms Result table " "did not finish loading.")


# ============================================================
# SELECT ALL
# ============================================================


async def select_all_results(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("SELECTING FILTERED FORMS RESULTS PER PAGE = ALL")

    print("=" * 78)

    before = await get_result_table_state(frame)

    print_table_state(
        "[DEBUG BEFORE ALL] ",
        before,
    )

    dropdown = frame.locator(('select[name="' "filteredResulttable_length" '"]'))

    print(
        "[DEBUG] Exact Forms result length " "dropdown count:",
        await dropdown.count(),
    )

    if await dropdown.count() == 0:

        dropdown = frame.locator(('select[aria-controls="' "filteredResulttable" '"]'))

    if await dropdown.count() == 0:

        await save_debug(
            page,
            "forms_result_length_missing",
        )

        raise RuntimeError("Forms filtered results-per-page " "dropdown missing.")

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
                        .replace(
                            /\\s+/g,
                            ' '
                        )
                        .trim(),

                    selected:
                        option.selected
                })
            )
        """)

    print(
        "[DEBUG] Page-length options:",
        options,
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

        second = int(elapsed)

        signature = (
            state.get("realRows"),
            state.get("formLinks"),
            state.get("lengthValue"),
            state.get("dataTablePageLength"),
            state.get("dataTableRows"),
            state.get("recordsDisplay"),
            state.get("recordsTotal"),
            state.get("processingVisible"),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            debug("Forms All state changed: " f"{previous_signature!r} " "-> " f"{signature!r}")

            previous_signature = signature

            stable_checks = 0

        if second != last_log:

            print_table_state(
                ("[DEBUG ALL " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                ("[DEBUG ALL] " f"stableChecks=" f"{stable_checks}"),
                flush=True,
            )

            last_log = second

        real_rows = (
            state.get(
                "realRows",
                0,
            )
            or 0
        )

        form_links = (
            state.get(
                "formLinks",
                0,
            )
            or 0
        )

        dt_length = state.get("dataTablePageLength")

        length_value = str(
            state.get(
                "lengthValue",
                "",
            )
        )

        if (
            length_value == "-1"
            and dt_length == -1
            and real_rows > 0
            and form_links >= real_rows
            and not state.get("processingVisible")
            and stable_checks >= 3
        ):

            break

        await page.wait_for_timeout(250)

    if final_state is None:

        raise RuntimeError("Could not read final Forms table.")

    if final_state.get("dataTablePageLength") != -1:

        await save_debug(
            page,
            "forms_all_timeout",
        )

        raise RuntimeError("Forms Result table " "did not switch to All.")

    final_count = (
        final_state.get(
            "realRows",
            0,
        )
        or 0
    )

    print()
    print("=" * 78)

    print("ALL FILTERED FORMS STABLE")

    print("=" * 78)

    print_table_state(
        "[DEBUG FINAL ALL] ",
        final_state,
    )

    print(
        "FINAL FILTERED FORM ROWS:",
        final_count,
    )

    print(
        "Time to select/render All:",
        (f"{time.monotonic() - started:.2f}s"),
    )

    if final_count <= 0:

        raise RuntimeError("Filtered Forms result contains " "no rows.")

    return final_count


# ============================================================
# METADATA EXTRACTION
# ============================================================


async def collect_form_metadata(
    frame,
):

    print()
    print("=" * 78)

    print("COLLECTING FILTERED FORM METADATA")

    print("=" * 78)

    started = time.monotonic()

    result = await frame.evaluate("""
        () => {

            const table =
                document.querySelector(
                    '#filteredResulttable'
                );

            if (!table) {

                return {

                    ok:
                        false,

                    error:
                        'filteredResulttable missing',

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
                    tableRows[
                        index
                    ];

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
                    );

                if (
                    cells.length
                    === 0
                ) {

                    continue;
                }

                const downloadLink =
                    row.querySelector(
                        'a.dmslink[data-doccategory="Forms"]'
                    )
                    ||
                    row.querySelector(
                        'a.dmslink'
                    );

                if (!downloadLink) {

                    errors.push({

                        rowIndex:
                            index,

                        reason:
                            'Forms dmslink missing',

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
                        downloadLink.getAttribute(
                            'val'
                        )
                        || ''
                    )
                    .trim();

                /*
                 * First column contains:
                 *
                 * icon + <a>docName | size</a>
                 */

                let name = '';

                if (cells.length > 0) {

                    const nameLink =
                        cells[0].querySelector(
                            'a'
                        );

                    if (nameLink) {

                        name =
                            (
                                nameLink.innerText
                                ||
                                nameLink.textContent
                                ||
                                ''
                            )
                            .replace(
                                /\\s+/g,
                                ' '
                            )
                            .trim();

                    }
                    else {

                        name =
                            (
                                cells[0].innerText
                                || ''
                            )
                            .replace(
                                /\\s+/g,
                                ' '
                            )
                            .trim();
                    }
                }

                if (!documentId) {

                    errors.push({

                        rowIndex:
                            index,

                        reason:
                            'Form document ID missing',

                        text:
                            rowText
                    });

                    continue;
                }

                if (!name) {

                    errors.push({

                        rowIndex:
                            index,

                        reason:
                            'Form name missing',

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

                    form_name:
                        name,

                    doc_category:
                        (
                            downloadLink.getAttribute(
                                'data-doccategory'
                            )
                            || 'Forms'
                        )
                        .trim()
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

        raise RuntimeError("Forms metadata extraction failed: " f"{result!r}")

    print(
        "Raw filtered rows:",
        result.get("rawTableRows"),
    )

    print(
        "Parsed Form rows:",
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

        item["href"] = build_document_url(document_id)

        metadata.append(item)

    print(
        "Usable Forms:",
        len(metadata),
    )

    print(
        "Metadata extraction time:",
        (f"{time.monotonic() - started:.2f}s"),
    )

    if not metadata:

        raise RuntimeError("No Form metadata extracted.")

    print()
    print("FIRST PARSED FORMS")

    for index, item in enumerate(metadata[:5]):

        print()
        print(f"  [{index + 1}]")

        print(
            "    Name:",
            repr(item.get("form_name")),
        )

        print(
            "    Document ID:",
            item.get("document_id"),
        )

        print(
            "    URL:",
            item.get("href"),
        )

    return metadata


# ============================================================
# DOWNLOAD RESPONSE HELPERS
# ============================================================


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


def extension_from_filename(
    filename,
):

    filename = clean_text(filename)

    suffix = Path(filename).suffix

    if suffix:

        return suffix

    return ""


def extension_from_content_type(
    content_type,
):

    value = clean_text(content_type).lower()

    if "pdf" in value:

        return ".pdf"

    if "msword" in value:

        return ".doc"

    if "wordprocessingml" in value:

        return ".docx"

    if "spreadsheetml" in value:

        return ".xlsx"

    if "ms-excel" in value:

        return ".xls"

    if "zip" in value:

        return ".zip"

    return ".pdf"


# ============================================================
# DIRECT FORM DOWNLOAD
# ============================================================


async def download_form_direct(
    context,
    metadata,
):

    url = metadata["href"]

    started = time.monotonic()

    response = await context.request.get(
        url,
        timeout=(DIRECT_HTTP_TIMEOUT_MS),
        fail_on_status_code=False,
        headers={
            "Referer": FORMS_DIRECT_URL,
            "Accept": "*/*",
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

    disposition_name = filename_from_content_disposition(headers)

    body = await response.body()

    elapsed = time.monotonic() - started

    print(
        "  HTTP status:",
        status,
    )

    print(
        "  Content-Type:",
        repr(content_type),
    )

    if disposition_name:

        print(
            "  Server filename:",
            repr(disposition_name),
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

    if not body:

        error = RuntimeError("Empty download response")

        error.http_status = status

        raise error

    # --------------------------------------------------------
    # Forms could theoretically include non-PDF downloads,
    # so preserve server extension where possible.
    # --------------------------------------------------------

    extension = ""

    if disposition_name:

        extension = extension_from_filename(disposition_name)

    if not extension:

        extension = extension_from_content_type(content_type)

    return {
        "body": body,
        "original_file": (disposition_name or (metadata["document_id"] + extension)),
        "extension": extension,
        "bytes": len(body),
        "status": status,
        "elapsed": elapsed,
    }


# ============================================================
# RETRY DELAY
# ============================================================


def calculate_retry_delay(
    attempt,
    error,
):

    status = getattr(
        error,
        "http_status",
        None,
    )

    if status == 403:

        return (
            HTTP_403_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
            "HTTP 403 exponential backoff",
        )

    return (
        RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
        "exponential backoff",
    )


# ============================================================
# DOWNLOAD ONE FORM
# ============================================================


async def download_form(
    context,
    metadata,
    index,
    total,
    manifest_rows,
):

    document_id = clean_text(metadata["document_id"])

    form_name = clean_text(metadata["form_name"])

    url = clean_text(metadata["href"])

    print()
    print("#" * 78)

    print(f"FORM " f"{index + 1}/" f"{total}")

    print("#" * 78)

    print(
        "Document ID:",
        document_id,
    )

    print(
        "Form Name:",
        repr(form_name),
    )

    print("Document URL:")

    print(
        " ",
        url,
    )

    # ========================================================
    # Existing manifest/file detection
    # ========================================================

    existing_manifest = None

    for row in manifest_rows:

        if (
            clean_text(
                row.get(
                    "document_id",
                    "",
                )
            )
            == document_id
        ):

            existing_manifest = row

            break

    if existing_manifest:

        saved_filename = clean_text(
            existing_manifest.get(
                "saved_filename",
                "",
            )
        )

        if saved_filename:

            existing_path = DOWNLOAD_DIR / saved_filename

            if existing_path.exists() and existing_path.stat().st_size > 0:

                print("ALREADY EXISTS - SKIPPING")

                print(
                    "Existing file:",
                    existing_path.name,
                )

                existing_manifest["status"] = "already-exists"

                save_manifest(manifest_rows)

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

            result = await download_form_direct(
                context,
                metadata,
            )

            filename = build_filename(
                form_name,
                extension=(result["extension"]),
            )

            destination = DOWNLOAD_DIR / filename

            destination.write_bytes(result["body"])

            print("  SUCCESS")

            print(
                "  Original file:",
                repr(result["original_file"]),
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
                    "form_name": form_name,
                    "original_file": result["original_file"],
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

            status = getattr(
                exc,
                "http_status",
                None,
            )

            if status is not None:

                print(
                    "  HTTP status from error:",
                    status,
                )

        if attempt < DOWNLOAD_RETRY_ATTEMPTS:

            (
                delay,
                reason,
            ) = calculate_retry_delay(
                attempt,
                last_error,
            )

            print(
                "  Retry strategy:",
                reason,
            )

            print(
                f"  Retrying in {delay}s...",
                flush=True,
            )

            await asyncio.sleep(delay)

    error_text = clean_text(str(last_error or "Unknown failure"))

    upsert_manifest_row(
        manifest_rows,
        {
            "table_row": index + 1,
            "document_id": document_id,
            "form_name": form_name,
            "original_file": "",
            "saved_filename": "",
            "document_url": url,
            "status": ("ERROR: " + error_text),
        },
    )

    return False


# ============================================================
# PROCESS ALL FORMS
# ============================================================


async def process_all_forms(
    context,
    frame,
):

    print()
    print("=" * 78)

    print("FORM DOWNLOAD")

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

    metadata = await collect_form_metadata(frame)

    total = len(metadata)

    print()
    print(
        "Total filtered Forms:",
        total,
    )

    started = time.monotonic()

    successes = 0

    failures = 0

    for index, item in enumerate(metadata):

        result = await download_form(
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

        elapsed = time.monotonic() - started

        average = elapsed / completed

        remaining = total - completed

        eta = average * remaining

        if remaining > 0:

            eta += INTER_DOWNLOAD_DELAY_SECONDS * remaining

        print()
        print(
            (
                "[PROGRESS] "
                f"{completed}/{total} "
                f"({completed / total * 100:.1f}%) | "
                f"success={successes} "
                f"failed={failures} | "
                f"elapsed={elapsed / 60:.1f}m | "
                f"ETA≈{eta / 60:.1f}m"
            ),
            flush=True,
        )

        if completed < total:

            print(
                ("[DELAY] Waiting " f"{INTER_DOWNLOAD_DELAY_SECONDS}s " "before next Form..."),
                flush=True,
            )

            await asyncio.sleep(INTER_DOWNLOAD_DELAY_SECONDS)

    print()
    print("=" * 78)

    print("FINAL SUMMARY")

    print("=" * 78)

    print(
        "Filtered Forms discovered:",
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

            def on_request(
                request,
            ):

                try:

                    url = request.url

                    if "documentMetadata" in url and "docCategory=Forms" in url:

                        forms_request_urls.append(url)

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

            def on_response(
                response,
            ):

                try:

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

                    if "docCategory=Forms" in url:

                        forms_response_urls.append(url)

                except Exception:

                    pass

            page.on(
                "response",
                on_response,
            )

            # =================================================
            # FLOW
            # =================================================

            await open_home(page)

            frame = await open_forms_module(page)

            # =================================================
            # 1. WAIT FOR INITIAL AUTOMATIC FORMS TABLE
            # =================================================

            await wait_for_initial_forms_load(
                page,
                frame,
            )

            # =================================================
            # 2. SELECT COMPANIES ACT
            # =================================================

            await select_companies_act(
                page,
                frame,
            )

            # =================================================
            # 3. CLICK GO
            #
            # After Go, monitor:
            #
            # #filteredResulttable
            #
            # NOT the original Forms table.
            # =================================================

            await click_go_and_wait(
                page,
                frame,
            )

            # =================================================
            # 4. SELECT ALL ON FILTERED RESULT TABLE
            # =================================================

            final_count = await select_all_results(
                page,
                frame,
            )

            print()
            print(
                "Companies Act Forms:",
                final_count,
            )

            # =================================================
            # FINAL TABLE DEBUG
            # =================================================

            if DEBUG_TABLE:

                result_state = await get_result_table_state(frame)

                print_table_state(
                    "[FILTERED FORMS] ",
                    result_state,
                )

            # =================================================
            # 5. DOWNLOAD
            # =================================================

            await process_all_forms(
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
