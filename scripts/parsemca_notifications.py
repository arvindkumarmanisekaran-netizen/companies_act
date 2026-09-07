#!/usr/bin/env python3

import asyncio
import base64
import csv
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

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

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

HEADLESS = True

DEFAULT_TIMEOUT = 30000
NAVIGATION_RETRIES = 10
ACT_OPTIONS_TIMEOUT_SECONDS = 60
RESULTS_TIMEOUT_SECONDS = 60

DOWNLOAD_RETRY_ATTEMPTS = 3
DOWNLOAD_RETRY_DELAY_SECONDS = 2

# Direct HTTP endpoint is the preferred path.
DIRECT_HTTP_TIMEOUT_MS = 120000

# Only used when direct endpoint fails.
POPUP_WAIT_SECONDS = 20
DOWNLOAD_WAIT_SECONDS = 30


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
        ) as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def save_manifest(rows):
    with MANIFEST_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=MANIFEST_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def upsert_manifest_row(manifest_rows, row_data):
    """
    Keep one manifest row per notification.

    Prefer document_id as the unique key. If it is missing, fall back to
    date + particulars.
    """
    key_doc = clean_text(row_data.get("document_id", ""))
    key_date = clean_text(row_data.get("notification_date", ""))
    key_particulars = clean_text(row_data.get("particulars", ""))

    for idx, existing in enumerate(manifest_rows):
        existing_doc = clean_text(existing.get("document_id", ""))

        same = False

        if key_doc and existing_doc:
            same = key_doc == existing_doc
        else:
            same = (
                clean_text(existing.get("notification_date", "")) == key_date
                and clean_text(existing.get("particulars", "")) == key_particulars
            )

        if same:
            manifest_rows[idx] = row_data
            save_manifest(manifest_rows)
            return

    manifest_rows.append(row_data)
    save_manifest(manifest_rows)


# ============================================================
# GENERAL HELPERS
# ============================================================


def clean_text(value):
    value = value or ""
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def sanitize_filename_component(value):
    value = clean_text(value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip(" .")
    return value or "NA"


def truncate_utf8(value, max_bytes):
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


def sortable_notification_date(value):
    value = clean_text(value)

    for pattern in (
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
        r"(\d{1,2})-(\d{1,2})-(\d{4})",
    ):
        match = re.fullmatch(pattern, value)

        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3))

            return f"{year:04d}-{month:02d}-{day:02d}"

    return sanitize_filename_component(value)


def strip_size_suffix(particulars):
    """
    MCA link text can look like:

        G.S.R. .... Rules, 2026. | 804KB

    Keep the legal title, not the file-size UI text.
    """
    text = clean_text(particulars)

    text = re.sub(
        r"\s*\|\s*\d+(?:\.\d+)?\s*(?:KB|MB|GB)\s*$",
        "",
        text,
        flags=re.I,
    )

    return text.strip()


def build_filename(notification_date, particulars, max_bytes=245):
    date_prefix = sanitize_filename_component(sortable_notification_date(notification_date))

    title = sanitize_filename_component(strip_size_suffix(particulars))

    prefix = f"{date_prefix} - "
    suffix = ".pdf"

    filename = prefix + title + suffix

    if len(filename.encode("utf-8")) <= max_bytes:
        return filename

    available = max(
        30,
        max_bytes - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8")),
    )

    title = truncate_utf8(title, available)

    return prefix + title + suffix


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
            r"/acts-rules/ebooks/notifications\.html(?:$|[?#])",
            url or "",
            re.I,
        )
    )


def looks_like_pdf(data):
    if not data:
        return False

    # Some servers prepend whitespace/binary noise.
    return data.find(b"%PDF-") >= 0


def normalize_pdf_bytes(data):
    pos = data.find(b"%PDF-")

    if pos < 0:
        return data

    return data[pos:]


def decode_document_id_from_url(url):
    """
    Example:
        ?doc=Njc1OTQ4NjUx
    decodes to:
        675948651
    """
    try:
        query = parse_qs(urlparse(url).query)
        encoded = (query.get("doc") or [""])[0]

        if not encoded:
            return ""

        # base64 may be unpadded
        encoded += "=" * (-len(encoded) % 4)

        decoded = base64.b64decode(encoded).decode(
            "utf-8",
            errors="ignore",
        )

        return clean_text(decoded)
    except Exception:
        return ""


def filename_from_content_disposition(headers):
    """
    APIResponse.headers is a dict property in Playwright Python.

    Do NOT use:
        await response.all_headers()

    That method is not available on APIResponse in the environment that
    produced the user's AttributeError.
    """
    if not headers:
        return ""

    disposition = ""

    for key, value in headers.items():
        if key.lower() == "content-disposition":
            disposition = value or ""
            break

    if not disposition:
        return ""

    # RFC 5987 filename*=UTF-8''...
    match = re.search(
        r"filename\*\s*=\s*(?:UTF-8''|utf-8'')?([^;]+)",
        disposition,
        re.I,
    )

    if match:
        from urllib.parse import unquote

        value = match.group(1).strip().strip("\"'")
        return clean_text(unquote(value))

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


async def save_debug(page, name):
    safe_name = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        name,
    )

    try:
        screenshot_path = DEBUG_DIR / f"{safe_name}.png"

        await page.screenshot(
            path=str(screenshot_path),
            full_page=True,
        )

        print(
            "  Screenshot:",
            screenshot_path.resolve(),
        )
    except Exception:
        pass

    for frame_index, frame in enumerate(page.frames):
        try:
            html = await frame.content()

            html_path = DEBUG_DIR / f"{safe_name}_frame_{frame_index}.html"

            html_path.write_text(
                html,
                encoding="utf-8",
            )
        except Exception:
            pass


# ============================================================
# MCA NAVIGATION
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
        raise RuntimeError(f"MCA home returned HTTP {response.status}")


async def find_acts_rules_link(page):
    selectors = [
        (".second-navigation " 'a[href="/content/mca/global/en/acts-rules.html"]'),
        'a[href="/content/mca/global/en/acts-rules.html"]',
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


async def click_notifications_real(page):
    print()
    print("Searching for Notifications tab...")

    selectors = [
        (".ebooknavigation " "a.menuClick" '[data-doccategory="Notifications"]'),
        'a.menuClick[data-doccategory="Notifications"]',
        'a[data-doccategory="Notifications"]',
        'a[val="Notifications"]',
        'a[data-redirect="/ebooks/notifications.html"]',
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

                    for _ in range(100):
                        if is_notifications_url(page.url):
                            return True

                        await page.wait_for_timeout(100)

                    return False

        await page.wait_for_timeout(100)

    return False


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

            # Fallback: search for the Companies Act option.
            try:
                selects = frame.locator("select")

                for i in range(await selects.count()):
                    select = selects.nth(i)

                    options = select.locator("option")

                    for j in range(await options.count()):
                        option = options.nth(j)

                        text = clean_text(await option.inner_text())

                        data_id = await option.get_attribute("data-id") or ""

                        if text == TARGET_ACT or data_id == TARGET_ACT_DATA_ID:
                            return frame
            except Exception:
                pass

        await page.wait_for_timeout(100)

    return None


async def open_notifications_module(page):
    for attempt in range(
        1,
        NAVIGATION_RETRIES + 1,
    ):
        print()
        print("=" * 78)
        print("NOTIFICATIONS NAVIGATION ATTEMPT " f"{attempt}/{NAVIGATION_RETRIES}")
        print("=" * 78)

        if not is_home_url(page.url):
            await open_home(page)

        acts_link = await find_acts_rules_link(page)

        if acts_link is None:
            print("Acts & Rules link not found.")

            await open_home(page)
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
            print("eBooks page was not reached.")
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

        print("Using direct Notifications URL fallback...")

        response = await page.goto(
            NOTIFICATIONS_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        print(
            "Direct URL HTTP:",
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
# ACT FILTER
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

        candidate_selects = []

        if await preferred.count() > 0:
            candidate_selects.append(preferred.first)

        selects = frame.locator("select")

        for i in range(await selects.count()):
            candidate_selects.append(selects.nth(i))

        seen_ids = set()

        for select in candidate_selects:
            try:
                select_id = await select.get_attribute("id") or ""

                locator_key = select_id or str(
                    await select.evaluate(
                        "el => Array.from(document.querySelectorAll('select')).indexOf(el)"
                    )
                )

                if locator_key in seen_ids:
                    continue

                seen_ids.add(locator_key)

                options = select.locator("option")

                for option_index in range(await options.count()):
                    option = options.nth(option_index)

                    text = clean_text(await option.inner_text())

                    data_id = await option.get_attribute("data-id") or ""

                    if text == TARGET_ACT or data_id == TARGET_ACT_DATA_ID:
                        print("Act dropdown found.")

                        print(
                            "  id:",
                            repr(select_id),
                        )

                        return (
                            select,
                            option_index,
                        )
            except Exception:
                continue

        await page.wait_for_timeout(250)

    raise RuntimeError("Act dropdown containing " "The Companies Act, 2013 was not found.")


async def select_companies_act(
    page,
    frame,
):
    dropdown, option_index = await find_act_dropdown(
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

    verification = await dropdown.evaluate("""
        select => {
            const option =
                select.options[
                    select.selectedIndex
                ];

            return {
                index:
                    select.selectedIndex,
                text:
                    (
                        option.textContent
                        || ''
                    )
                    .replace(/\\s+/g, ' ')
                    .trim(),
                value:
                    option.value || '',
                dataId:
                    option.getAttribute(
                        'data-id'
                    ) || ''
            };
        }
        """)

    print(
        "Selected:",
        verification,
    )


async def find_go_button(frame):
    selectors = [
        "#clickGo",
        'button:has-text("Go")',
        'input[type="button"][value="Go"]',
        'input[type="submit"][value="Go"]',
        'a:has-text("Go")',
    ]

    for selector in selectors:
        candidates = frame.locator(selector)

        for index in range(await candidates.count()):
            candidate = candidates.nth(index)

            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                pass

    return None


async def click_go(
    page,
    frame,
):
    go = await find_go_button(frame)

    if go is None:
        raise RuntimeError("Go button not found.")

    print()
    print("Clicking Go...")

    try:
        await go.click(
            timeout=15000,
        )
    except Exception:
        await go.click(
            force=True,
        )


# ============================================================
# RESULTS
# ============================================================


def notifications_link_locator(frame):
    """
    MCA notification document anchors currently use id="notifications"
    and class="dmslink". The page has duplicate IDs, so locator() is used.
    """
    return frame.locator(
        (
            "a#notifications.dmslink, "
            "a.dmslink#notifications, "
            'a[id="notifications"].dmslink, '
            '[id="notifications"].dmslink'
        )
    )


async def wait_for_notification_results(
    page,
):
    print()
    print("Waiting for notification results...")

    loop = asyncio.get_running_loop()
    start = loop.time()
    previous = None

    while loop.time() - start < RESULTS_TIMEOUT_SECONDS:
        for frame in page.frames:
            try:
                links = notifications_link_locator(frame)

                count = await links.count()

                if count != previous:
                    print(
                        "  Notification links:",
                        count,
                    )
                    previous = count

                if count > 0:
                    print("Notification results loaded.")
                    return frame
            except Exception:
                pass

        await page.wait_for_timeout(250)

    raise RuntimeError("Notification results did not load.")


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
        # Generic fallback: find a select with an All / -1 option,
        # excluding the Act selector.
        selects = frame.locator("select")

        for i in range(await selects.count()):
            select = selects.nth(i)

            select_id = await select.get_attribute("id") or ""

            if select_id == "DropDown_Act":
                continue

            options = select.locator("option")

            for j in range(await options.count()):
                option = options.nth(j)

                text = clean_text(await option.inner_text())

                value = await option.get_attribute("value") or ""

                if text.lower() == "all" or value == "-1":
                    dropdown = select
                    break

            if dropdown is not None:
                break

    if dropdown is None:
        raise RuntimeError("Results-per-page dropdown " "was not found.")

    print(
        "Results-per-page name:",
        repr(await dropdown.get_attribute("name")),
    )

    selected = False

    try:
        await dropdown.select_option(value="-1")
        selected = True
    except Exception:
        pass

    if not selected:
        await dropdown.select_option(label="All")

    print("Selected All.")

    previous = None
    stable_rounds = 0

    for _ in range(60):
        count = await notifications_link_locator(frame).count()

        if count != previous:
            print(
                "  Current document links:",
                count,
            )
            previous = count
            stable_rounds = 0
        else:
            stable_rounds += 1

        if count > 5 and stable_rounds >= 4:
            break

        await page.wait_for_timeout(250)

    final_count = await notifications_link_locator(frame).count()

    print(
        "Final notification links:",
        final_count,
    )

    return final_count


# ============================================================
# METADATA EXTRACTION
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

        for i in range(await tds.count()):
            try:
                cells.append(clean_text(await tds.nth(i).inner_text()))
            except Exception:
                cells.append("")

    notification_date = ""

    for value in cells:
        match = DATE_PATTERN.search(value)

        if match:
            notification_date = match.group(1)
            break

    if not notification_date:
        row_text = ""

        try:
            row_text = clean_text(await row.inner_text())
        except Exception:
            pass

        match = DATE_PATTERN.search(row_text)

        if match:
            notification_date = match.group(1)

    if not notification_date:
        raise RuntimeError("Notification date could not " f"be extracted for {particulars!r}.")

    if not particulars:
        raise RuntimeError("Notification particulars are empty.")

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
                f"  Metadata error at row " f"{index + 1}:",
                repr(exc),
            )

    print(
        "Usable notifications:",
        len(items),
    )

    return items


# ============================================================
# DIRECT HTTP DOWNLOAD
# ============================================================


async def try_direct_endpoint_download(
    context,
    metadata,
    destination,
):
    """
    Download the MCA DMS endpoint using the authenticated BrowserContext.

    IMPORTANT:
        APIResponse does NOT expose all_headers() in the Playwright version
        that produced the user's error.

    Correct:
        headers = response.headers

    Not:
        await response.all_headers()
    """
    url = metadata["href"]

    if not url:
        raise RuntimeError("Notification document URL is empty.")

    response = await context.request.get(
        url,
        timeout=DIRECT_HTTP_TIMEOUT_MS,
        fail_on_status_code=False,
        headers={
            "Referer": NOTIFICATIONS_DIRECT_URL,
            "Accept": ("application/pdf," "application/octet-stream;q=0.9," "*/*;q=0.8"),
        },
    )

    status = response.status

    # FIX: APIResponse.headers is a property returning a dict.
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
            body[:300].decode(
                "utf-8",
                errors="ignore",
            )
        )

        raise RuntimeError(
            "Direct endpoint did not return a PDF. "
            f"Content-Type={content_type!r}; "
            f"body preview={preview!r}"
        )

    pdf_bytes = normalize_pdf_bytes(body)

    destination.write_bytes(pdf_bytes)

    original_pdf = filename_from_content_disposition(headers)

    if not original_pdf:
        path_name = Path(urlparse(url).path).name

        if path_name and "." in path_name:
            original_pdf = path_name

    if not original_pdf:
        original_pdf = f"{metadata.get('document_id') or 'notification'}.pdf"

    return {
        "original_pdf": original_pdf,
        "bytes": len(pdf_bytes),
        "status": status,
        "content_type": content_type,
    }


# ============================================================
# POPUP / BROWSER FALLBACK
# ============================================================


async def wait_for_download_event(
    page,
    trigger,
    timeout_seconds,
):
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def on_download(download):
        if not future.done():
            future.set_result(download)

    page.on(
        "download",
        on_download,
    )

    try:
        await trigger()

        try:
            return await asyncio.wait_for(
                future,
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return None

    finally:
        try:
            page.remove_listener(
                "download",
                on_download,
            )
        except Exception:
            pass


async def try_popup_or_browser_fallback(
    page,
    context,
    frame,
    metadata,
    destination,
):
    """
    Fallback path only.

    Depending on MCA implementation, clicking a dmslink may:
      * fire a browser download;
      * open a popup/new tab;
      * navigate a popup to a PDF endpoint.

    We handle all three.
    """
    source_index = metadata["source_index"]

    links = notifications_link_locator(frame)

    if source_index >= await links.count():
        raise RuntimeError("Notification link disappeared " "before popup fallback.")

    link = links.nth(source_index)

    try:
        await link.scroll_into_view_if_needed()
    except Exception:
        pass

    # --------------------------------------------------------
    # Register both download and popup listeners BEFORE click.
    # --------------------------------------------------------

    download_future = asyncio.get_running_loop().create_future()

    popup_future = asyncio.get_running_loop().create_future()

    def on_download(download):
        if not download_future.done():
            download_future.set_result(download)

    def on_popup(popup):
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
            return_when=asyncio.FIRST_COMPLETED,
        )

        # ----------------------------------------------------
        # Case 1: direct browser download
        # ----------------------------------------------------

        if download_future in done and not download_future.cancelled():
            download = download_future.result()

            original_pdf = clean_text(download.suggested_filename or "")

            await download.save_as(str(destination))

            return {
                "original_pdf": original_pdf or "notification.pdf",
                "method": "browser-download",
            }

        # ----------------------------------------------------
        # Case 2: popup opened
        # ----------------------------------------------------

        if popup_future in done and not popup_future.cancelled():
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

            # A popup can itself start a download after creation.
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

            # If popup is at a usable URL, fetch it with the same
            # authenticated context.
            if popup_url and popup_url != "about:blank":
                response = await context.request.get(
                    popup_url,
                    timeout=DIRECT_HTTP_TIMEOUT_MS,
                    fail_on_status_code=False,
                )

                body = await response.body()

                if 200 <= response.status < 300 and looks_like_pdf(body):
                    headers = response.headers

                    destination.write_bytes(normalize_pdf_bytes(body))

                    original_pdf = filename_from_content_disposition(headers)

                    if not original_pdf:
                        original_pdf = Path(urlparse(popup_url).path).name or "notification.pdf"

                    try:
                        await popup.close()
                    except Exception:
                        pass

                    return {
                        "original_pdf": original_pdf,
                        "method": "popup-http",
                    }

            # Last popup attempt: inspect PDF/embed/iframe/object URL.
            pdf_candidate = ""

            for selector, attr in (
                ("iframe", "src"),
                ("embed", "src"),
                ("object", "data"),
                ('a[href*=".pdf"]', "href"),
                ('a[href*="getdocument"]', "href"),
            ):
                try:
                    locator = popup.locator(selector)

                    if await locator.count() > 0:
                        value = await locator.first.get_attribute(attr) or ""

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
                    timeout=DIRECT_HTTP_TIMEOUT_MS,
                    fail_on_status_code=False,
                )

                body = await response.body()

                if 200 <= response.status < 300 and looks_like_pdf(body):
                    headers = response.headers

                    destination.write_bytes(normalize_pdf_bytes(body))

                    original_pdf = (
                        filename_from_content_disposition(headers)
                        or Path(urlparse(pdf_candidate).path).name
                        or "notification.pdf"
                    )

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

        raise RuntimeError("Popup fallback did not produce a PDF.")

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

    source_href = metadata["href"]

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
        document_id or "(not decoded)",
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
        source_href,
    )

    # --------------------------------------------------------
    # Resume / physical duplicate check
    # --------------------------------------------------------

    if destination.exists():
        size = destination.stat().st_size

        if size > 0:
            print(
                "ALREADY EXISTS - SKIPPING:",
                destination.name,
            )

            upsert_manifest_row(
                manifest_rows,
                {
                    "table_row": item_index + 1,
                    "document_id": document_id,
                    "notification_date": notification_date,
                    "particulars": particulars,
                    "original_pdf": "",
                    "saved_filename": destination.name,
                    "document_url": source_href,
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
        print(f"DOWNLOAD ATTEMPT " f"{attempt}/" f"{DOWNLOAD_RETRY_ATTEMPTS}")

        # ====================================================
        # PREFERRED METHOD: DIRECT AUTHENTICATED HTTP
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
                    "original_pdf": result["original_pdf"],
                    "saved_filename": destination.name,
                    "document_url": source_href,
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

            # Never leave a partial/corrupt file behind.
            try:
                if destination.exists():
                    destination.unlink()
            except Exception:
                pass

        # ====================================================
        # FALLBACK: REAL BROWSER / POPUP
        # ====================================================

        try:
            print("  Using popup fallback...")

            result = await try_popup_or_browser_fallback(
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
                    "document_url": source_href,
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

    # --------------------------------------------------------
    # All attempts failed
    # --------------------------------------------------------

    error_text = clean_text(str(last_error or "Unknown download failure"))

    print()
    print("ERROR: all " f"{DOWNLOAD_RETRY_ATTEMPTS} " "attempts failed.")

    print("Recording failure and moving on.")

    upsert_manifest_row(
        manifest_rows,
        {
            "table_row": item_index + 1,
            "document_id": document_id,
            "notification_date": notification_date,
            "particulars": particulars,
            "original_pdf": "",
            "saved_filename": filename,
            "document_url": source_href,
            "status": ("ERROR after " f"{DOWNLOAD_RETRY_ATTEMPTS} attempts: " f"{error_text}"),
        },
    )


# ============================================================
# PROCESS ALL NOTIFICATIONS
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
                "ERROR processing notification " f"{item_index + 1}:",
                repr(exc),
            )

            try:
                await save_debug(
                    page,
                    (f"notification_" f"{item_index + 1}_" "fatal_item_error"),
                )
            except Exception:
                pass

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

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

        # Firefox only:
        # Chromium has previously received MCA/Akamai HTTP 403
        # in this environment.
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
            # 3. ACT = THE COMPANIES ACT, 2013
            # =================================================

            await select_companies_act(
                page,
                notifications_context,
            )

            # =================================================
            # 4. GO
            # =================================================

            await click_go(
                page,
                notifications_context,
            )

            notifications_context = await wait_for_notification_results(page)

            # =================================================
            # 5. RESULTS PER PAGE = ALL
            # =================================================

            await select_all_results(
                page,
                notifications_context,
            )

            # =================================================
            # 6. DOWNLOAD ALL NOTIFICATIONS
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
