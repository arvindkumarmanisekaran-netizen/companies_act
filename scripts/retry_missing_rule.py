#!/usr/bin/env python3

import asyncio
import csv
import re
from pathlib import Path

from playwright.async_api import async_playwright

# ============================================================
# CONFIG
# ============================================================

START_URL = "https://www.mca.gov.in/content/mca/global/en/home.html"

RULES_DIRECT_URL = "https://www.mca.gov.in/content/mca/global/en/" "acts-rules/ebooks/rules.html"

TARGET_ACT = "The Companies Act, 2013"
TARGET_ACT_DATA_ID = "J105_D"

TARGET_RULES_NAME = (
    "The Investor Education and Protection Fund Authority "
    "(Form of Annual Statement of Accounts) Rules, 2018"
)

TARGET_RULE_CONTAINS = "Rule 1 to 6"
TARGET_NOTIFICATION_DATE = "11/10/2018"
TARGET_RULE_TITLE = "Schedule"

OUTPUT_ROOT = Path("mca_companies_act_2013")

DOWNLOAD_DIR = OUTPUT_ROOT / "rules"

MANIFEST_FILE = DOWNLOAD_DIR / "downloads.csv"

DEBUG_DIR = OUTPUT_ROOT / "debug"

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DEBUG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DEFAULT_TIMEOUT = 30000
DOWNLOAD_WAIT_SECONDS = 60


# ============================================================
# HELPERS
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


def normalize_date_for_filename(
    value,
):
    return clean_text(value).replace(
        "/",
        "-",
    )


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

    return value.strip(" .")


def build_target_filename():
    return (
        f"{sanitize_filename_component(TARGET_RULES_NAME)}"
        f" - "
        f"{sanitize_filename_component(TARGET_RULE_CONTAINS)}"
        f" - "
        f"{normalize_date_for_filename(TARGET_NOTIFICATION_DATE)}"
        f" - "
        f"{sanitize_filename_component(TARGET_RULE_TITLE)}"
        f" .pdf"
    )


def is_ebooks_url(url):
    return bool(
        re.search(
            r"/acts-rules/ebooks\.html(?:$|[?#])",
            url or "",
            re.I,
        )
    )


def is_rules_url(url):
    return bool(
        re.search(
            r"/acts-rules/ebooks/rules\.html(?:$|[?#])",
            url or "",
            re.I,
        )
    )


# ============================================================
# DEBUG
# ============================================================


async def save_debug(
    page,
    name,
):
    safe = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        name,
    )

    try:
        await page.screenshot(
            path=str(DEBUG_DIR / f"{safe}.png"),
            full_page=True,
        )

    except Exception:
        pass

    try:
        html = await page.content()

        (DEBUG_DIR / f"{safe}.html").write_text(
            html,
            encoding="utf-8",
        )

    except Exception:
        pass


# ============================================================
# MANIFEST UPDATE
# ============================================================


def update_manifest_downloaded(
    original_pdf,
    saved_filename,
):
    if not MANIFEST_FILE.exists():
        print("Manifest does not exist; " "skipping manifest update.")
        return

    with MANIFEST_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        rows = list(csv.DictReader(file))

        fieldnames = rows[0].keys() if rows else []

    updated = False

    for row in rows:
        if (
            clean_text(row.get("rules", "")) == TARGET_RULES_NAME
            and clean_text(row.get("rule_contains", "")) == TARGET_RULE_CONTAINS
            and clean_text(row.get("notification_date", "")) == TARGET_NOTIFICATION_DATE
            and clean_text(row.get("rule_title", "")) == TARGET_RULE_TITLE
        ):
            row["original_pdf"] = original_pdf

            row["saved_filename"] = saved_filename

            row["status"] = "downloaded"

            updated = True

    if not updated:
        print("WARNING: Matching manifest row " "was not found.")
        return

    with MANIFEST_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(fieldnames),
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)

    print("Manifest updated.")


# ============================================================
# OPEN MCA
# ============================================================


async def open_home(
    page,
):
    print()
    print("=" * 78)
    print("OPENING MCA")
    print("=" * 78)

    response = await page.goto(
        START_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    print(
        "HTTP:",
        response.status if response else None,
    )

    print(
        "URL:",
        page.url,
    )


# ============================================================
# OPEN RULES
# ============================================================


async def open_rules_module(
    page,
):
    acts_link = page.locator(('a[href="/content/mca/global/en/' 'acts-rules.html"]')).first

    await acts_link.wait_for(
        state="visible",
        timeout=30000,
    )

    print("Clicking Acts & Rules...")

    await acts_link.click()

    for _ in range(200):
        if is_ebooks_url(page.url):
            break

        await page.wait_for_timeout(50)

    print(
        "eBooks URL:",
        page.url,
    )

    rules = page.locator((".ebooknavigation " "a.menuClick" '[data-doccategory="Rules"]')).first

    await rules.wait_for(
        state="visible",
        timeout=30000,
    )

    print("Clicking Rules...")

    await rules.click()

    for _ in range(200):
        if is_rules_url(page.url):
            break

        await page.wait_for_timeout(50)

    if not is_rules_url(page.url):
        print("Using direct Rules URL fallback...")

        await page.goto(
            RULES_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

    print(
        "Rules URL:",
        page.url,
    )


# ============================================================
# SELECT COMPANIES ACT
# ============================================================


async def select_companies_act(
    page,
):
    dropdown = page.locator("#DropDown_RuleAct")

    await dropdown.wait_for(
        state="attached",
        timeout=30000,
    )

    print("Waiting for Act options...")

    target_index = None

    for _ in range(240):
        options = dropdown.locator("option")

        count = await options.count()

        for index in range(count):
            option = options.nth(index)

            text = clean_text(await option.inner_text())

            data_id = await option.get_attribute("data-id") or ""

            if data_id == TARGET_ACT_DATA_ID or text == TARGET_ACT:
                target_index = index
                break

        if target_index is not None:
            break

        await page.wait_for_timeout(250)

    if target_index is None:
        raise RuntimeError("Companies Act option not found.")

    print("Selecting Companies Act...")

    await dropdown.select_option(
        index=target_index,
    )

    go = page.locator("#clickGo")

    await go.wait_for(
        state="visible",
        timeout=30000,
    )

    print("Clicking Go...")

    await go.click()

    rows = page.locator("#rulesContainer tbody tr")

    for _ in range(240):
        row_count = await rows.count()

        useful = 0

        for index in range(row_count):
            if await rows.nth(index).locator(".ruleLink").count() > 0:
                useful += 1

        if useful:
            break

        await page.wait_for_timeout(250)

    print(
        "Initial rows:",
        await rows.count(),
    )


# ============================================================
# SHOW ALL
# ============================================================


async def show_all_rows(
    page,
):
    dropdown = page.locator(("select[name=" '"rulesContainer_length"]'))

    await dropdown.wait_for(
        state="visible",
        timeout=30000,
    )

    await dropdown.select_option(value="-1")

    await page.wait_for_timeout(1500)

    print(
        "Rows after All:",
        await page.locator("#rulesContainer tbody tr").count(),
    )


# ============================================================
# FIND TARGET ROW
# ============================================================


async def find_target_row(
    page,
):
    rows = page.locator("#rulesContainer tbody tr")

    count = await rows.count()

    print()
    print("Searching", count, "table rows...")

    for index in range(count):
        row = rows.nth(index)

        rule_link = row.locator(".ruleLink")

        if await rule_link.count() == 0:
            continue

        rules_name = clean_text(await rule_link.first.inner_text())

        if rules_name != TARGET_RULES_NAME:
            continue

        cells = row.locator("td")

        texts = []

        for cell_index in range(await cells.count()):
            texts.append(clean_text(await cells.nth(cell_index).inner_text()))

        rule_contains = texts[1] if len(texts) > 1 else ""

        notification_date = texts[2] if len(texts) > 2 else ""

        print()
        print("TARGET TABLE ROW FOUND")

        print(
            "Row index:",
            index + 1,
        )

        print(
            "Rules:",
            rules_name,
        )

        print(
            "Rule Contains:",
            rule_contains,
        )

        print(
            "Notification Date:",
            notification_date,
        )

        if rule_contains == TARGET_RULE_CONTAINS and notification_date == TARGET_NOTIFICATION_DATE:
            return (
                row,
                index,
            )

    return (
        None,
        None,
    )


# ============================================================
# FIND TARGET POPUP
# ============================================================


async def open_target_popup(
    page,
    row,
):
    link = row.locator(".ruleLink").first

    await link.click()

    popup_links = page.locator(
        (
            ".resaultContentContainer "
            "ol.rulesListPopContainer "
            "li.pop a.rulePopup, "
            ".resultContentContainer "
            "ol.rulesListPopContainer "
            "li.pop a.rulePopup, "
            "ol.rulesListPopContainer "
            "li.pop a.rulePopup"
        )
    )

    await popup_links.first.wait_for(
        state="visible",
        timeout=30000,
    )

    count = await popup_links.count()

    print(
        "Popup rules:",
        count,
    )

    for index in range(count):
        popup = popup_links.nth(index)

        title = clean_text(await popup.inner_text())

        if title == TARGET_RULE_TITLE:
            print(
                "TARGET POPUP FOUND:",
                title,
            )

            await popup.click()

            return

    raise RuntimeError("Schedule popup not found.")


# ============================================================
# ACTIVE MODAL
# ============================================================


async def get_modal(
    page,
):
    for _ in range(100):
        modals = page.locator(".modal-dialog.modal-sm")

        for index in range(await modals.count()):
            modal = modals.nth(index)

            try:
                if await modal.is_visible():
                    return modal

            except Exception:
                pass

        await page.wait_for_timeout(100)

    return None


# ============================================================
# OPEN PDF DROPDOWN
# ============================================================


async def get_current_rule_radio(
    page,
    modal,
):
    selectors = [
        (".rulespdfDownload " ".dropdown-toggle"),
        ".rulespdfDownload button",
        ".rulespdfDownload a",
        ".rulespdfDownload",
    ]

    for selector in selectors:
        candidate = modal.locator(selector)

        for index in range(await candidate.count()):
            item = candidate.nth(index)

            try:
                if await item.is_visible():
                    await item.click(force=True)

                    break

            except Exception:
                pass

    await page.wait_for_timeout(300)

    dropdown = modal.locator("#mypdfDropdown")

    if await dropdown.count() == 0:
        dropdown = page.locator("#mypdfDropdown")

    radio = dropdown.locator(('input[type="radio"]' '[value="Current Rule"]'))

    if await radio.count() == 0:
        radio = dropdown.locator(('input[type="radio"]' '[aria-label="Current Rule"]'))

    if await radio.count() == 0:
        raise RuntimeError("Current Rule radio not found.")

    return radio.first


# ============================================================
# DOWNLOAD LISTENER
# ============================================================


async def wait_for_download(
    page,
    radio,
):
    loop = asyncio.get_running_loop()

    future = loop.create_future()

    def on_download(
        download,
    ):
        if not future.done():
            future.set_result(download)

    page.on(
        "download",
        on_download,
    )

    try:
        result = await radio.evaluate("""
            element => {
                element.click();

                return {
                    value:
                        element.getAttribute(
                            'value'
                        ),

                    ariaLabel:
                        element.getAttribute(
                            'aria-label'
                        )
                };
            }
            """)

        print(
            "Radio trigger:",
            result,
        )

        try:
            return await asyncio.wait_for(
                future,
                timeout=DOWNLOAD_WAIT_SECONDS,
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


# ============================================================
# RETRY DOWNLOAD
# ============================================================


async def retry_download(
    page,
):
    target_filename = build_target_filename()

    destination = DOWNLOAD_DIR / target_filename

    print()
    print("=" * 78)
    print("TARGET")
    print("=" * 78)

    print("Filename:")

    print(target_filename)

    if destination.exists():
        print()
        print("FILE ALREADY EXISTS.")

        print("No download required.")

        update_manifest_downloaded(
            original_pdf="",
            saved_filename=target_filename,
        )

        return True

    row, row_index = await find_target_row(page)

    if row is None:
        raise RuntimeError("Target table row not found.")

    await open_target_popup(
        page,
        row,
    )

    modal = await get_modal(page)

    if modal is None:
        raise RuntimeError("Modal did not open.")

    radio = await get_current_rule_radio(
        page,
        modal,
    )

    print()
    print("Downloading Current Rule...")

    download = await wait_for_download(
        page,
        radio,
    )

    if download is None:
        raise RuntimeError("Current Rule download " "timed out again.")

    original_pdf = clean_text(download.suggested_filename or "")

    print(
        "Original MCA filename:",
        original_pdf,
    )

    await download.save_as(str(destination))

    print()
    print("SAVED:")

    print(destination.resolve())

    update_manifest_downloaded(
        original_pdf=original_pdf,
        saved_filename=target_filename,
    )

    return True


# ============================================================
# MAIN
# ============================================================


async def main():
    async with async_playwright() as p:

        browser = await p.firefox.launch(
            headless=True,
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
            await open_home(page)

            await open_rules_module(page)

            await select_companies_act(page)

            await show_all_rows(page)

            await retry_download(page)

            print()
            print("=" * 78)
            print("RETRY COMPLETE")
            print("=" * 78)

        except Exception as exc:
            print()
            print("=" * 78)

            print(
                "RETRY FAILED:",
                repr(exc),
            )

            print("=" * 78)

            await save_debug(
                page,
                "schedule_retry_failed",
            )

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
        print("Stopped.")
