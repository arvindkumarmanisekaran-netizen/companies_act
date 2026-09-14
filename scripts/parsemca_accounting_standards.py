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

ACCOUNTING_STANDARDS_DIRECT_URL = (
    "https://www.mca.gov.in/content/mca/global/en/" "acts-rules/ebooks/accounting-standards.html"
)

DOC_CATEGORY = "Accounting Standards"

ACCORDION_SELECTOR = "#accordionStandardAccounting"

CARD_SELECTOR = "#accordionStandardAccounting > .card"

CARD_BUTTON_SELECTOR = ".card-header .btn.btn-link"


# ============================================================
# OUTPUT
# ============================================================

OUTPUT_ROOT = Path("mca_companies_act_2013")

DOWNLOAD_DIR = OUTPUT_ROOT / "Accounting Standards"

DEBUG_DIR = OUTPUT_ROOT / "debug" / "Accounting Standards"

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

ACCORDION_TIMEOUT_SECONDS = 60

TABLE_LOAD_TIMEOUT_SECONDS = 60

ALL_RESULTS_TIMEOUT_SECONDS = 60


# ============================================================
# DOWNLOAD / RETRY CONFIGURATION
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


# ============================================================
# MANIFEST
# ============================================================

MANIFEST_FIELDS = [
    "card_index",
    "group_title",
    "reference_no",
    "document_id",
    "description",
    "original_pdf",
    "saved_filename",
    "document_url",
    "status",
]


# ============================================================
# BASIC HELPERS
# ============================================================


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


def debug(message):

    print(
        f"[DEBUG] {message}",
        flush=True,
    )


# ============================================================
# MANIFEST
# ============================================================


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


def manifest_key(row):

    return (
        clean_text(
            row.get(
                "group_title",
                "",
            )
        ),
        clean_text(
            row.get(
                "reference_no",
                "",
            )
        ),
        clean_text(
            row.get(
                "document_id",
                "",
            )
        ),
    )


def upsert_manifest_row(
    manifest_rows,
    row_data,
):

    key = manifest_key(row_data)

    for index, existing in enumerate(manifest_rows):

        if manifest_key(existing) == key:

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


def strip_size_suffix(value):

    value = clean_text(value)

    return re.sub(
        (r"\s*\|\s*" r"\d+(?:\.\d+)?\s*" r"(?:KB|MB|GB)" r"\s*$"),
        "",
        value,
        flags=re.I,
    ).strip()


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


def build_filename(
    group_title,
    reference_no,
    description,
    max_bytes=245,
):

    # ========================================================
    # NAMING CONVENTION
    #
    # Group - Reference No - Description.pdf
    # ========================================================

    group_title = sanitize_filename_component(group_title)

    reference_no = sanitize_filename_component(reference_no)

    description = sanitize_filename_component(strip_size_suffix(description))

    prefix = f"{group_title} - " f"{reference_no} - "

    suffix = ".pdf"

    filename = prefix + description + suffix

    if len(filename.encode("utf-8")) <= max_bytes:

        return filename

    fixed_bytes = len((prefix + suffix).encode("utf-8"))

    available = max_bytes - fixed_bytes

    description = truncate_utf8(
        description,
        max(
            20,
            available,
        ),
    )

    return prefix + description + suffix


# ============================================================
# DMS URL
# ============================================================


def encode_document_id(document_id):

    return base64.b64encode(str(document_id).encode("utf-8")).decode("ascii")


def build_document_url(document_id):

    encoded = encode_document_id(document_id)

    # Confirmed from MCA dmslink handler.

    return (
        "https://www.mca.gov.in/"
        "bin/ebook/dms/getdocument"
        f"?doc={encoded}"
        "&docCategory=Accounting%20Standards"
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


def is_accounting_standards_url(url):

    return bool(
        re.search(
            (r"/acts-rules/" r"ebooks/" r"accounting-standards\.html" r"(?:$|[?#])"),
            url or "",
            re.I,
        )
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


def filename_from_content_disposition(headers):

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
# DEBUG FILES
# ============================================================


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
# ACTS & RULES
# ============================================================


async def find_acts_rules_link(page):

    selectors = [
        (".second-navigation " 'a[href="/content/mca/global/en/' 'acts-rules.html"]'),
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


# ============================================================
# ACCOUNTING STANDARDS TAB
# ============================================================


async def click_accounting_standards_tab(page):

    print()
    print("Searching for Accounting Standards tab...")

    selectors = [
        (".ebooknavigation " "a.menuClick" '[data-doccategory="Accounting Standards"]'),
        ("a.menuClick" '[data-doccategory="Accounting Standards"]'),
        ('a[data-doccategory="Accounting Standards"]'),
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

                    print("  Accounting Standards tab found " f"in frame #{frame_index}")

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

                        if is_accounting_standards_url(page.url):

                            return True

                        await page.wait_for_timeout(100)

        await page.wait_for_timeout(100)

    return False


# ============================================================
# FIND PAGE CONTEXT
# ============================================================


async def find_accounting_context(
    page,
    timeout_seconds=30,
):

    loop = asyncio.get_running_loop()

    started = loop.time()

    while loop.time() - started < timeout_seconds:

        for frame in page.frames:

            try:

                if await frame.locator(ACCORDION_SELECTOR).count() > 0:

                    return frame

            except Exception:

                pass

        await page.wait_for_timeout(100)

    return None


# ============================================================
# OPEN ACCOUNTING STANDARDS
# ============================================================


async def open_accounting_standards_module(
    page,
):

    for attempt in range(
        1,
        NAVIGATION_RETRIES + 1,
    ):

        print()
        print("=" * 78)

        print("ACCOUNTING STANDARDS NAVIGATION ATTEMPT " f"{attempt}/" f"{NAVIGATION_RETRIES}")

        print("=" * 78)

        if not is_home_url(page.url):

            await open_home(page)

        acts_link = await find_acts_rules_link(page)

        if acts_link is None:

            debug("Acts & Rules link missing.")

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

        await click_accounting_standards_tab(page)

        frame = await find_accounting_context(
            page,
            timeout_seconds=20,
        )

        if frame is not None:

            print()
            print("=" * 78)

            print("ACCOUNTING STANDARDS MODULE LOADED")

            print("=" * 78)

            print(
                "Current URL:",
                page.url,
            )

            print(
                "Accounting Standards context:",
                frame.url,
            )

            return frame

        print("Using direct Accounting Standards URL...")

        response = await page.goto(
            ACCOUNTING_STANDARDS_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        print(
            "[DEBUG] Direct HTTP:",
            (response.status if response else None),
        )

        frame = await find_accounting_context(
            page,
            timeout_seconds=30,
        )

        if frame is not None:

            return frame

    raise RuntimeError("Could not load Accounting Standards.")


# ============================================================
# WAIT FOR ACCORDION
# ============================================================


async def wait_for_accordion(
    page,
    frame,
):

    print()
    print("=" * 78)

    print("WAITING FOR ACCOUNTING STANDARDS ACCORDION")

    print("=" * 78)

    await frame.locator(ACCORDION_SELECTOR).wait_for(
        state="attached",
        timeout=(ACCORDION_TIMEOUT_SECONDS * 1000),
    )

    loop = asyncio.get_running_loop()

    started = loop.time()

    previous_count = None

    stable_checks = 0

    while loop.time() - started < ACCORDION_TIMEOUT_SECONDS:

        cards = frame.locator(CARD_SELECTOR)

        count = await cards.count()

        if count == previous_count:

            stable_checks += 1

        else:

            print(
                "[DEBUG] Accordion card count:",
                count,
            )

            previous_count = count

            stable_checks = 0

        if count > 0 and stable_checks >= 4:

            print()
            print(
                "Accounting Standards groups:",
                count,
            )

            return count

        await page.wait_for_timeout(250)

    raise RuntimeError("Accounting Standards accordion " "did not stabilize.")


# ============================================================
# GROUP TITLE
# ============================================================


async def get_card_title(card):

    button = card.locator(CARD_BUTTON_SELECTOR)

    if await button.count() == 0:

        return ""

    title = clean_text(await button.first.inner_text())

    # Remove visual + / - if included in text.

    title = re.sub(
        r"\s*[+\-]\s*$",
        "",
        title,
    ).strip()

    return title


# ============================================================
# CARD TABLE STATE
# ============================================================


async def get_card_table_state(card):

    return await card.evaluate("""
        card => {

            const table =
                card.querySelector(
                    'table'
                );

            if (!table) {

                return {

                    tableFound:
                        false,

                    tableId:
                        '',

                    rawRows:
                        0,

                    realRows:
                        0,

                    links:
                        0,

                    pageLength:
                        null,

                    infoText:
                        '',

                    parsedStart:
                        null,

                    parsedEnd:
                        null,

                    parsedTotal:
                        null
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

            const links =
                table.querySelectorAll(
                    'a.dmslink[data-doccategory="Accounting Standards"]'
                ).length;

            /*
             * IMPORTANT:
             *
             * Everything is scoped to THIS CARD.
             */

            const wrapper =
                table.closest(
                    '.dataTables_wrapper'
                );

            let lengthSelect = null;

            if (wrapper) {

                lengthSelect =
                    wrapper.querySelector(
                        '.dataTables_length select'
                    );
            }

            if (!lengthSelect) {

                lengthSelect =
                    card.querySelector(
                        '.dataTables_length select'
                    );
            }

            let infoElement = null;

            if (wrapper) {

                infoElement =
                    wrapper.querySelector(
                        '.dataTables_info'
                    );
            }

            if (!infoElement) {

                infoElement =
                    card.querySelector(
                        '.dataTables_info'
                    );
            }

            const infoText =
                infoElement
                ? (
                    infoElement.innerText
                    || ''
                )
                .replace(
                    /\\s+/g,
                    ' '
                )
                .trim()
                : '';

            let parsedStart =
                null;

            let parsedEnd =
                null;

            let parsedTotal =
                null;

            /*
             * Examples:
             *
             * Showing Results 1-5 of 28
             * Showing Results 1-28 of 28
             */

            let match =
                infoText.match(
                    /Showing\\s+Results\\s+(\\d+)\\s*-\\s*(\\d+)\\s+of\\s+(\\d+)/i
                );

            if (match) {

                parsedStart =
                    parseInt(
                        match[1],
                        10
                    );

                parsedEnd =
                    parseInt(
                        match[2],
                        10
                    );

                parsedTotal =
                    parseInt(
                        match[3],
                        10
                    );
            }
            else {

                match =
                    infoText.match(
                        /\\bof\\s+(\\d+)\\b/i
                    );

                if (match) {

                    parsedTotal =
                        parseInt(
                            match[1],
                            10
                        );
                }
            }

            return {

                tableFound:
                    true,

                tableId:
                    table.id || '',

                rawRows:
                    rows.length,

                realRows:
                    realRows.length,

                links:
                    links,

                pageLength:
                    lengthSelect
                    ? lengthSelect.value
                    : null,

                infoText:
                    infoText,

                parsedStart:
                    parsedStart,

                parsedEnd:
                    parsedEnd,

                parsedTotal:
                    parsedTotal
            };
        }
        """)


def print_card_table_state(
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
            f"links={state.get('links')} "
            f"pageLength={state.get('pageLength')!r} "
            f"start={state.get('parsedStart')} "
            f"end={state.get('parsedEnd')} "
            f"total={state.get('parsedTotal')}"
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
# WAIT FOR EACH CARD'S INITIAL TABLE
# ============================================================


async def wait_for_card_table(
    page,
    card,
    title,
):

    print()
    print("Waiting for card table to populate...")

    loop = asyncio.get_running_loop()

    started = loop.time()

    previous_signature = None

    stable_checks = 0

    last_log = -1

    while loop.time() - started < TABLE_LOAD_TIMEOUT_SECONDS:

        state = await get_card_table_state(card)

        elapsed = loop.time() - started

        signature = (
            state.get("realRows"),
            state.get("links"),
            state.get("pageLength"),
            state.get("parsedTotal"),
            state.get("infoText"),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            stable_checks = 0

            previous_signature = signature

        if int(elapsed) != last_log:

            print_card_table_state(
                ("[DEBUG TABLE " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                ("[DEBUG TABLE] " f"stableChecks=" f"{stable_checks}"),
                flush=True,
            )

            last_log = int(elapsed)

        if (
            state.get("tableFound")
            and state.get(
                "realRows",
                0,
            )
            > 0
            and state.get(
                "links",
                0,
            )
            > 0
            and state.get("parsedTotal") is not None
            and state.get("parsedTotal") > 0
            and stable_checks >= 3
        ):

            print("Table ready:")

            print_card_table_state(
                "[DEBUG READY] ",
                state,
            )

            return state

        await page.wait_for_timeout(250)

    raise RuntimeError("Accounting Standards table " f"did not populate for: {title}")


# ============================================================
# SET CURRENT CARD TO ALL
# ============================================================


async def select_all_in_card(
    page,
    card,
    title,
):

    print()
    print("Changing Results per page to All...")

    # ========================================================
    # DO NOT USE PLAYWRIGHT VISIBILITY.
    #
    # The entire accordion body may be hidden.
    #
    # Use browser-side JavaScript directly.
    # ========================================================

    change_result = await card.evaluate("""
        card => {

            const table =
                card.querySelector(
                    'table'
                );

            if (!table) {

                return {

                    ok:
                        false,

                    reason:
                        'table missing'
                };
            }

            const wrapper =
                table.closest(
                    '.dataTables_wrapper'
                );

            let select = null;

            if (wrapper) {

                select =
                    wrapper.querySelector(
                        '.dataTables_length select'
                    );
            }

            if (!select) {

                select =
                    card.querySelector(
                        '.dataTables_length select'
                    );
            }

            if (!select) {

                return {

                    ok:
                        false,

                    reason:
                        'page length select missing'
                };
            }

            const options =
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
                            .trim()
                    })
                );

            const hasAll =
                options.some(
                    option =>
                        option.value
                        === '-1'
                );

            if (!hasAll) {

                return {

                    ok:
                        false,

                    reason:
                        'All option missing',

                    options:
                        options
                };
            }

            const before =
                select.value;

            /*
             * Set native DOM value first.
             */

            select.value =
                '-1';

            /*
             * MCA uses jQuery / DataTables.
             *
             * Trigger jQuery change so the existing
             * page-length handler redraws THIS table.
             */

            if (
                window.jQuery
            ) {

                jQuery(
                    select
                )
                .val(
                    '-1'
                )
                .trigger(
                    'change'
                );
            }
            else {

                select.dispatchEvent(
                    new Event(
                        'change',
                        {
                            bubbles:
                                true
                        }
                    )
                );
            }

            return {

                ok:
                    true,

                before:
                    before,

                after:
                    select.value,

                options:
                    options,

                tableId:
                    table.id || ''
            };
        }
        """)

    print(
        "[DEBUG] Change to All:",
        change_result,
    )

    if not change_result or not change_result.get("ok"):

        raise RuntimeError("Could not change card to All: " f"{title}: " f"{change_result!r}")

    # ========================================================
    # WAIT UNTIL RENDERED ROWS == DYNAMIC TOTAL
    # ========================================================

    loop = asyncio.get_running_loop()

    started = loop.time()

    previous_signature = None

    stable_checks = 0

    last_log = -1

    retriggered = False

    while loop.time() - started < ALL_RESULTS_TIMEOUT_SECONDS:

        state = await get_card_table_state(card)

        elapsed = loop.time() - started

        signature = (
            state.get("realRows"),
            state.get("links"),
            state.get("pageLength"),
            state.get("parsedStart"),
            state.get("parsedEnd"),
            state.get("parsedTotal"),
            state.get("infoText"),
        )

        if signature == previous_signature:

            stable_checks += 1

        else:

            stable_checks = 0

            previous_signature = signature

        if int(elapsed) != last_log:

            print_card_table_state(
                ("[DEBUG ALL " f"+{elapsed:05.2f}s] "),
                state,
            )

            print(
                ("[DEBUG ALL] " f"stableChecks=" f"{stable_checks}"),
                flush=True,
            )

            last_log = int(elapsed)

        real_rows = (
            state.get(
                "realRows",
                0,
            )
            or 0
        )

        links = (
            state.get(
                "links",
                0,
            )
            or 0
        )

        total = state.get("parsedTotal")

        page_length = str(
            state.get(
                "pageLength",
                "",
            )
        )

        # ====================================================
        # If first change event did not redraw, send another
        # event after 2 seconds.
        # ====================================================

        if not retriggered and elapsed >= 2 and total is not None and real_rows < total:

            print("[DEBUG] Table has not expanded yet. " "Triggering All change again...")

            retry_result = await card.evaluate("""
                card => {

                    const table =
                        card.querySelector(
                            'table'
                        );

                    const wrapper =
                        table
                        ? table.closest(
                            '.dataTables_wrapper'
                        )
                        : null;

                    const select =
                        (
                            wrapper
                            ? wrapper.querySelector(
                                '.dataTables_length select'
                            )
                            : null
                        )
                        ||
                        card.querySelector(
                            '.dataTables_length select'
                        );

                    if (!select) {

                        return {

                            ok:
                                false
                        };
                    }

                    select.value =
                        '-1';

                    if (
                        window.jQuery
                    ) {

                        jQuery(
                            select
                        )
                        .val(
                            '-1'
                        )
                        .trigger(
                            'change'
                        );
                    }
                    else {

                        select.dispatchEvent(
                            new Event(
                                'change',
                                {
                                    bubbles:
                                        true
                                }
                            )
                        );
                    }

                    return {

                        ok:
                            true,

                        value:
                            select.value
                    };
                }
                """)

            print(
                "[DEBUG] Retrigger result:",
                retry_result,
            )

            retriggered = True

            stable_checks = 0

            await page.wait_for_timeout(300)

            continue

        # ====================================================
        # COMPLETE
        #
        # Dynamic. No expected total hard-coded.
        # ====================================================

        if (
            page_length == "-1"
            and total is not None
            and total > 0
            and real_rows == total
            and links >= real_rows
            and stable_checks >= 3
        ):

            print()
            print("ALL ROWS LOADED")

            print(
                "Group:",
                title,
            )

            print_card_table_state(
                "[DEBUG ALL FINAL] ",
                state,
            )

            return real_rows

        await page.wait_for_timeout(250)

    raise RuntimeError("Could not render All rows for: " f"{title}")


# ============================================================
# EXTRACT ONE CARD
# ============================================================


async def extract_card_metadata(
    card,
    group_title,
    card_index,
):

    result = await card.evaluate("""
        card => {

            const table =
                card.querySelector(
                    'table'
                );

            if (!table) {

                return {

                    ok:
                        false,

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

                const cells =
                    Array.from(
                        row.querySelectorAll(
                            'td'
                        )
                    );

                if (
                    cells.length < 2
                ) {

                    continue;
                }

                const referenceNo =
                    (
                        cells[0].innerText
                        ||
                        cells[0].textContent
                        ||
                        ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim();

                const link =
                    row.querySelector(
                        'a.dmslink[data-doccategory="Accounting Standards"]'
                    )
                    ||
                    row.querySelector(
                        'a.dmslink'
                    );

                if (!link) {

                    errors.push({

                        rowIndex:
                            index,

                        reason:
                            'dmslink missing'
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

                const description =
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

                if (
                    !referenceNo
                    ||
                    !documentId
                    ||
                    !description
                ) {

                    errors.push({

                        rowIndex:
                            index,

                        reason:
                            'required data missing',

                        referenceNo:
                            referenceNo,

                        documentId:
                            documentId,

                        description:
                            description
                    });

                    continue;
                }

                rows.push({

                    reference_no:
                        referenceNo,

                    document_id:
                        documentId,

                    description:
                        description
                });
            }

            return {

                ok:
                    true,

                rawRows:
                    tableRows.length,

                rows:
                    rows,

                errors:
                    errors
            };
        }
        """)

    if not result.get("ok"):

        raise RuntimeError(f"Could not extract group: " f"{group_title}")

    rows = result.get("rows") or []

    errors = result.get("errors") or []

    print(
        "Raw rows:",
        result.get("rawRows"),
    )

    print(
        "Parsed rows:",
        len(rows),
    )

    print(
        "Metadata errors:",
        len(errors),
    )

    for error in errors[:5]:

        print(
            "[DEBUG METADATA ERROR]",
            error,
        )

    metadata = []

    for row in rows:

        description = strip_size_suffix(row["description"])

        document_id = row["document_id"]

        metadata.append(
            {
                "card_index": card_index + 1,
                "group_title": group_title,
                "reference_no": row["reference_no"],
                "document_id": document_id,
                "description": description,
                "document_url": build_document_url(document_id),
                "saved_filename": build_filename(
                    group_title,
                    row["reference_no"],
                    description,
                ),
            }
        )

    return metadata


# ============================================================
# COLLECT ALL CARDS
# ============================================================


async def collect_all_metadata(
    page,
    frame,
):

    group_count = await wait_for_accordion(
        page,
        frame,
    )

    all_metadata = []

    for card_index in range(group_count):

        # Re-resolve card every iteration.

        cards = frame.locator(CARD_SELECTOR)

        current_count = await cards.count()

        if card_index >= current_count:

            raise RuntimeError("Accordion card count " "changed unexpectedly.")

        card = cards.nth(card_index)

        title = await get_card_title(card)

        if not title:

            title = "Accounting Standards Group " f"{card_index + 1}"

        print()
        print("=" * 78)

        print((f"GROUP {card_index + 1}/" f"{group_count}: " f"{title}"))

        print("=" * 78)

        # ====================================================
        # NOTE:
        #
        # We intentionally DO NOT require accordion expansion.
        #
        # MCA's data-target and actual collapse IDs can differ.
        # ====================================================

        initial_state = await wait_for_card_table(
            page,
            card,
            title,
        )

        print()
        print(
            "Initial visible rows:",
            initial_state.get("realRows"),
        )

        print(
            "Dynamic total:",
            initial_state.get("parsedTotal"),
        )

        total_rows = await select_all_in_card(
            page,
            card,
            title,
        )

        print(
            "Rows after All:",
            total_rows,
        )

        group_metadata = await extract_card_metadata(
            card,
            title,
            card_index,
        )

        print(
            "Extracted documents:",
            len(group_metadata),
        )

        if len(group_metadata) != total_rows:

            print()
            print("WARNING:")

            print(
                "  Rendered rows:",
                total_rows,
            )

            print(
                "  Extracted rows:",
                len(group_metadata),
            )

        for item in group_metadata[:3]:

            print()
            print(
                "  Reference:",
                item["reference_no"],
            )

            print(
                "  Description:",
                item["description"],
            )

            print(
                "  Document ID:",
                item["document_id"],
            )

            print(
                "  Filename:",
                item["saved_filename"],
            )

        all_metadata.extend(group_metadata)

        print()
        print(("[GROUP COMPLETE] " f"{card_index + 1}/" f"{group_count}"))

    # ========================================================
    # DEDUPE
    # ========================================================

    unique = []

    seen = set()

    for item in all_metadata:

        key = (
            clean_text(item["group_title"]),
            clean_text(item["reference_no"]),
            clean_text(item["document_id"]),
        )

        if key in seen:

            continue

        seen.add(key)

        unique.append(item)

    print()
    print("=" * 78)

    print("ACCOUNTING STANDARDS METADATA COMPLETE")

    print("=" * 78)

    print(
        "Groups processed:",
        group_count,
    )

    print(
        "Entries collected:",
        len(all_metadata),
    )

    print(
        "Unique entries:",
        len(unique),
    )

    return unique


# ============================================================
# DIRECT PDF DOWNLOAD
# ============================================================


async def download_pdf_direct(
    context,
    metadata,
    destination,
):

    started = time.monotonic()

    response = await context.request.get(
        metadata["document_url"],
        timeout=(DIRECT_HTTP_TIMEOUT_MS),
        fail_on_status_code=False,
        headers={
            "Referer": ACCOUNTING_STANDARDS_DIRECT_URL,
            "Accept": ("application/pdf," "application/octet-stream," "*/*"),
        },
    )

    status = response.status

    headers = response.headers

    body = await response.body()

    elapsed = time.monotonic() - started

    content_type = clean_text(
        headers.get(
            "content-type",
            "",
        )
    )

    print(
        "  HTTP status:",
        status,
    )

    print(
        "  Content-Type:",
        repr(content_type),
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

    original_pdf = filename_from_content_disposition(headers) or metadata["document_id"] + ".pdf"

    return {
        "original_pdf": original_pdf,
        "bytes": len(body),
        "http_status": status,
    }


# ============================================================
# RETRY
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
# DOWNLOAD ONE DOCUMENT
# ============================================================


async def download_document(
    context,
    metadata,
    index,
    total,
    manifest,
):

    destination = DOWNLOAD_DIR / metadata["saved_filename"]

    print()
    print("#" * 78)

    print(("ACCOUNTING STANDARD " f"{index + 1}/" f"{total}"))

    print("#" * 78)

    print(
        "Group:",
        metadata["group_title"],
    )

    print(
        "Reference:",
        metadata["reference_no"],
    )

    print(
        "Description:",
        metadata["description"],
    )

    print(
        "Document ID:",
        metadata["document_id"],
    )

    print(
        "Saved filename:",
        destination.name,
    )

    print(
        "Document URL:",
        metadata["document_url"],
    )

    # ========================================================
    # RESUME
    # ========================================================

    if destination.exists() and destination.stat().st_size > 0:

        print("ALREADY EXISTS - SKIPPING")

        upsert_manifest_row(
            manifest,
            {
                "card_index": metadata["card_index"],
                "group_title": metadata["group_title"],
                "reference_no": metadata["reference_no"],
                "document_id": metadata["document_id"],
                "description": metadata["description"],
                "original_pdf": "",
                "saved_filename": destination.name,
                "document_url": metadata["document_url"],
                "status": "already-exists",
            },
        )

        return True

    last_error = None

    for attempt in range(
        1,
        DOWNLOAD_RETRY_ATTEMPTS + 1,
    ):

        print()
        print(("DOWNLOAD ATTEMPT " f"{attempt}/" f"{DOWNLOAD_RETRY_ATTEMPTS}"))

        try:

            result = await download_pdf_direct(
                context,
                metadata,
                destination,
            )

            print("  SUCCESS")

            print(
                "  Original PDF:",
                result["original_pdf"],
            )

            print(
                "  Saved bytes:",
                result["bytes"],
            )

            upsert_manifest_row(
                manifest,
                {
                    "card_index": metadata["card_index"],
                    "group_title": metadata["group_title"],
                    "reference_no": metadata["reference_no"],
                    "document_id": metadata["document_id"],
                    "description": metadata["description"],
                    "original_pdf": result["original_pdf"],
                    "saved_filename": destination.name,
                    "document_url": metadata["document_url"],
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

            try:

                if destination.exists():

                    destination.unlink()

            except Exception:

                pass

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
                (f"  Retrying in " f"{delay}s..."),
                flush=True,
            )

            await asyncio.sleep(delay)

    upsert_manifest_row(
        manifest,
        {
            "card_index": metadata["card_index"],
            "group_title": metadata["group_title"],
            "reference_no": metadata["reference_no"],
            "document_id": metadata["document_id"],
            "description": metadata["description"],
            "original_pdf": "",
            "saved_filename": destination.name,
            "document_url": metadata["document_url"],
            "status": ("ERROR: " + clean_text(str(last_error))),
        },
    )

    return False


# ============================================================
# PROCESS DOWNLOADS
# ============================================================


async def process_downloads(
    context,
    metadata,
):

    print()
    print("=" * 78)

    print("ACCOUNTING STANDARDS DOWNLOAD")

    print("=" * 78)

    manifest = load_manifest()

    total = len(metadata)

    print(
        "Documents:",
        total,
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
        "Retry attempts:",
        DOWNLOAD_RETRY_ATTEMPTS,
    )

    print(
        "Delay between downloads:",
        (f"{INTER_DOWNLOAD_DELAY_SECONDS}s"),
    )

    success = 0
    failed = 0

    started = time.monotonic()

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

        completed = index + 1

        elapsed = time.monotonic() - started

        remaining = total - completed

        average = elapsed / completed

        eta = average * remaining

        if remaining > 0:

            eta += INTER_DOWNLOAD_DELAY_SECONDS * remaining

        print()
        print(
            (
                "[PROGRESS] "
                f"{completed}/{total} "
                f"("
                f"{completed / total * 100:.1f}%"
                f") | "
                f"success={success} "
                f"failed={failed} | "
                f"elapsed="
                f"{elapsed / 60:.1f}m | "
                f"ETA≈"
                f"{eta / 60:.1f}m"
            ),
            flush=True,
        )

        if completed < total:

            print(
                ("[DELAY] Waiting " f"{INTER_DOWNLOAD_DELAY_SECONDS}s " "before next PDF..."),
                flush=True,
            )

            await asyncio.sleep(INTER_DOWNLOAD_DELAY_SECONDS)

    print()
    print("=" * 78)

    print("FINAL SUMMARY")

    print("=" * 78)

    print(
        "Documents discovered:",
        total,
    )

    print(
        "Successful/skipped:",
        success,
    )

    print(
        "Failed:",
        failed,
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
            # NETWORK DEBUG
            # =================================================

            def on_request(request):

                try:

                    url = request.url

                    if "documentMetadata" in url or "/bin/ebook/dms/getdocument" in url:

                        if DEBUG_NETWORK:

                            print(
                                "[REQUEST]",
                                url,
                                flush=True,
                            )

                except Exception:

                    pass

            def on_response(response):

                try:

                    url = response.url

                    if "documentMetadata" in url:

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
                "request",
                on_request,
            )

            page.on(
                "response",
                on_response,
            )

            # =================================================
            # NAVIGATE
            # =================================================

            await open_home(page)

            frame = await open_accounting_standards_module(page)

            # =================================================
            # PROCESS EVERY CARD WITHOUT REQUIRING EXPANSION
            # =================================================

            metadata = await collect_all_metadata(
                page,
                frame,
            )

            # =================================================
            # DOWNLOAD
            # =================================================

            await process_downloads(
                context,
                metadata,
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

        debug("Total runtime: " f"{time.monotonic() - program_started:.2f}s")

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
