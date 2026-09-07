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
DEBUG_DIR = OUTPUT_ROOT / "debug"
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

BLOB_WAIT_SECONDS = 120

# 1 MB chunks
BLOB_CHUNK_SIZE = 1024 * 1024


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


def filename_safe(value):
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
        f"{filename_safe(TARGET_RULES_NAME)}"
        f" - "
        f"{filename_safe(TARGET_RULE_CONTAINS)}"
        f" - "
        f"{TARGET_NOTIFICATION_DATE.replace('/', '-')}"
        f" - "
        f"{filename_safe(TARGET_RULE_TITLE)}"
        f" .pdf"
    )


def human_size(size):
    if size is None:
        return "unknown"

    value = float(size)

    for unit in [
        "B",
        "KB",
        "MB",
        "GB",
    ]:
        if value < 1024:
            return f"{value:.2f} {unit}"

        value /= 1024

    return f"{value:.2f} TB"


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
        screenshot = DEBUG_DIR / f"{safe}.png"

        await page.screenshot(
            path=str(screenshot),
            full_page=True,
        )

        print(
            "Screenshot:",
            screenshot.resolve(),
        )

    except Exception:
        pass

    for frame_index, frame in enumerate(page.frames):
        try:
            html = await frame.content()

            html_path = DEBUG_DIR / (f"{safe}_" f"frame_{frame_index}.html")

            html_path.write_text(
                html,
                encoding="utf-8",
            )

        except Exception:
            pass


# ============================================================
# MANIFEST
# ============================================================


def update_manifest(
    original_pdf,
    saved_filename,
):
    if not MANIFEST_FILE.exists():
        print("Manifest not found.")

        return

    with MANIFEST_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        rows = list(reader)

        fields = reader.fieldnames or []

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
        print("WARNING: matching manifest " "row was not found.")

        return

    with MANIFEST_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)

    print("Manifest updated: downloaded")


# ============================================================
# BLOB INTERCEPTION SCRIPT
# ============================================================

BLOB_INTERCEPT_SCRIPT = r"""
(() => {
    if (window.__mcaBlobInterceptorInstalled) {
        return;
    }

    window.__mcaBlobInterceptorInstalled = true;

    window.__mcaCapturedBlobs = [];
    window.__mcaBlobCounter = 0;

    const originalCreateObjectURL =
        URL.createObjectURL.bind(URL);

    const originalRevokeObjectURL =
        URL.revokeObjectURL.bind(URL);

    URL.createObjectURL = function(object) {
        const url =
            originalCreateObjectURL(object);

        try {
            const id =
                ++window.__mcaBlobCounter;

            window.__mcaCapturedBlobs.push({
                id: id,
                url: url,
                object: object,
                size:
                    object && typeof object.size === 'number'
                    ? object.size
                    : null,
                type:
                    object && object.type
                    ? object.type
                    : '',
                createdAt:
                    Date.now(),
                revoked:
                    false
            });

            console.log(
                '[MCA BLOB CAPTURE]',
                id,
                url,
                object?.type,
                object?.size
            );

        } catch (error) {
            console.error(
                '[MCA BLOB CAPTURE ERROR]',
                error
            );
        }

        return url;
    };

    URL.revokeObjectURL = function(url) {
        try {
            const entry =
                window.__mcaCapturedBlobs
                .find(
                    item => item.url === url
                );

            if (entry) {
                entry.revoked = true;

                entry.revokedAt =
                    Date.now();
            }

        } catch (_) {
        }

        return originalRevokeObjectURL(
            url
        );
    };

    console.log(
        '[MCA] Blob interceptor installed'
    );
})();
"""


# ============================================================
# MCA HOME
# ============================================================


async def open_home(page):
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

    if response is not None and response.status >= 400:
        raise RuntimeError(f"MCA returned HTTP " f"{response.status}")


# ============================================================
# OPEN RULES
# ============================================================


async def open_rules_module(page):
    acts = page.locator(('a[href="/content/mca/global/en/' 'acts-rules.html"]')).first

    await acts.wait_for(
        state="visible",
        timeout=30000,
    )

    print("Clicking Acts & Rules...")

    await acts.click()

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

    try:
        await rules.click(
            timeout=10000,
        )

    except Exception:
        await rules.click(
            force=True,
        )

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


async def select_companies_act(page):
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
        raise RuntimeError("Companies Act option " "not found.")

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
        useful = 0

        for index in range(await rows.count()):
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


async def show_all_rows(page):
    dropdown = page.locator('select[name="rulesContainer_length"]')

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


async def find_target_row(page):
    rows = page.locator("#rulesContainer tbody tr")

    count = await rows.count()

    print()
    print(f"Searching {count} table rows...")

    for index in range(count):
        row = rows.nth(index)

        link = row.locator(".ruleLink")

        if await link.count() == 0:
            continue

        title = clean_text(await link.first.inner_text())

        if title != TARGET_RULES_NAME:
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
            title,
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
            return row

    return None


# ============================================================
# OPEN SCHEDULE
# ============================================================


async def open_schedule(
    page,
    row,
):
    await row.locator(".ruleLink").first.click()

    popups = page.locator(
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

    await popups.first.wait_for(
        state="visible",
        timeout=30000,
    )

    print(
        "Popup rules:",
        await popups.count(),
    )

    for index in range(await popups.count()):
        popup = popups.nth(index)

        text = clean_text(await popup.inner_text())

        if text == TARGET_RULE_TITLE:
            print(
                "TARGET POPUP FOUND:",
                text,
            )

            await popup.click()

            return

    raise RuntimeError("Schedule popup not found.")


# ============================================================
# ACTIVE MODAL
# ============================================================


async def get_modal(page):
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
# DOWNLOAD BUTTON
# ============================================================


async def get_download_button(
    modal,
):
    buttons = modal.locator("a#downloadRuleBtn")

    print()
    print(
        "#downloadRuleBtn count:",
        await buttons.count(),
    )

    for index in range(await buttons.count()):
        button = buttons.nth(index)

        try:
            visible = await button.is_visible()

        except Exception:
            visible = False

        print(f"  [{index}] " f"visible={visible}")

        if visible:
            return button

    raise RuntimeError("Visible #downloadRuleBtn " "not found.")


# ============================================================
# OPEN PDF MENU
# ============================================================


async def open_pdf_dropdown(
    page,
    modal,
):
    button = await get_download_button(modal)

    print()
    print("Opening PDF dropdown...")

    await button.click()

    dropdown = modal.locator("#mypdfDropdown")

    for _ in range(50):
        if await dropdown.count() > 0:
            radio = dropdown.first.locator("#rulesDownloadLinks")

            if await radio.count() > 0:
                try:
                    if await radio.first.is_visible():
                        print("#mypdfDropdown opened.")

                        return (
                            button,
                            dropdown.first,
                        )

                except Exception:
                    pass

        await page.wait_for_timeout(100)

    raise RuntimeError("#mypdfDropdown did not open.")


# ============================================================
# SELECT CURRENT RULE
# ============================================================


async def select_current_rule(
    page,
    dropdown,
):
    radio = dropdown.locator(
        ("input#rulesDownloadLinks" '[type="radio"]' '[name="download"]' '[value="Current Rule"]')
    ).first

    await radio.wait_for(
        state="visible",
        timeout=10000,
    )

    print()
    print("CURRENT RULE RADIO")

    print(
        "Visible:",
        await radio.is_visible(),
    )

    print(
        "Enabled:",
        await radio.is_enabled(),
    )

    print(
        "Checked before:",
        await radio.is_checked(),
    )

    if not await radio.is_checked():
        await radio.click()

    await page.wait_for_timeout(500)

    print(
        "Checked after:",
        await radio.is_checked(),
    )

    if not await radio.is_checked():
        raise RuntimeError("Current Rule was not selected.")


# ============================================================
# INSTALL BLOB INTERCEPTOR
# ============================================================


async def install_blob_interceptor(
    page,
):
    print()
    print("=" * 78)
    print("INSTALLING BLOB INTERCEPTOR")
    print("=" * 78)

    # Install in main page.
    result = await page.evaluate(BLOB_INTERCEPT_SCRIPT)

    # Install in existing frames too, just in case
    # MCA generates the PDF inside an iframe.
    for frame_index, frame in enumerate(page.frames):
        try:
            await frame.evaluate(BLOB_INTERCEPT_SCRIPT)

            print(f"Blob interceptor installed " f"in frame #{frame_index}")

        except Exception:
            pass

    print("Blob interception ready.")


# ============================================================
# READ CAPTURED BLOBS
# ============================================================


async def get_captured_blobs(
    page,
):
    captures = []

    for frame_index, frame in enumerate(page.frames):
        try:
            items = await frame.evaluate("""
                () => {
                    if (
                        !window.__mcaCapturedBlobs
                    ) {
                        return [];
                    }

                    return (
                        window.__mcaCapturedBlobs
                        .map(
                            item => ({
                                id:
                                    item.id,

                                url:
                                    item.url,

                                size:
                                    item.size,

                                type:
                                    item.type,

                                createdAt:
                                    item.createdAt,

                                revoked:
                                    item.revoked
                            })
                        )
                    );
                }
                """)

            for item in items:
                item["frame_index"] = frame_index

                captures.append(item)

        except Exception:
            pass

    return captures


# ============================================================
# WAIT FOR MCA TO CALL URL.createObjectURL()
# ============================================================


async def wait_for_captured_blob(
    page,
):
    print()
    print("=" * 78)
    print("WAITING FOR URL.createObjectURL()")
    print("=" * 78)

    loop = asyncio.get_running_loop()

    start = loop.time()

    while loop.time() - start < BLOB_WAIT_SECONDS:
        blobs = await get_captured_blobs(page)

        if blobs:
            # Prefer a PDF MIME type.
            pdf_blobs = [item for item in blobs if ("pdf" in (item.get("type", "") or "").lower())]

            if pdf_blobs:
                selected = max(
                    pdf_blobs,
                    key=lambda x: x.get("createdAt", 0),
                )

            else:
                # Otherwise select largest/newest blob.
                selected = max(
                    blobs,
                    key=lambda x: (
                        x.get("size", 0) or 0,
                        x.get("createdAt", 0),
                    ),
                )

            print()
            print()
            print("=" * 78)
            print("BLOB CAPTURED")
            print("=" * 78)

            print(
                "Frame:",
                selected["frame_index"],
            )

            print(
                "ID:",
                selected["id"],
            )

            print(
                "URL:",
                selected["url"],
            )

            print(
                "MIME:",
                selected.get("type") or "unknown",
            )

            print(
                "Size:",
                human_size(selected.get("size") or 0),
            )

            print(
                "Already revoked:",
                selected.get("revoked"),
            )

            return selected

        elapsed = int(loop.time() - start)

        print(
            f"\rWaiting for blob creation: " f"{elapsed:3d}/" f"{BLOB_WAIT_SECONDS}s",
            end="",
            flush=True,
        )

        await asyncio.sleep(0.25)

    print()

    return None


# ============================================================
# EXTRACT CAPTURED BLOB
# ============================================================


async def extract_captured_blob(
    page,
    blob_info,
    destination,
):
    frame_index = blob_info["frame_index"]

    blob_id = blob_info["id"]

    frame = page.frames[frame_index]

    print()
    print("=" * 78)
    print("EXTRACTING CAPTURED PDF BLOB")
    print("=" * 78)

    # --------------------------------------------------------
    # Read metadata directly from retained Blob object.
    #
    # Important:
    # Even if URL.revokeObjectURL() was called, the Blob
    # object itself is still retained in our JS array.
    # --------------------------------------------------------

    metadata = await frame.evaluate(
        """
        (id) => {
            const entry =
                window.__mcaCapturedBlobs
                .find(
                    x => x.id === id
                );

            if (!entry) {
                return null;
            }

            return {
                size:
                    entry.object.size,

                type:
                    entry.object.type,

                revoked:
                    entry.revoked
            };
        }
        """,
        blob_id,
    )

    if metadata is None:
        raise RuntimeError("Captured Blob object disappeared.")

    total_size = int(metadata["size"])

    print(
        "MIME:",
        metadata["type"],
    )

    print(
        "Size:",
        human_size(total_size),
    )

    print(
        "URL revoked:",
        metadata["revoked"],
    )

    if total_size <= 0:
        raise RuntimeError("Captured blob is empty.")

    temp_file = destination.with_suffix(destination.suffix + ".part")

    if temp_file.exists():
        temp_file.unlink()

    # --------------------------------------------------------
    # Transfer 1 MB at a time.
    # --------------------------------------------------------

    with temp_file.open("wb") as output:
        offset = 0

        while offset < total_size:
            end = min(
                offset + BLOB_CHUNK_SIZE,
                total_size,
            )

            chunk = await frame.evaluate(
                """
                async ({
                    id,
                    start,
                    end
                }) => {
                    const entry =
                        window
                        .__mcaCapturedBlobs
                        .find(
                            x => x.id === id
                        );

                    if (!entry) {
                        throw new Error(
                            'Blob entry missing'
                        );
                    }

                    const slice =
                        entry.object.slice(
                            start,
                            end
                        );

                    const buffer =
                        await slice.arrayBuffer();

                    return Array.from(
                        new Uint8Array(
                            buffer
                        )
                    );
                }
                """,
                {
                    "id": blob_id,
                    "start": offset,
                    "end": end,
                },
            )

            output.write(bytes(chunk))

            offset = end

            percent = offset / total_size * 100

            print(
                f"\rExtracting: "
                f"{percent:6.2f}%  "
                f"{human_size(offset)}"
                f" / "
                f"{human_size(total_size)}",
                end="",
                flush=True,
            )

    print()

    temp_file.replace(destination)


# ============================================================
# VERIFY PDF
# ============================================================


def verify_pdf(
    destination,
):
    if not destination.exists():
        raise RuntimeError("PDF file was not created.")

    size = destination.stat().st_size

    if size == 0:
        raise RuntimeError("PDF is empty.")

    with destination.open("rb") as file:
        signature = file.read(5)

    print()
    print(
        "Saved size:",
        human_size(size),
    )

    print(
        "First 5 bytes:",
        repr(signature),
    )

    if signature != b"%PDF-":
        raise RuntimeError("Saved Blob does not have " "a valid PDF signature.")

    print("PDF signature verified: %PDF-")


# ============================================================
# RETRY
# ============================================================


async def retry_download(
    page,
):
    filename = build_target_filename()

    destination = DOWNLOAD_DIR / filename

    print()
    print("=" * 78)
    print("TARGET")
    print("=" * 78)

    print("Filename:")

    print(filename)

    # ========================================================
    # EXISTING FILE
    # ========================================================

    if destination.exists():
        print()
        print("FILE ALREADY EXISTS")

        verify_pdf(destination)

        update_manifest(
            original_pdf="blob-pdf",
            saved_filename=filename,
        )

        return

    # ========================================================
    # FIND TARGET ROW
    # ========================================================

    row = await find_target_row(page)

    if row is None:
        raise RuntimeError("Target table row not found.")

    # ========================================================
    # OPEN SCHEDULE
    # ========================================================

    await open_schedule(
        page,
        row,
    )

    modal = await get_modal(page)

    if modal is None:
        raise RuntimeError("Schedule modal did not open.")

    print("Schedule modal opened.")

    # ========================================================
    # INSTALL INTERCEPTOR BEFORE PDF GENERATION
    # ========================================================

    await install_blob_interceptor(page)

    # ========================================================
    # OPEN PDF DROPDOWN
    # ========================================================

    (
        download_button,
        dropdown,
    ) = await open_pdf_dropdown(
        page,
        modal,
    )

    # ========================================================
    # CURRENT RULE
    # ========================================================

    await select_current_rule(
        page,
        dropdown,
    )

    print()
    print("Current Rule selected.")

    # ========================================================
    # RESET CAPTURE BUFFER JUST BEFORE ACTUAL GENERATION
    # ========================================================

    for frame in page.frames:
        try:
            await frame.evaluate("""
                () => {
                    if (
                        window.__mcaCapturedBlobs
                    ) {
                        window.__mcaCapturedBlobs = [];
                    }

                    window.__mcaBlobCounter = 0;
                }
                """)

        except Exception:
            pass

    await page.wait_for_timeout(500)

    # ========================================================
    # CLICK DOWNLOAD ICON
    # ========================================================

    print()
    print("=" * 78)
    print("GENERATING CURRENT RULE PDF")
    print("=" * 78)

    print("Clicking #downloadRuleBtn...")

    await download_button.click()

    print("#downloadRuleBtn clicked.")

    # ========================================================
    # WAIT FOR URL.createObjectURL()
    # ========================================================

    blob_info = await wait_for_captured_blob(page)

    if blob_info is None:
        await save_debug(
            page,
            "blob_create_object_url_not_seen",
        )

        raise RuntimeError("MCA did not call URL.createObjectURL() " "inside any monitored frame.")

    # ========================================================
    # EXTRACT ACTUAL BLOB OBJECT
    # ========================================================

    await extract_captured_blob(
        page,
        blob_info,
        destination,
    )

    # ========================================================
    # VERIFY
    # ========================================================

    verify_pdf(destination)

    # ========================================================
    # MANIFEST
    # ========================================================

    update_manifest(
        original_pdf="blob-pdf",
        saved_filename=filename,
    )

    print()
    print("=" * 78)
    print("SUCCESS")
    print("=" * 78)

    print("Saved:")

    print(destination.resolve())

    print()
    print("Manifest:")

    print(MANIFEST_FILE.resolve())


# ============================================================
# MAIN
# ============================================================


async def main():
    async with async_playwright() as p:

        print()
        print("Launching HEADLESS Firefox...")

        # ====================================================
        # Context-level interception.
        #
        # This installs the createObjectURL hook in every
        # document before MCA's JavaScript executes.
        # ====================================================

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

        await context.add_init_script(BLOB_INTERCEPT_SCRIPT)

        page = await context.new_page()

        page.set_default_timeout(DEFAULT_TIMEOUT)

        # ----------------------------------------------------
        # Optional browser-console diagnostics
        # ----------------------------------------------------

        def console_message(msg):
            text = msg.text

            if "MCA BLOB" in text or "Blob interceptor" in text:
                print()
                print(
                    "[BROWSER]",
                    text,
                )

        page.on(
            "console",
            console_message,
        )

        try:
            # =================================================
            # HOME
            # =================================================

            await open_home(page)

            # =================================================
            # RULES
            # =================================================

            await open_rules_module(page)

            # =================================================
            # COMPANIES ACT
            # =================================================

            await select_companies_act(page)

            # =================================================
            # ALL 54 ROWS
            # =================================================

            await show_all_rows(page)

            # =================================================
            # ONE FAILED PDF
            # =================================================

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

            try:
                await save_debug(
                    page,
                    "schedule_retry_failed",
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
        print("Stopped.")
