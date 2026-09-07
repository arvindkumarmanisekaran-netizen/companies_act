#!/usr/bin/env python3

import asyncio
import base64
import csv
import re
from pathlib import Path
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qs,
    unquote,
)

from playwright.async_api import (
    async_playwright,
)

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

# Each Go strategy gets this long.
GO_ATTEMPT_WAIT_SECONDS = 25

DOWNLOAD_RETRY_ATTEMPTS = 3
DOWNLOAD_RETRY_DELAY_SECONDS = 2

DIRECT_HTTP_TIMEOUT_MS = 120000

POPUP_WAIT_SECONDS = 20


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

    except Exception:
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

    notification_date = clean_text(
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
        existing_document_id = clean_text(
            existing.get(
                "document_id",
                "",
            )
        )

        same = False

        if document_id and existing_document_id:
            same = document_id == existing_document_id

        else:
            same = (
                clean_text(
                    existing.get(
                        "notification_date",
                        "",
                    )
                )
                == notification_date
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
# TEXT / FILENAME HELPERS
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
    particulars,
):
    """
    Example:

    G.S.R. 725(E)-.... Rules, 2026. | 804KB

    becomes:

    G.S.R. 725(E)-.... Rules, 2026.
    """

    text = clean_text(particulars)

    text = re.sub(
        (r"\s*\|\s*" r"\d+(?:\.\d+)?\s*" r"(?:KB|MB|GB)" r"\s*$"),
        "",
        text,
        flags=re.I,
    )

    return text.strip()


def build_filename(
    notification_date,
    particulars,
    max_bytes=245,
):
    date_part = sortable_notification_date(notification_date)

    date_part = sanitize_filename_component(date_part)

    title = strip_size_suffix(particulars)

    title = sanitize_filename_component(title)

    prefix = f"{date_part} - "

    suffix = ".pdf"

    filename = prefix + title + suffix

    if len(filename.encode("utf-8")) <= max_bytes:
        return filename

    available = max_bytes - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8"))

    available = max(
        30,
        available,
    )

    title = truncate_utf8(
        title,
        available,
    )

    return prefix + title + suffix


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


def is_notifications_url(url):
    return bool(
        re.search(
            (r"/acts-rules/ebooks/" r"notifications\.html" r"(?:$|[?#])"),
            url or "",
            re.I,
        )
    )


def decode_document_id_from_url(
    url,
):
    """
    Example:

    doc=Njc1OTQ4NjUx

    ->

    675948651
    """

    try:
        query = parse_qs(urlparse(url).query)

        encoded = (query.get("doc") or [""])[0]

        if not encoded:
            return ""

        encoded += "=" * (-len(encoded) % 4)

        decoded = base64.b64decode(encoded).decode(
            "utf-8",
            errors="ignore",
        )

        return clean_text(decoded)

    except Exception:
        return ""


# ============================================================
# PDF HELPERS
# ============================================================


def looks_like_pdf(
    data,
):
    if not data:
        return False

    return data.find(b"%PDF-") >= 0


def normalize_pdf_bytes(
    data,
):
    position = data.find(b"%PDF-")

    if position < 0:
        return data

    return data[position:]


def filename_from_content_disposition(
    headers,
):
    if not headers:
        return ""

    disposition = ""

    for key, value in headers.items():
        if key.lower() == "content-disposition":
            disposition = value or ""
            break

    if not disposition:
        return ""

    # --------------------------------------------------------
    # filename*=UTF-8''name.pdf
    # --------------------------------------------------------

    match = re.search(
        (r"filename\*\s*=\s*" r"(?:UTF-8''|utf-8'')?" r"([^;]+)"),
        disposition,
        re.I,
    )

    if match:
        value = match.group(1).strip().strip("\"'")

        return clean_text(unquote(value))

    # --------------------------------------------------------
    # filename="name.pdf"
    # --------------------------------------------------------

    match = re.search(
        r'filename\s*=\s*"([^"]+)"',
        disposition,
        re.I,
    )

    if match:
        return clean_text(match.group(1))

    # --------------------------------------------------------
    # filename=name.pdf
    # --------------------------------------------------------

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
            "  Screenshot:",
            screenshot.resolve(),
        )

    except Exception:
        pass

    for frame_index, frame in enumerate(page.frames):
        try:
            html = await frame.content()

            html_file = DEBUG_DIR / (f"{safe_name}_" f"frame_{frame_index}.html")

            html_file.write_text(
                html,
                encoding="utf-8",
            )

        except Exception:
            pass


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

    if response is not None:
        print(
            "HTTP status:",
            response.status,
        )

    await page.wait_for_timeout(1500)

    print(
        "URL:",
        page.url,
    )

    if response is not None and response.status >= 400:
        raise RuntimeError("MCA home returned " f"HTTP {response.status}")


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

        count = await locator.count()

        for index in range(count):
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


async def click_notifications_real(
    page,
):
    print()
    print("Searching for Notifications tab...")

    selectors = [
        (".ebooknavigation " "a.menuClick" '[data-doccategory="Notifications"]'),
        ("a.menuClick" '[data-doccategory="Notifications"]'),
        ('a[data-doccategory="Notifications"]'),
        ('a[val="Notifications"]'),
        ('a[data-redirect="' '/ebooks/notifications.html"]'),
    ]

    for _ in range(100):
        for frame_index, frame in enumerate(page.frames):
            for selector in selectors:
                try:
                    candidates = frame.locator(selector)

                    count = await candidates.count()

                except Exception:
                    continue

                for index in range(count):
                    candidate = candidates.nth(index)

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

                    return False

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
                select = frame.locator("#DropDown_Act")

                if await select.count() > 0:
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
            print("Acts & Rules link not found.")

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

        for _ in range(250):
            if is_ebooks_url(page.url):
                ebooks_seen = True
                break

            await page.wait_for_timeout(50)

        if not ebooks_seen:
            print("eBooks page not detected.")

            continue

        print(
            "eBooks page detected:",
            page.url,
        )

        await page.wait_for_timeout(500)

        clicked = await click_notifications_real(page)

        if clicked:
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

        print("Using direct Notifications " "URL fallback...")

        response = await page.goto(
            NOTIFICATIONS_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        print(
            "Direct URL HTTP:",
            (response.status if response else None),
        )

        frame = await find_notifications_context(
            page,
            timeout_seconds=20,
        )

        if frame is not None:
            return frame

    raise RuntimeError("Could not load " "Notifications module.")


# ============================================================
# FIND ACT DROPDOWN
# ============================================================


async def find_act_dropdown(
    page,
    frame,
):
    print()
    print("Searching for Act dropdown containing " f"{TARGET_ACT!r}...")

    loop = asyncio.get_running_loop()

    start = loop.time()

    while loop.time() - start < ACT_OPTIONS_TIMEOUT_SECONDS:
        preferred = frame.locator("#DropDown_Act")

        if await preferred.count() > 0:
            dropdown = preferred.first

            options = dropdown.locator("option")

            for option_index in range(await options.count()):
                option = options.nth(option_index)

                try:
                    text = clean_text(await option.inner_text())

                    data_id = await option.get_attribute("data-id") or ""

                except Exception:
                    continue

                if text == TARGET_ACT or data_id == TARGET_ACT_DATA_ID:
                    print("Act dropdown found.")

                    print(
                        "  id:",
                        repr(await dropdown.get_attribute("id")),
                    )

                    return (
                        dropdown,
                        option_index,
                    )

        await page.wait_for_timeout(250)

    raise RuntimeError("The Companies Act, 2013 " "option was not found.")


# ============================================================
# SELECT COMPANIES ACT
# ============================================================


async def select_companies_act(
    page,
    frame,
):
    (
        dropdown,
        option_index,
    ) = await find_act_dropdown(
        page,
        frame,
    )

    print()
    print("Selecting " "The Companies Act, 2013...")

    selected = await dropdown.select_option(
        index=option_index,
    )

    print(
        "select_option result:",
        selected,
    )

    # --------------------------------------------------------
    # MCA has inline onchange handlers. Although select_option
    # already fires input/change, explicitly dispatch them
    # again and call MCA's enable function if it exists.
    # --------------------------------------------------------

    state = await dropdown.evaluate("""
        select => {
            try {
                select.dispatchEvent(
                    new Event(
                        'input',
                        {
                            bubbles: true
                        }
                    )
                );
            }
            catch (e) {}

            try {
                select.dispatchEvent(
                    new Event(
                        'change',
                        {
                            bubbles: true
                        }
                    )
                );
            }
            catch (e) {}

            try {
                if (
                    typeof window
                        .enableclickGoButton
                    === 'function'
                ) {
                    window
                        .enableclickGoButton();
                }
            }
            catch (e) {}

            const option =
                select.options[
                    select.selectedIndex
                ];

            const go =
                document.querySelector(
                    '#clickGo'
                );

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
                        ) || ''
                    )
                    : '',

                goFound:
                    !!go,

                goDisabled:
                    go
                    ? !!go.disabled
                    : null,

                goDisabledAttribute:
                    go
                    ? go.getAttribute(
                        'disabled'
                    )
                    : null,

                goDisabled1:
                    go
                    ? go.getAttribute(
                        'disabled1'
                    )
                    : null
            };
        }
        """)

    print(
        "Selected:",
        {
            "index": state.get("index"),
            "text": state.get("text"),
            "value": state.get("value"),
            "dataId": state.get("dataId"),
        },
    )

    print(
        "Go state after selection:",
        {
            "found": state.get("goFound"),
            "disabled": state.get("goDisabled"),
            "disabled-attr": state.get("goDisabledAttribute"),
            "disabled1": state.get("goDisabled1"),
        },
    )

    if state.get("dataId") != TARGET_ACT_DATA_ID and state.get("text") != TARGET_ACT:
        raise RuntimeError("Wrong Act selected.")

    # Give MCA change handlers a moment.
    await page.wait_for_timeout(750)


# ============================================================
# NOTIFICATION LOCATOR
# ============================================================


def notifications_link_locator(
    frame,
):
    return frame.locator(
        (
            "a#notifications.dmslink, "
            "a.dmslink#notifications, "
            'a[id="notifications"].dmslink, '
            '[id="notifications"].dmslink'
        )
    )


# ============================================================
# RESULTS CHECK
# ============================================================


async def notification_result_state(
    frame,
):
    try:
        links = notifications_link_locator(frame)

        count = await links.count()

    except Exception:
        count = 0

    table_exists = False
    rows = 0
    processing_text = ""

    # --------------------------------------------------------
    # Known DataTables ID
    # --------------------------------------------------------

    try:
        table = frame.locator("#notificationCircularResultTable")

        table_exists = await table.count() > 0

        if table_exists:
            rows = await table.locator("tbody tr").count()

    except Exception:
        pass

    # --------------------------------------------------------
    # DataTables processing message
    # --------------------------------------------------------

    try:
        processing = frame.locator(
            ("#notificationCircularResultTable_processing, " ".dataTables_processing")
        )

        for index in range(await processing.count()):
            item = processing.nth(index)

            if await item.is_visible():
                processing_text = clean_text(await item.inner_text())

                break

    except Exception:
        pass

    return {
        "links": count,
        "table_exists": table_exists,
        "rows": rows,
        "processing": processing_text,
    }


async def wait_for_notification_results_once(
    page,
    frame,
    timeout_seconds,
):
    loop = asyncio.get_running_loop()

    start = loop.time()

    last_state = None
    last_print_second = -1

    while loop.time() - start < timeout_seconds:
        state = await notification_result_state(frame)

        elapsed = int(loop.time() - start)

        if state != last_state or elapsed != last_print_second:
            print(
                "  "
                f"[{elapsed:02d}s] "
                f"links={state['links']} "
                f"rows={state['rows']} "
                f"table={state['table_exists']} "
                f"processing="
                f"{state['processing']!r}"
            )

            last_state = state.copy()
            last_print_second = elapsed

        if state["links"] > 0:
            return True

        await page.wait_for_timeout(250)

    return False


# ============================================================
# FIND GO
# ============================================================


async def find_go_button(
    frame,
):
    selectors = [
        "#clickGo",
        'button:has-text("Go")',
        'input[type="button"][value="Go"]',
        'input[type="submit"][value="Go"]',
    ]

    for selector in selectors:
        candidates = frame.locator(selector)

        count = await candidates.count()

        for index in range(count):
            candidate = candidates.nth(index)

            try:
                if await candidate.is_visible():
                    return candidate

            except Exception:
                pass

    return None


# ============================================================
# ROBUST GO
# ============================================================


async def click_go_and_wait(
    page,
    frame,
):
    print()
    print("=" * 78)
    print("CLICKING GO")
    print("=" * 78)

    # ========================================================
    # GO ATTEMPT 1: NORMAL REAL PLAYWRIGHT CLICK
    # ========================================================

    print()
    print("GO ATTEMPT 1/3:")

    print("  Real Playwright click")

    go = await find_go_button(frame)

    if go is None:
        raise RuntimeError("Go button not found.")

    try:
        print(
            "  disabled:",
            await go.is_disabled(),
        )

    except Exception:
        pass

    try:
        print(
            "  disabled1:",
            repr(await go.get_attribute("disabled1")),
        )

    except Exception:
        pass

    try:
        await go.scroll_into_view_if_needed()

    except Exception:
        pass

    try:
        await go.click(
            timeout=15000,
        )

        print("  Click completed.")

    except Exception as exc:
        print(
            "  Normal click exception:",
            repr(exc),
        )

    found = await wait_for_notification_results_once(
        page,
        frame,
        GO_ATTEMPT_WAIT_SECONDS,
    )

    if found:
        print()
        print("Notification results loaded " "after normal click.")

        return frame

    # ========================================================
    # GO ATTEMPT 2: FORCE REAL PLAYWRIGHT CLICK
    # ========================================================

    print()
    print("GO ATTEMPT 2/3:")

    print("  Force Playwright click")

    go = await find_go_button(frame)

    if go is None:
        raise RuntimeError("Go button disappeared.")

    # Remove literal HTML disabled attribute only if MCA left one.
    # Do not replace the click handler.
    try:
        state = await go.evaluate("""
            button => {
                try {
                    button.disabled = false;
                }
                catch (e) {}

                try {
                    button.removeAttribute(
                        'disabled'
                    );
                }
                catch (e) {}

                return {
                    disabled:
                        !!button.disabled,
                    disabled1:
                        button.getAttribute(
                            'disabled1'
                        ),
                    onclick:
                        button.getAttribute(
                            'onclick'
                        )
                };
            }
            """)

        print(
            "  Go DOM state:",
            state,
        )

    except Exception as exc:
        print(
            "  Could not inspect Go:",
            repr(exc),
        )

    try:
        await go.click(
            force=True,
            timeout=15000,
        )

        print("  Force click completed.")

    except Exception as exc:
        print(
            "  Force click exception:",
            repr(exc),
        )

    found = await wait_for_notification_results_once(
        page,
        frame,
        GO_ATTEMPT_WAIT_SECONDS,
    )

    if found:
        print()
        print("Notification results loaded " "after forced click.")

        return frame

    # ========================================================
    # GO ATTEMPT 3: DOM CLICK
    # ========================================================

    print()
    print("GO ATTEMPT 3/3:")

    print("  MCA DOM click fallback")

    result = await frame.evaluate("""
        () => {
            const select =
                document.querySelector(
                    '#DropDown_Act'
                );

            if (select) {
                try {
                    select.dispatchEvent(
                        new Event(
                            'input',
                            {
                                bubbles: true
                            }
                        )
                    );
                }
                catch (e) {}

                try {
                    select.dispatchEvent(
                        new Event(
                            'change',
                            {
                                bubbles: true
                            }
                        )
                    );
                }
                catch (e) {}
            }

            try {
                if (
                    typeof window
                        .enableclickGoButton
                    === 'function'
                ) {
                    window
                        .enableclickGoButton();
                }
            }
            catch (e) {}

            const go =
                document.querySelector(
                    '#clickGo'
                );

            if (!go) {
                return {
                    ok: false,
                    reason:
                        '#clickGo not found'
                };
            }

            try {
                go.disabled = false;
            }
            catch (e) {}

            try {
                go.removeAttribute(
                    'disabled'
                );
            }
            catch (e) {}

            const result = {
                ok: true,
                text:
                    (
                        go.textContent
                        || ''
                    )
                    .replace(/\\s+/g, ' ')
                    .trim(),
                onclick:
                    go.getAttribute(
                        'onclick'
                    ),
                disabled1:
                    go.getAttribute(
                        'disabled1'
                    )
            };

            go.click();

            return result;
        }
        """)

    print(
        "  DOM click result:",
        result,
    )

    found = await wait_for_notification_results_once(
        page,
        frame,
        GO_ATTEMPT_WAIT_SECONDS,
    )

    if found:
        print()
        print("Notification results loaded " "after DOM click.")

        return frame

    await save_debug(
        page,
        "go_failed_no_notification_results",
    )

    raise RuntimeError(
        "Go was triggered using all three " "methods but MCA returned no " "notification links."
    )


# ============================================================
# SELECT ALL RESULTS
# ============================================================


async def select_all_results(
    page,
    frame,
):
    print()
    print("=" * 78)

    print("SELECTING RESULTS PER PAGE = ALL")

    print("=" * 78)

    selectors = [
        ('select[name="' "notificationCircularResultTable_length" '"]'),
        ('select[aria-controls="' "notificationCircularResultTable" '"]'),
        ".dataTables_length select",
    ]

    dropdown = None

    for selector in selectors:
        candidate = frame.locator(selector)

        if await candidate.count() > 0:
            dropdown = candidate.first

            break

    if dropdown is None:
        raise RuntimeError("Notification results-per-page " "dropdown not found.")

    print(
        "Results-per-page name:",
        repr(await dropdown.get_attribute("name")),
    )

    try:
        await dropdown.select_option(value="-1")

    except Exception:
        await dropdown.select_option(label="All")

    print("Selected All.")

    previous = -1
    stable = 0

    for _ in range(120):
        count = await notifications_link_locator(frame).count()

        if count != previous:
            print(
                "  Current document links:",
                count,
            )

            previous = count
            stable = 0

        else:
            stable += 1

        if count > 5 and stable >= 5:
            break

        await page.wait_for_timeout(250)

    final_count = await notifications_link_locator(frame).count()

    print(
        "Final notification links:",
        final_count,
    )

    return final_count


# ============================================================
# METADATA
# ============================================================

DATE_PATTERN = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")


async def extract_notification_metadata(
    link,
):
    row = link.locator("xpath=ancestor::tr[1]")

    particulars = clean_text(await link.inner_text())

    if not particulars:
        particulars = clean_text(await link.get_attribute("title") or "")

    href = clean_text(await link.get_attribute("href") or "")

    if href.startswith("/"):
        href = urljoin(
            "https://www.mca.gov.in",
            href,
        )

    cells = []

    if await row.count() > 0:
        tds = row.locator("td")

        for index in range(await tds.count()):
            try:
                cells.append(clean_text(await tds.nth(index).inner_text()))

            except Exception:
                cells.append("")

    notification_date = ""

    for value in cells:
        match = DATE_PATTERN.search(value)

        if match:
            notification_date = match.group(1)

            break

    if not notification_date:
        try:
            row_text = clean_text(await row.inner_text())

            match = DATE_PATTERN.search(row_text)

            if match:
                notification_date = match.group(1)

        except Exception:
            pass

    if not notification_date:
        raise RuntimeError("Notification date could not " f"be extracted for {particulars!r}")

    if not particulars:
        raise RuntimeError("Particulars are empty.")

    document_id = decode_document_id_from_url(href)

    return {
        "document_id": document_id,
        "notification_date": notification_date,
        "particulars": particulars,
        "href": href,
        "cells": cells,
    }


async def collect_notification_metadata(
    frame,
):
    print()
    print("=" * 78)

    print("COLLECTING NOTIFICATION METADATA")

    print("=" * 78)

    links = notifications_link_locator(frame)

    total = await links.count()

    print(
        "Notification document links:",
        total,
    )

    items = []

    for index in range(total):
        try:
            link = links.nth(index)

            metadata = await extract_notification_metadata(link)

            metadata["source_index"] = index

            if not metadata.get("href"):
                continue

            items.append(metadata)

        except Exception as exc:
            print(
                "  Metadata error " f"row {index + 1}:",
                repr(exc),
            )

    print(
        "Usable notifications:",
        len(items),
    )

    return items


# ============================================================
# DIRECT HTTP PDF DOWNLOAD
# ============================================================


async def try_direct_endpoint_download(
    context,
    metadata,
    destination,
):
    url = metadata["href"]

    if not url:
        raise RuntimeError("Document URL is empty.")

    response = await context.request.get(
        url,
        timeout=DIRECT_HTTP_TIMEOUT_MS,
        fail_on_status_code=False,
        headers={
            "Referer": NOTIFICATIONS_DIRECT_URL,
            "Accept": ("application/pdf," "application/octet-stream;" "q=0.9,*/*;q=0.8"),
        },
    )

    status = response.status

    # ========================================================
    # IMPORTANT:
    #
    # APIResponse.headers is the correct property.
    #
    # Do NOT call:
    #
    #   await response.all_headers()
    #
    # ========================================================

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

    print(
        "  Direct HTTP status:",
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

    body = await response.body()

    print(
        "  Direct response bytes:",
        len(body),
    )

    if status < 200 or status >= 300:
        raise RuntimeError("Direct endpoint returned " f"HTTP {status}")

    if not looks_like_pdf(body):
        preview = clean_text(
            body[:400].decode(
                "utf-8",
                errors="ignore",
            )
        )

        raise RuntimeError(
            "Direct endpoint did not "
            "return PDF. "
            f"Content-Type={content_type!r}; "
            f"preview={preview!r}"
        )

    pdf_bytes = normalize_pdf_bytes(body)

    destination.write_bytes(pdf_bytes)

    original_pdf = filename_from_content_disposition(headers)

    if not original_pdf:
        document_id = metadata.get("document_id") or "notification"

        original_pdf = f"{document_id}.pdf"

    return {
        "original_pdf": original_pdf,
        "bytes": len(pdf_bytes),
        "status": status,
        "content_type": content_type,
    }


# ============================================================
# POPUP FALLBACK
# ============================================================


async def try_popup_fallback(
    page,
    context,
    frame,
    metadata,
    destination,
):
    source_index = metadata["source_index"]

    links = notifications_link_locator(frame)

    if source_index >= await links.count():
        raise RuntimeError("Notification link disappeared.")

    link = links.nth(source_index)

    try:
        await link.scroll_into_view_if_needed()

    except Exception:
        pass

    loop = asyncio.get_running_loop()

    download_future = loop.create_future()

    popup_future = loop.create_future()

    def on_download(
        download,
    ):
        if not download_future.done():
            download_future.set_result(download)

    def on_popup(
        popup,
    ):
        if not popup_future.done():
            popup_future.set_result(popup)

    page.on(
        "download",
        on_download,
    )

    page.on(
        "popup",
        on_popup,
    )

    try:
        try:
            await link.click(
                timeout=15000,
            )

        except Exception:
            await link.click(
                force=True,
            )

        done, pending = await asyncio.wait(
            {
                download_future,
                popup_future,
            },
            timeout=POPUP_WAIT_SECONDS,
            return_when=(asyncio.FIRST_COMPLETED),
        )

        # ----------------------------------------------------
        # Browser download
        # ----------------------------------------------------

        if download_future in done:
            download = download_future.result()

            original_pdf = clean_text(download.suggested_filename or "")

            await download.save_as(str(destination))

            return {
                "original_pdf": original_pdf or "notification.pdf",
                "method": "browser-download",
            }

        # ----------------------------------------------------
        # Popup
        # ----------------------------------------------------

        if popup_future in done:
            popup = popup_future.result()

            try:
                await popup.wait_for_load_state(
                    "domcontentloaded",
                    timeout=30000,
                )

            except Exception:
                pass

            popup_url = popup.url

            print(
                "  Popup URL:",
                popup_url,
            )

            # -----------------------------------------------
            # Popup may subsequently create a download.
            # -----------------------------------------------

            try:
                if not download_future.done():
                    download = await asyncio.wait_for(
                        download_future,
                        timeout=5,
                    )

                    original_pdf = clean_text(download.suggested_filename or "")

                    await download.save_as(str(destination))

                    try:
                        await popup.close()

                    except Exception:
                        pass

                    return {
                        "original_pdf": original_pdf or "notification.pdf",
                        "method": "popup-download",
                    }

            except asyncio.TimeoutError:
                pass

            # -----------------------------------------------
            # Fetch popup URL
            # -----------------------------------------------

            if popup_url and popup_url != "about:blank":
                response = await context.request.get(
                    popup_url,
                    timeout=(DIRECT_HTTP_TIMEOUT_MS),
                    fail_on_status_code=False,
                )

                body = await response.body()

                if 200 <= response.status < 300 and looks_like_pdf(body):
                    headers = response.headers

                    destination.write_bytes(normalize_pdf_bytes(body))

                    original_pdf = filename_from_content_disposition(headers)

                    if not original_pdf:
                        original_pdf = (metadata.get("document_id") or "notification") + ".pdf"

                    try:
                        await popup.close()

                    except Exception:
                        pass

                    return {
                        "original_pdf": original_pdf,
                        "method": "popup-http",
                    }

            # -----------------------------------------------
            # Look for embedded PDF URL
            # -----------------------------------------------

            pdf_candidate = ""

            selectors = [
                (
                    "iframe",
                    "src",
                ),
                (
                    "embed",
                    "src",
                ),
                (
                    "object",
                    "data",
                ),
                (
                    'a[href*="getdocument"]',
                    "href",
                ),
                (
                    'a[href*=".pdf"]',
                    "href",
                ),
            ]

            for selector, attribute in selectors:
                try:
                    locator = popup.locator(selector)

                    if await locator.count() == 0:
                        continue

                    value = await locator.first.get_attribute(attribute) or ""

                    if value:
                        pdf_candidate = urljoin(
                            popup_url,
                            value,
                        )

                        break

                except Exception:
                    pass

            if pdf_candidate:
                print(
                    "  Popup PDF candidate:",
                    pdf_candidate,
                )

                response = await context.request.get(
                    pdf_candidate,
                    timeout=(DIRECT_HTTP_TIMEOUT_MS),
                    fail_on_status_code=False,
                )

                body = await response.body()

                if 200 <= response.status < 300 and looks_like_pdf(body):
                    headers = response.headers

                    destination.write_bytes(normalize_pdf_bytes(body))

                    original_pdf = filename_from_content_disposition(headers)

                    if not original_pdf:
                        original_pdf = (metadata.get("document_id") or "notification") + ".pdf"

                    try:
                        await popup.close()

                    except Exception:
                        pass

                    return {
                        "original_pdf": original_pdf,
                        "method": "popup-pdf-url",
                    }

            try:
                await popup.close()

            except Exception:
                pass

        raise RuntimeError("Popup fallback did not " "produce a PDF.")

    finally:
        try:
            page.remove_listener(
                "download",
                on_download,
            )

        except Exception:
            pass

        try:
            page.remove_listener(
                "popup",
                on_popup,
            )

        except Exception:
            pass


# ============================================================
# DOWNLOAD ONE NOTIFICATION
# ============================================================


async def download_notification(
    page,
    context,
    frame,
    metadata,
    item_index,
    total_items,
    manifest_rows,
):
    document_id = clean_text(
        metadata.get(
            "document_id",
            "",
        )
    )

    notification_date = metadata["notification_date"]

    particulars = metadata["particulars"]

    document_url = metadata["href"]

    filename = build_filename(
        notification_date,
        particulars,
    )

    destination = DOWNLOAD_DIR / filename

    print()
    print("#" * 78)

    print(f"NOTIFICATION " f"{item_index + 1}/" f"{total_items}")

    print("#" * 78)

    print(
        "Document ID:",
        (document_id or "(not decoded)"),
    )

    print(
        "Notification Date:",
        notification_date,
    )

    print(
        "Particulars:",
        repr(particulars),
    )

    print("Document URL:")

    print(
        " ",
        document_url,
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

            upsert_manifest_row(
                manifest_rows,
                {
                    "table_row": item_index + 1,
                    "document_id": document_id,
                    "notification_date": notification_date,
                    "particulars": particulars,
                    "original_pdf": "",
                    "saved_filename": destination.name,
                    "document_url": document_url,
                    "status": "already-exists",
                },
            )

            return

    last_error = None

    for attempt in range(
        1,
        DOWNLOAD_RETRY_ATTEMPTS + 1,
    ):
        print()
        print("DOWNLOAD ATTEMPT " f"{attempt}/" f"{DOWNLOAD_RETRY_ATTEMPTS}")

        # ====================================================
        # DIRECT ENDPOINT FIRST
        # ====================================================

        try:
            result = await try_direct_endpoint_download(
                context,
                metadata,
                destination,
            )

            print("  DIRECT ENDPOINT SUCCESS")

            print(
                "  PDF bytes:",
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
                    "table_row": item_index + 1,
                    "document_id": document_id,
                    "notification_date": notification_date,
                    "particulars": particulars,
                    "original_pdf": result.get(
                        "original_pdf",
                        "",
                    ),
                    "saved_filename": destination.name,
                    "document_url": document_url,
                    "status": "downloaded-direct-http",
                },
            )

            return

        except Exception as exc:
            last_error = exc

            print(
                "  Direct endpoint failed:",
                repr(exc),
            )

            try:
                if destination.exists():
                    destination.unlink()

            except Exception:
                pass

        # ====================================================
        # POPUP FALLBACK
        # ====================================================

        print("  Using popup fallback...")

        try:
            result = await try_popup_fallback(
                page,
                context,
                frame,
                metadata,
                destination,
            )

            print("  POPUP FALLBACK SUCCESS")

            print(
                "  Method:",
                result.get(
                    "method",
                    "",
                ),
            )

            print("  SAVED:")

            print(
                " ",
                destination.name,
            )

            upsert_manifest_row(
                manifest_rows,
                {
                    "table_row": item_index + 1,
                    "document_id": document_id,
                    "notification_date": notification_date,
                    "particulars": particulars,
                    "original_pdf": result.get(
                        "original_pdf",
                        "",
                    ),
                    "saved_filename": destination.name,
                    "document_url": document_url,
                    "status": "downloaded-popup-fallback",
                },
            )

            return

        except Exception as exc:
            last_error = exc

            print(
                "  Popup fallback failed:",
                repr(exc),
            )

            try:
                if destination.exists():
                    destination.unlink()

            except Exception:
                pass

        if attempt < DOWNLOAD_RETRY_ATTEMPTS:
            print("  Retrying in " f"{DOWNLOAD_RETRY_DELAY_SECONDS}s...")

            await asyncio.sleep(DOWNLOAD_RETRY_DELAY_SECONDS)

    # ========================================================
    # FAILED
    # ========================================================

    error_text = clean_text(str(last_error or "Unknown failure"))

    print()
    print("ERROR: all download " "attempts failed.")

    upsert_manifest_row(
        manifest_rows,
        {
            "table_row": item_index + 1,
            "document_id": document_id,
            "notification_date": notification_date,
            "particulars": particulars,
            "original_pdf": "",
            "saved_filename": filename,
            "document_url": document_url,
            "status": ("ERROR after " f"{DOWNLOAD_RETRY_ATTEMPTS} " "attempts: " f"{error_text}"),
        },
    )


# ============================================================
# PROCESS ALL
# ============================================================


async def process_all_notifications(
    page,
    context,
    frame,
):
    manifest_rows = load_manifest()

    print()
    print("=" * 78)
    print("NOTIFICATION DOWNLOAD")
    print("=" * 78)

    print(
        "Existing manifest rows:",
        len(manifest_rows),
    )

    print(
        "Output:",
        DOWNLOAD_DIR.resolve(),
    )

    metadata_items = await collect_notification_metadata(frame)

    total_items = len(metadata_items)

    print()
    print(
        "Total notification documents:",
        total_items,
    )

    for item_index, metadata in enumerate(metadata_items):
        try:
            await download_notification(
                page=page,
                context=context,
                frame=frame,
                metadata=metadata,
                item_index=item_index,
                total_items=total_items,
                manifest_rows=manifest_rows,
            )

        except Exception as exc:
            print()
            print(
                "ERROR processing " f"notification {item_index + 1}:",
                repr(exc),
            )

            try:
                await save_debug(
                    page,
                    ("notification_" f"{item_index + 1}_" "fatal_error"),
                )

            except Exception:
                pass

    rows = load_manifest()

    downloaded = sum(1 for row in rows if row.get("status", "").startswith("downloaded"))

    already_exists = sum(1 for row in rows if row.get("status") == "already-exists")

    errors = sum(1 for row in rows if row.get("status", "").startswith("ERROR"))

    print()
    print("=" * 78)
    print("FINAL SUMMARY")
    print("=" * 78)

    print(
        "Notifications discovered:",
        total_items,
    )

    print(
        "Downloaded:",
        downloaded,
    )

    print(
        "Already existed:",
        already_exists,
    )

    print(
        "Errors:",
        errors,
    )

    print(
        "Download directory:",
        DOWNLOAD_DIR.resolve(),
    )

    print(
        "Manifest:",
        MANIFEST_FILE.resolve(),
    )

    print("=" * 78)


# ============================================================
# MAIN
# ============================================================


async def main():
    async with async_playwright() as p:

        print()

        if HEADLESS:
            print("Launching HEADLESS Firefox...")

        else:
            print("Launching VISIBLE Firefox...")

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
        # NETWORK DEBUG
        #
        # This is deliberately limited to AJAX/fetch responses
        # likely related to MCA eBooks / notifications.
        # ====================================================

        async def log_response(
            response,
        ):
            try:
                resource_type = response.request.resource_type

                if resource_type not in {
                    "xhr",
                    "fetch",
                }:
                    return

                url = response.url

                low = url.lower()

                interesting = (
                    "notification" in low or "circular" in low or "ebook" in low or "dms" in low
                )

                if not interesting:
                    return

                print(
                    "[AJAX]",
                    response.status,
                    url,
                )

            except Exception:
                pass

        page.on(
            "response",
            log_response,
        )

        try:
            # =================================================
            # 1. HOME
            # =================================================

            await open_home(page)

            # =================================================
            # 2. NOTIFICATIONS MODULE
            # =================================================

            notifications_context = await open_notifications_module(page)

            # =================================================
            # 3. SELECT COMPANIES ACT
            # =================================================

            await select_companies_act(
                page,
                notifications_context,
            )

            # =================================================
            # 4. ROBUST GO + RESULTS
            # =================================================

            notifications_context = await click_go_and_wait(
                page,
                notifications_context,
            )

            # =================================================
            # 5. ALL RESULTS
            # =================================================

            await select_all_results(
                page,
                notifications_context,
            )

            # =================================================
            # 6. DOWNLOAD
            # =================================================

            await process_all_notifications(
                page,
                context,
                notifications_context,
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
