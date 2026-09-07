#!/usr/bin/env python3

import asyncio
import csv
import re
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# ============================================================
# CONFIGURATION
# ============================================================

START_URL = "https://www.mca.gov.in/content/mca/global/en/home.html"

TARGET_ACT = "The Companies Act, 2013"
TARGET_ACT_DATA_ID = "J105_D"

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

DEFAULT_TIMEOUT = 30000
DOWNLOAD_TIMEOUT = 60000

NAVIGATION_RETRIES = 10


# ============================================================
# MANIFEST
# ============================================================

MANIFEST_FIELDS = [
    "table_row",
    "rule_group",
    "rule_title",
    "pdf_option",
    "original_pdf",
    "saved_filename",
    "status",
]


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


# ============================================================
# GENERAL HELPERS
# ============================================================


def clean_text(value):
    value = value or ""

    value = value.replace("\xa0", " ")

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


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
    safe_name = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        name,
    )

    try:
        await page.screenshot(
            path=str(DEBUG_DIR / f"{safe_name}.png"),
            full_page=True,
        )
    except Exception:
        pass

    for frame_index, frame in enumerate(page.frames):
        try:
            html = await frame.content()

            (DEBUG_DIR / f"{safe_name}_frame_{frame_index}.html").write_text(
                html,
                encoding="utf-8",
            )

        except Exception:
            pass

    print(f"  Debug saved: {name}")


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


def build_filename(
    document_title,
    rule_title,
    pdf_option,
    original_pdf,
    max_bytes=240,
):
    """
    Requested filename:

    <docRightTitleDefault h1>
    -
    <rulePopup link text>
    -
    <radio option name>
    (<original PDF filename>).pdf
    """

    document_title = sanitize_filename_component(document_title)

    rule_title = sanitize_filename_component(rule_title)

    pdf_option = sanitize_filename_component(pdf_option)

    original_pdf = sanitize_filename_component(original_pdf)

    components = [
        document_title,
        rule_title,
        pdf_option,
    ]

    separator = " - "

    suffix = f" ({original_pdf}).pdf"

    def compose():
        return separator.join(components) + suffix

    filename = compose()

    if len(filename.encode("utf-8")) <= max_bytes:
        return filename

    while len(compose().encode("utf-8")) > max_bytes:
        component_sizes = [len(item.encode("utf-8")) for item in components]

        largest_index = max(
            range(len(components)),
            key=lambda index: component_sizes[index],
        )

        if component_sizes[largest_index] <= 16:
            break

        components[largest_index] = truncate_utf8(
            components[largest_index],
            max(
                16,
                component_sizes[largest_index] - 8,
            ),
        )

    filename = compose()

    if len(filename.encode("utf-8")) > max_bytes:
        available = max_bytes - len(suffix.encode("utf-8"))

        filename = (
            truncate_utf8(
                separator.join(components),
                available,
            )
            + suffix
        )

    return filename


# ============================================================
# DUPLICATE CHECK
# ============================================================


def original_pdf_already_downloaded(
    original_pdf,
):
    """
    Download folder is authoritative.

    Generated filename example:

        Rule Set - Rule 3 - Amendment
        (GSR123.pdf).pdf

    We extract:
        GSR123.pdf

    and compare with current suggested filename.
    """

    wanted = clean_text(original_pdf).lower()

    if not wanted:
        return False

    for path in DOWNLOAD_DIR.glob("*.pdf"):
        match = re.search(
            r"\(([^()]+\.pdf)\)\.pdf$",
            path.name,
            re.I,
        )

        if not match:
            continue

        existing = clean_text(match.group(1)).lower()

        if existing == wanted:
            return True

    return False


# ============================================================
# OPEN HOME
# ============================================================


async def open_home(
    page,
):
    print()
    print("=" * 78)
    print("OPENING MCA HOME")
    print("=" * 78)

    await page.goto(
        START_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(1200)

    print(
        "URL:",
        page.url,
    )


# ============================================================
# FIND ACTS & RULES LINK
# ============================================================


async def find_acts_rules_link(
    page,
):
    selectors = [
        (".second-navigation " 'a[href="/content/mca/global/en/acts-rules.html"]'),
        ('a[href="/content/mca/global/en/acts-rules.html"]'),
    ]

    for selector in selectors:
        locator = page.locator(selector)

        count = await locator.count()

        print(f"Acts & Rules selector " f"{selector!r}: {count}")

        for index in range(count):
            candidate = locator.nth(index)

            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                pass

    return None


# ============================================================
# FIND RULES LINK
# ============================================================


async def find_rules_link_fast(
    page,
    timeout_seconds=8,
):
    """
    Rules lives under:

        .second-navigation
            .ebooknavigation
                a.menuClick[data-doccategory="Rules"]
    """

    selectors = [
        (
            ".second-navigation "
            ".ebooknavigation "
            "a.menuClick"
            '[data-doccategory="Rules"]'
            '[data-redirect="/ebooks/rules.html"]'
        ),
        (".ebooknavigation " "a.menuClick" '[data-doccategory="Rules"]'),
        ("a.menuClick" '[data-doccategory="Rules"]' '[data-redirect="/ebooks/rules.html"]'),
        ('a[data-doccategory="Rules"]' '[data-redirect="/ebooks/rules.html"]'),
        ('a[val="Rules"]' '[data-redirect="/ebooks/rules.html"]'),
    ]

    loop = asyncio.get_running_loop()

    started = loop.time()

    attempt = 0

    while loop.time() - started < timeout_seconds:
        attempt += 1

        print(
            f"  Rules DOM check {attempt}:",
            page.url,
        )

        if is_home_url(page.url):
            return (
                None,
                None,
            )

        for frame_index, frame in enumerate(page.frames):
            for selector in selectors:
                try:
                    locator = frame.locator(selector)

                    count = await locator.count()

                except Exception:
                    continue

                if not count:
                    continue

                print(f"    MATCH in frame " f"#{frame_index}")

                for index in range(count):
                    candidate = locator.nth(index)

                    try:
                        text = clean_text(await candidate.inner_text())
                    except Exception:
                        text = ""

                    redirect = await candidate.get_attribute("data-redirect") or ""

                    category = await candidate.get_attribute("data-doccategory") or ""

                    val = await candidate.get_attribute("val") or ""

                    try:
                        visible = await candidate.is_visible()
                    except Exception:
                        visible = False

                    print(
                        "      text:",
                        repr(text),
                    )

                    print(
                        "      redirect:",
                        repr(redirect),
                    )

                    print(
                        "      category:",
                        repr(category),
                    )

                    print(
                        "      val:",
                        repr(val),
                    )

                    print(
                        "      visible:",
                        visible,
                    )

                    if not visible:
                        continue

                    if redirect == "/ebooks/rules.html" and (
                        category.lower() == "rules"
                        or val.lower() == "rules"
                        or text.lower() == "rules"
                    ):
                        return (
                            frame,
                            candidate,
                        )

        await page.wait_for_timeout(100)

    return (
        None,
        None,
    )


# ============================================================
# WAIT FOR RULES FORM
# ============================================================


async def wait_for_rules_form(
    page,
    timeout_seconds=15,
):
    loop = asyncio.get_running_loop()

    started = loop.time()

    while loop.time() - started < timeout_seconds:
        if is_home_url(page.url):
            return None

        for frame_index, frame in enumerate(page.frames):
            try:
                dropdown = frame.locator("#DropDown_RuleAct")

                if await dropdown.count() == 0:
                    continue

                print("  #DropDown_RuleAct " f"found in frame " f"#{frame_index}")

                return frame

            except Exception:
                pass

        await page.wait_for_timeout(100)

    return None


# ============================================================
# ATOMIC RULES LINK CLICK
# ============================================================


async def click_rules_atomically(
    frame,
):
    """
    Re-find the element inside one JS execution,
    then click immediately.

    This reduces stale-locator problems on MCA.
    """

    return await frame.evaluate("""
        () => {
            const selectors = [
                '.second-navigation '
                + '.ebooknavigation '
                + 'a.menuClick'
                + '[data-doccategory="Rules"]'
                + '[data-redirect="/ebooks/rules.html"]',

                '.ebooknavigation '
                + 'a.menuClick'
                + '[data-doccategory="Rules"]',

                'a.menuClick'
                + '[data-doccategory="Rules"]'
                + '[data-redirect="/ebooks/rules.html"]',

                'a[data-doccategory="Rules"]'
                + '[data-redirect="/ebooks/rules.html"]'
            ];

            let link = null;

            for (
                const selector
                of selectors
            ) {
                link =
                    document.querySelector(
                        selector
                    );

                if (link) {
                    break;
                }
            }

            if (!link) {
                return {
                    ok: false,
                    reason:
                        'Rules link not found'
                };
            }

            const descriptor = {
                text:
                    (
                        link.textContent
                        || ''
                    )
                    .replace(/\\s+/g, ' ')
                    .trim(),

                redirect:
                    link.getAttribute(
                        'data-redirect'
                    ) || '',

                category:
                    link.getAttribute(
                        'data-doccategory'
                    ) || '',

                val:
                    link.getAttribute(
                        'val'
                    ) || ''
            };

            link.click();

            return {
                ok: true,
                descriptor:
                    descriptor
            };
        }
        """)


# ============================================================
# ROBUST HOME -> ACTS & RULES -> RULES
# ============================================================


async def open_rules_module(
    page,
):
    for navigation_attempt in range(
        1,
        NAVIGATION_RETRIES + 1,
    ):
        print()
        print("=" * 78)

        print(f"RULES NAVIGATION ATTEMPT " f"{navigation_attempt}/" f"{NAVIGATION_RETRIES}")

        print("=" * 78)

        # ====================================================
        # ENSURE HOME
        # ====================================================

        if not is_home_url(page.url):
            await open_home(page)

        # ====================================================
        # ACTS & RULES
        # ====================================================

        print()
        print("=" * 78)
        print("OPENING ACTS & RULES")
        print("=" * 78)

        acts_link = await find_acts_rules_link(page)

        if acts_link is None:
            print("Acts & Rules link not found.")

            await open_home(page)

            continue

        print("Acts & Rules link found.")

        print(
            "href:",
            repr(await acts_link.get_attribute("href")),
        )

        print("Clicking Acts & Rules...")

        try:
            await acts_link.click(
                timeout=10000,
            )

        except Exception as exc:
            print(
                "Normal click failed:",
                repr(exc),
            )

            try:
                await acts_link.click(
                    force=True,
                )

            except Exception as force_exc:
                print(
                    "Force click failed:",
                    repr(force_exc),
                )

                await open_home(page)

                continue

        # ====================================================
        # DETECT EBOOK PAGE QUICKLY
        # ====================================================

        ebooks_detected = False

        for _ in range(120):
            if is_ebooks_url(page.url):
                ebooks_detected = True
                break

            await page.wait_for_timeout(50)

        if not ebooks_detected:
            print("eBooks page was not " "detected.")

            print(
                "Current URL:",
                page.url,
            )

            await open_home(page)

            continue

        print(
            "eBooks page detected:",
            page.url,
        )

        # ====================================================
        # FIND RULES IMMEDIATELY
        # ====================================================

        print()
        print("Searching eBook navigation " "for Rules...")

        (
            rules_link_frame,
            rules_link,
        ) = await find_rules_link_fast(
            page,
            timeout_seconds=8,
        )

        if rules_link is None:
            print("Rules link was not found " "or MCA returned home.")

            await open_home(page)

            continue

        print()
        print("RULES LINK FOUND")

        print(
            "Text:",
            repr(clean_text(await rules_link.inner_text())),
        )

        print(
            "data-redirect:",
            repr(await rules_link.get_attribute("data-redirect")),
        )

        # ====================================================
        # VERIFY DOM DIDN'T DISAPPEAR
        # ====================================================

        if is_home_url(page.url):
            print("Rules DOM did not stay stable.")

            await open_home(page)

            continue

        # ====================================================
        # ATOMIC CLICK
        # ====================================================

        print("Clicking Rules atomically...")

        try:
            result = await click_rules_atomically(rules_link_frame)

            print(
                "Rules click result:",
                result,
            )

        except Exception as exc:
            print(
                "Atomic Rules click failed:",
                repr(exc),
            )

            await open_home(page)

            continue

        if not result.get("ok"):
            print("Rules atomic click " "was unsuccessful.")

            await open_home(page)

            continue

        # ====================================================
        # WAIT FOR #DropDown_RuleAct
        # ====================================================

        rules_context = await wait_for_rules_form(
            page,
            timeout_seconds=15,
        )

        if rules_context is None:
            print("Rules click did not load " "the Rules form.")

            print(
                "Current URL:",
                page.url,
            )

            if is_home_url(page.url):
                print("MCA returned to home. " "Retrying complete flow.")

            await open_home(page)

            continue

        print()
        print("=" * 78)
        print("RULES MODULE LOADED")
        print("=" * 78)

        print(
            "Current URL:",
            page.url,
        )

        print(
            "Rules context:",
            rules_context.url,
        )

        print("=" * 78)

        return rules_context

    await save_debug(
        page,
        "rules_navigation_failed_all_retries",
    )

    raise RuntimeError("Could not load MCA Rules module " f"after {NAVIGATION_RETRIES} attempts.")


# ============================================================
# SELECT COMPANIES ACT + CLICK GO ATOMICALLY
# ============================================================


async def select_companies_act_and_click_go(
    page,
):
    print()
    print("=" * 78)
    print("SELECTING THE COMPANIES ACT, 2013")
    print("=" * 78)

    # ========================================================
    # FIND LIVE RULES FRAME
    # ========================================================

    rules_frame = None

    for attempt in range(
        1,
        101,
    ):
        if is_home_url(page.url):
            raise RuntimeError("MCA returned to home before " "Act selection.")

        for frame_index, frame in enumerate(page.frames):
            try:
                dropdown = frame.locator("#DropDown_RuleAct")

                if await dropdown.count() == 0:
                    continue

                rules_frame = frame

                print("#DropDown_RuleAct found " f"in frame #{frame_index}")

                break

            except Exception:
                pass

        if rules_frame is not None:
            break

        await page.wait_for_timeout(50)

    if rules_frame is None:
        raise RuntimeError("#DropDown_RuleAct disappeared " "before selection.")

    # ========================================================
    # PRINT OPTIONS
    # ========================================================

    dropdown = rules_frame.locator("#DropDown_RuleAct")

    options = dropdown.locator("option")

    option_count = await options.count()

    print(
        "Options:",
        option_count,
    )

    target_index = None

    for index in range(option_count):
        option = options.nth(index)

        text = clean_text(await option.inner_text())

        data_id = await option.get_attribute("data-id") or ""

        try:
            selected = await option.evaluate("option => option.selected")
        except Exception:
            selected = False

        print(f"  [{index}] " f"{text!r} " f"data-id={data_id!r} " f"selected={selected}")

        if text == TARGET_ACT or data_id == TARGET_ACT_DATA_ID:
            target_index = index

    if target_index is None:
        raise RuntimeError("The Companies Act, 2013 " "option was not found.")

    print(
        "Target option index:",
        target_index,
    )

    # ========================================================
    # ONE JS OPERATION:
    #
    # - select J105_D
    # - fire input/change
    # - invoke enableclickGoButton if available
    # - immediately find #clickGo
    # - immediately click it
    # ========================================================

    result = await rules_frame.evaluate("""
        () => {
            const select =
                document.querySelector(
                    '#DropDown_RuleAct'
                );

            if (!select) {
                return {
                    ok: false,
                    stage: 'dropdown',
                    reason:
                        '#DropDown_RuleAct not found'
                };
            }

            const options =
                Array.from(
                    select.options
                );

            let targetIndex =
                options.findIndex(
                    option =>
                        (
                            option.getAttribute(
                                'data-id'
                            ) || ''
                        ) === 'J105_D'
                );

            if (targetIndex < 0) {
                targetIndex =
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
                            ===
                            'The Companies Act, 2013'
                    );
            }

            if (targetIndex < 0) {
                return {
                    ok: false,
                    stage: 'selection',
                    reason:
                        'Companies Act option not found'
                };
            }

            select.selectedIndex =
                targetIndex;

            for (
                let i = 0;
                i < options.length;
                i++
            ) {
                options[i].selected =
                    i === targetIndex;
            }

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
            catch (error) {}

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
            catch (error) {}

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
            catch (error) {}

            const selected =
                select.options[
                    select.selectedIndex
                ];

            const go =
                document.querySelector(
                    '#clickGo'
                );

            if (!go) {
                return {
                    ok: false,
                    stage: 'go',
                    reason:
                        '#clickGo not found',

                    selectedText:
                        selected
                        ? (
                            selected.textContent
                            || ''
                        )
                        .replace(
                            /\\s+/g,
                            ' '
                        )
                        .trim()
                        : '',

                    selectedDataId:
                        selected
                        ? (
                            selected.getAttribute(
                                'data-id'
                            )
                            || ''
                        )
                        : ''
                };
            }

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

            const descriptor = {
                selectedText:
                    selected
                    ? (
                        selected.textContent
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim()
                    : '',

                selectedDataId:
                    selected
                    ? (
                        selected.getAttribute(
                            'data-id'
                        )
                        || ''
                    )
                    : '',

                selectedIndex:
                    select.selectedIndex,

                goText:
                    (
                        go.textContent
                        || ''
                    )
                    .replace(
                        /\\s+/g,
                        ' '
                    )
                    .trim(),

                goDisabled:
                    !!go.disabled,

                goDisabledAttr:
                    go.getAttribute(
                        'disabled'
                    ),

                goDisabled1:
                    go.getAttribute(
                        'disabled1'
                    )
            };

            go.click();

            return {
                ok: true,
                descriptor:
                    descriptor
            };
        }
        """)

    print(
        "Atomic Act + Go result:",
        result,
    )

    if not result or not result.get("ok"):
        raise RuntimeError(
            "Could not atomically select " "Companies Act and click Go: " f"{result}"
        )

    descriptor = result.get("descriptor") or {}

    print(
        "Selected:",
        descriptor.get("selectedText"),
    )

    print(
        "Selected data-id:",
        descriptor.get("selectedDataId"),
    )

    print(
        "Go text:",
        descriptor.get("goText"),
    )

    print(
        "Go disabled:",
        descriptor.get("goDisabled"),
    )

    print(
        "Go disabled1:",
        descriptor.get("goDisabled1"),
    )

    # ========================================================
    # REACQUIRE LIVE RESULT CONTEXT
    # ========================================================

    print()
    print("Waiting for Rules results...")

    result_context = None

    for attempt in range(
        1,
        121,
    ):
        if is_home_url(page.url):
            raise RuntimeError("MCA returned to home " "after clicking Go.")

        for frame_index, frame in enumerate(page.frames):
            try:
                table = frame.locator("#rulesContainer")

                if await table.count() == 0:
                    continue

                result_context = frame

                row_count = await frame.locator("#rulesContainer tbody tr").count()

                print("  Results detected " f"in frame #{frame_index}: " f"{row_count} row(s)")

                break

            except Exception:
                pass

        if result_context is not None:
            break

        if attempt % 10 == 0:
            print(f"  Still waiting " f"{attempt}/120...")

        await page.wait_for_timeout(100)

    if result_context is None:
        raise RuntimeError("#rulesContainer did not appear " "after clicking Go.")

    # ========================================================
    # WAIT FOR REAL .ruleLink ROWS
    # ========================================================

    rows = result_context.locator("#rulesContainer tbody tr")

    for attempt in range(
        1,
        101,
    ):
        row_count = await rows.count()

        useful_rows = 0

        for index in range(row_count):
            try:
                if await rows.nth(index).locator(".ruleLink").count() > 0:
                    useful_rows += 1
            except Exception:
                pass

        if useful_rows:
            print("Rules table loaded.")

            print(
                "Initial displayed rows:",
                row_count,
            )

            print(
                "Rows containing .ruleLink:",
                useful_rows,
            )

            return result_context

        await page.wait_for_timeout(100)

    raise RuntimeError("#rulesContainer appeared, " "but no .ruleLink data rows " "were loaded.")


# ============================================================
# FIND DATATABLE LENGTH DROPDOWN
# ============================================================


async def find_length_dropdown(
    rules_context,
):
    selectors = [
        ('select[name="rulesContainer_length"]'),
        ('select[aria-controls="rulesContainer"]'),
        ("#rulesContainer_length select"),
        (".dataTables_length " 'select[aria-controls="rulesContainer"]'),
        (".dataTables_length select"),
        ("select.custom-select" '[aria-controls="rulesContainer"]'),
    ]

    for attempt in range(
        1,
        31,
    ):
        for selector in selectors:
            try:
                locator = rules_context.locator(selector)

                count = await locator.count()

            except Exception:
                continue

            if count:
                print("  Length selector " "matched:")

                print(f"    {selector}")

                print(f"    count={count}")

            for index in range(count):
                candidate = locator.nth(index)

                try:
                    visible = await candidate.is_visible()
                except Exception:
                    visible = False

                if visible:
                    return candidate

        await asyncio.sleep(0.5)

    return None


# ============================================================
# SELECT ALL RULE TABLE ROWS
# ============================================================


async def select_all_rules(
    rules_context,
):
    print()
    print("=" * 78)
    print("SELECTING ALL RULE ROWS")
    print("=" * 78)

    rows = rules_context.locator("#rulesContainer tbody tr")

    before_count = await rows.count()

    print(
        "Current displayed rows:",
        before_count,
    )

    dropdown = await find_length_dropdown(rules_context)

    # ========================================================
    # NORMAL DROPDOWN
    # ========================================================

    if dropdown is not None:
        print("DataTables length dropdown found.")

        try:
            options = dropdown.locator("option")

            print("Options:")

            for index in range(await options.count()):
                option = options.nth(index)

                value = await option.get_attribute("value")

                text = clean_text(await option.inner_text())

                print(f"  {value!r} " f"=> {text!r}")

        except Exception:
            pass

        selected = False

        try:
            await dropdown.select_option(value="-1")

            print("Selected value=-1.")

            selected = True

        except Exception as exc:
            print(
                "Selecting value=-1 " "failed:",
                repr(exc),
            )

        if not selected:
            try:
                await dropdown.select_option(label="All")

                print("Selected label='All'.")

                selected = True

            except Exception as exc:
                print(
                    "Selecting label='All' " "failed:",
                    repr(exc),
                )

        if selected:
            await asyncio.sleep(1.5)

    # ========================================================
    # CHECK ROWS
    # ========================================================

    after_dropdown_count = await rows.count()

    print(
        "Rows after dropdown attempt:",
        after_dropdown_count,
    )

    # ========================================================
    # DATATABLE API FALLBACK
    # ========================================================

    if dropdown is None or (before_count <= 50 and after_dropdown_count <= before_count):
        print()
        print("Trying DataTables " "JavaScript API fallback...")

        try:
            api_result = await rules_context.evaluate("""
                    () => {
                        try {
                            if (
                                typeof window.jQuery
                                === 'undefined'
                            ) {
                                return {
                                    ok: false,
                                    reason:
                                        'jQuery missing'
                                };
                            }

                            const $ =
                                window.jQuery;

                            if (
                                !$.fn
                                ||
                                !$.fn.DataTable
                            ) {
                                return {
                                    ok: false,
                                    reason:
                                        'DataTables missing'
                                };
                            }

                            if (
                                !$.fn.DataTable
                                    .isDataTable(
                                        '#rulesContainer'
                                    )
                            ) {
                                return {
                                    ok: false,
                                    reason:
                                        'rulesContainer '
                                        + 'is not a DataTable'
                                };
                            }

                            const table =
                                $(
                                    '#rulesContainer'
                                )
                                .DataTable();

                            const before =
                                table.rows({
                                    search: 'applied'
                                }).count();

                            table
                                .page
                                .len(-1)
                                .draw(false);

                            return {
                                ok: true,
                                before:
                                    before,
                                pageLength:
                                    table.page.len()
                            };
                        }
                        catch (error) {
                            return {
                                ok: false,
                                reason:
                                    String(error)
                            };
                        }
                    }
                    """)

        except Exception as exc:
            api_result = {
                "ok": False,
                "reason": repr(exc),
            }

        print(
            "DataTables API result:",
            api_result,
        )

        if api_result.get("ok"):
            await asyncio.sleep(1.5)

    # ========================================================
    # MANUAL CHANGE EVENT FALLBACK
    # ========================================================

    current_count = await rows.count()

    if dropdown is not None and current_count <= before_count:
        print()
        print("Trying manual dropdown " "change event...")

        try:
            await dropdown.evaluate("""
                element => {
                    element.value = '-1';

                    element.dispatchEvent(
                        new Event(
                            'change',
                            {
                                bubbles: true
                            }
                        )
                    );
                }
                """)

            await asyncio.sleep(1.5)

        except Exception as exc:
            print(
                "Manual dropdown change " "failed:",
                repr(exc),
            )

    # ========================================================
    # FINAL INFO
    # ========================================================

    final_count = await rows.count()

    print()
    print(
        "Final displayed rule rows:",
        final_count,
    )

    try:
        table_info = await rules_context.evaluate("""
                () => {
                    try {
                        if (
                            window.jQuery
                            &&
                            jQuery.fn
                            &&
                            jQuery.fn.DataTable
                            &&
                            jQuery.fn.DataTable
                                .isDataTable(
                                    '#rulesContainer'
                                )
                        ) {
                            const table =
                                jQuery(
                                    '#rulesContainer'
                                )
                                .DataTable();

                            return {
                                total:
                                    table.rows()
                                    .count(),

                                filtered:
                                    table.rows({
                                        search: 'applied'
                                    }).count(),

                                pageLength:
                                    table.page.len(),

                                pageInfo:
                                    table.page.info()
                            };
                        }

                        return null;
                    }
                    catch (error) {
                        return {
                            error:
                                String(error)
                        };
                    }
                }
                """)

        print(
            "DataTables info:",
            table_info,
        )

    except Exception as exc:
        print(
            "Could not read " "DataTables info:",
            repr(exc),
        )

    if final_count == 0:
        raise RuntimeError("No rule rows available " "after selecting All.")

    print("=" * 78)

    return final_count


# ============================================================
# RULE POPUP LOCATOR
# ============================================================


def rule_popup_locator(
    rules_context,
):
    return rules_context.locator(
        (
            ".resaultContentContainer "
            ".contentContainer "
            "ol.rulesListPopContainer "
            "li.pop a.rulePopup, "
            ".resultContentContainer "
            ".contentContainer "
            "ol.rulesListPopContainer "
            "li.pop a.rulePopup, "
            "ol.rulesListPopContainer "
            "li.pop a.rulePopup"
        )
    )


# ============================================================
# DOCUMENT TITLE
# ============================================================


async def get_document_title(
    rules_context,
):
    selectors = [
        "#docRightTitleDefault h1",
        ".docRightTitleDefault h1",
        "h1#docRightTitleDefault",
        "#docRightTitleDefault",
    ]

    for selector in selectors:
        try:
            locator = rules_context.locator(selector)

            if await locator.count() == 0:
                continue

            text = clean_text(await locator.first.inner_text())

            if text:
                return text

        except Exception:
            pass

    return "Rules"


# ============================================================
# OPEN ONE TABLE ROW
# ============================================================


async def open_rule_table_row(
    rules_context,
    row_index,
):
    rows = rules_context.locator("#rulesContainer tbody tr")

    row_count = await rows.count()

    if row_index >= row_count:
        raise RuntimeError(f"Rule row " f"{row_index + 1} " "no longer exists.")

    row = rows.nth(row_index)

    rule_link = row.locator(".ruleLink")

    if await rule_link.count() == 0:
        raise RuntimeError(f"No .ruleLink found " f"in table row " f"{row_index + 1}.")

    rule_link = rule_link.first

    link_text = clean_text(await rule_link.inner_text())

    print()
    print("#" * 78)

    print(f"RULE TABLE ROW " f"{row_index + 1}/" f"{row_count}")

    print("#" * 78)

    print(
        "ruleLink:",
        repr(link_text),
    )

    try:
        await rule_link.scroll_into_view_if_needed()
    except Exception:
        pass

    try:
        await rule_link.click(
            timeout=15000,
        )

    except Exception:
        await rule_link.click(
            force=True,
        )

    popup_links = rule_popup_locator(rules_context)

    await popup_links.first.wait_for(
        state="visible",
        timeout=30000,
    )

    popup_count = await popup_links.count()

    document_title = await get_document_title(rules_context)

    print(
        "docRightTitleDefault:",
        repr(document_title),
    )

    print(
        "rulePopup count:",
        popup_count,
    )

    return (
        document_title,
        popup_count,
    )


# ============================================================
# ACTIVE MODAL
# ============================================================


async def get_active_modal(
    rules_context,
):
    selectors = [
        ".modal.show .modal-dialog.modal-sm",
        ".modal-dialog.modal-sm:visible",
        ".modal-dialog.modal-sm",
    ]

    for selector in selectors:
        try:
            locator = rules_context.locator(selector)

            count = await locator.count()

        except Exception:
            continue

        for index in range(count):
            modal = locator.nth(index)

            try:
                if await modal.is_visible():
                    return modal

            except Exception:
                pass

    return None


# ============================================================
# OPEN PDF DOWNLOAD DROPDOWN
# ============================================================


async def open_pdf_dropdown(
    rules_context,
    modal,
):
    # Prefer dropdown inside active modal.
    area = modal.locator(".rulespdfDownload")

    if await area.count() == 0:
        area = rules_context.locator(".rulespdfDownload:visible")

    if await area.count() == 0:
        raise RuntimeError(".rulespdfDownload not found.")

    area = area.first

    clicked = False

    for selector in [
        ".dropdown-toggle",
        "button",
        "a",
    ]:
        try:
            candidate = area.locator(selector)

            if await candidate.count() == 0:
                continue

            await candidate.first.click(force=True)

            clicked = True
            break

        except Exception:
            pass

    if not clicked:
        try:
            await area.click(force=True)

            clicked = True
        except Exception:
            pass

    # Prefer dropdown scoped to modal.
    modal_dropdown = modal.locator("#mypdfDropdown")

    if await modal_dropdown.count() > 0:
        dropdown = modal_dropdown.first
    else:
        dropdown = rules_context.locator("#mypdfDropdown").first

    await dropdown.wait_for(
        state="attached",
        timeout=10000,
    )

    return dropdown


# ============================================================
# RADIO OPTION NAME
# ============================================================


async def get_radio_option_name(
    rules_context,
    dropdown,
    radio,
):
    """
    Preference:

    1. label[for=id]
    2. closest label
    3. nearby parent text
    4. useful attributes
    """

    radio_id = await radio.get_attribute("id") or ""

    if radio_id:
        try:
            label = rules_context.locator(f'label[for="{radio_id}"]')

            if await label.count() > 0:
                text = clean_text(await label.first.inner_text())

                if text:
                    return text

        except Exception:
            pass

    try:
        text = clean_text(await radio.evaluate("""
                element => {
                    const label =
                        element.closest(
                            'label'
                        );

                    if (label) {
                        return (
                            label.innerText
                            || ''
                        );
                    }

                    const parent =
                        element.parentElement;

                    if (parent) {
                        return (
                            parent.innerText
                            || ''
                        );
                    }

                    return '';
                }
                """))

        if text:
            return text

    except Exception:
        pass

    for attribute in [
        "data-name",
        "data-title",
        "title",
        "value",
        "name",
        "id",
    ]:
        try:
            value = clean_text(await radio.get_attribute(attribute) or "")

            if value:
                return value

        except Exception:
            pass

    return "PDF"


# ============================================================
# ORIGINAL DOWNLOAD NAME
# ============================================================


def get_original_download_name(
    download,
):
    """
    Playwright's suggested_filename should
    be authoritative for the original
    downloaded filename.
    """

    suggested = clean_text(download.suggested_filename or "")

    if suggested:
        return suggested

    return "document.pdf"


# ============================================================
# CLOSE MODAL
# ============================================================


async def close_modal(
    page,
    modal,
):
    selectors = [
        "button.close",
        ".close",
        'button[data-dismiss="modal"]',
        'button[data-bs-dismiss="modal"]',
    ]

    for selector in selectors:
        try:
            control = modal.locator(selector)

            if await control.count() == 0:
                continue

            if not await control.first.is_visible():
                continue

            await control.first.click(force=True)

            await page.wait_for_timeout(300)

            return

        except Exception:
            pass

    try:
        await page.keyboard.press("Escape")

        await page.wait_for_timeout(300)

    except Exception:
        pass


# ============================================================
# DOWNLOAD EVERY PDF FOR ONE rulePopup
# ============================================================


async def download_rule_popup_pdfs(
    page,
    rules_context,
    table_row_number,
    document_title,
    popup_index,
    manifest_rows,
):
    # Reacquire links each time.
    popup_links = rule_popup_locator(rules_context)

    popup_count = await popup_links.count()

    if popup_index >= popup_count:
        raise RuntimeError("rulePopup index disappeared.")

    popup_link = popup_links.nth(popup_index)

    rule_title = clean_text(await popup_link.inner_text())

    print()
    print("-" * 78)

    print(f"RULE POPUP " f"{popup_index + 1}/" f"{popup_count}")

    print("-" * 78)

    print(
        "Rule:",
        repr(rule_title),
    )

    try:
        await popup_link.scroll_into_view_if_needed()
    except Exception:
        pass

    try:
        await popup_link.click(
            timeout=15000,
        )

    except Exception:
        await popup_link.click(
            force=True,
        )

    # ========================================================
    # WAIT FOR MODAL
    # ========================================================

    modal = None

    for _ in range(60):
        modal = await get_active_modal(rules_context)

        if modal is not None:
            break

        await page.wait_for_timeout(100)

    if modal is None:
        raise RuntimeError(f"Modal did not open " f"for {rule_title!r}.")

    print("  Modal opened.")

    # ========================================================
    # OPEN PDF DROPDOWN
    # ========================================================

    dropdown = await open_pdf_dropdown(
        rules_context,
        modal,
    )

    radios = dropdown.locator('input[type="radio"]')

    radio_count = await radios.count()

    if radio_count == 0:
        # Fallback global.
        radios = rules_context.locator("#mypdfDropdown " 'input[type="radio"]')

        radio_count = await radios.count()

    print(
        "  PDF options:",
        radio_count,
    )

    if radio_count == 0:
        raise RuntimeError("No PDF radio buttons " "were found.")

    # ========================================================
    # EACH RADIO OPTION
    # ========================================================

    for radio_index in range(radio_count):
        # Reacquire modal/dropdown because
        # Bootstrap may close/re-render.
        modal = await get_active_modal(rules_context)

        if modal is None:
            raise RuntimeError("Modal disappeared while " "processing PDF options.")

        dropdown = await open_pdf_dropdown(
            rules_context,
            modal,
        )

        radios = dropdown.locator('input[type="radio"]')

        current_count = await radios.count()

        if current_count == 0:
            radios = rules_context.locator("#mypdfDropdown " 'input[type="radio"]')

            current_count = await radios.count()

        if radio_index >= current_count:
            print(
                "  Radio index disappeared:",
                radio_index,
            )

            continue

        radio = radios.nth(radio_index)

        option_name = await get_radio_option_name(
            rules_context,
            dropdown,
            radio,
        )

        print()
        print(f"  PDF option " f"{radio_index + 1}/" f"{current_count}: " f"{option_name!r}")

        # ====================================================
        # EXPECT REAL BROWSER DOWNLOAD
        # ====================================================

        try:
            async with page.expect_download(
                timeout=DOWNLOAD_TIMEOUT,
            ) as download_info:

                await radio.click(force=True)

            download = await download_info.value

        except PlaywrightTimeoutError:
            print("    ERROR: radio click " "did not trigger a browser " "download.")

            manifest_rows.append(
                {
                    "table_row": table_row_number,
                    "rule_group": document_title,
                    "rule_title": rule_title,
                    "pdf_option": option_name,
                    "original_pdf": "",
                    "saved_filename": "",
                    "status": "ERROR: no download triggered",
                }
            )

            save_manifest(manifest_rows)

            continue

        # ====================================================
        # ORIGINAL FILENAME
        # ====================================================

        original_pdf = get_original_download_name(download)

        print(
            "    Original PDF:",
            original_pdf,
        )

        # ====================================================
        # DUPLICATE CHECK
        # ====================================================

        if original_pdf_already_downloaded(original_pdf):
            print("    DUPLICATE - skipping.")

            try:
                await download.delete()
            except Exception:
                pass

            manifest_rows.append(
                {
                    "table_row": table_row_number,
                    "rule_group": document_title,
                    "rule_title": rule_title,
                    "pdf_option": option_name,
                    "original_pdf": original_pdf,
                    "saved_filename": "",
                    "status": "duplicate-skipped",
                }
            )

            save_manifest(manifest_rows)

            continue

        # ====================================================
        # BUILD FINAL NAME
        # ====================================================

        filename = build_filename(
            document_title,
            rule_title,
            option_name,
            original_pdf,
        )

        destination = DOWNLOAD_DIR / filename

        if destination.exists():
            print("    Exact destination " "already exists - skipping.")

            try:
                await download.delete()
            except Exception:
                pass

            manifest_rows.append(
                {
                    "table_row": table_row_number,
                    "rule_group": document_title,
                    "rule_title": rule_title,
                    "pdf_option": option_name,
                    "original_pdf": original_pdf,
                    "saved_filename": destination.name,
                    "status": "destination-exists",
                }
            )

            save_manifest(manifest_rows)

            continue

        await download.save_as(str(destination))

        print(
            "    SAVED:",
            destination.name,
        )

        manifest_rows.append(
            {
                "table_row": table_row_number,
                "rule_group": document_title,
                "rule_title": rule_title,
                "pdf_option": option_name,
                "original_pdf": original_pdf,
                "saved_filename": destination.name,
                "status": "downloaded",
            }
        )

        save_manifest(manifest_rows)

        await page.wait_for_timeout(300)

    # ========================================================
    # CLOSE CURRENT MODAL
    # ========================================================

    modal = await get_active_modal(rules_context)

    if modal is not None:
        await close_modal(
            page,
            modal,
        )


# ============================================================
# PROCESS ALL RULE TABLE ROWS
# ============================================================


async def process_all_rules(
    page,
    rules_context,
):
    manifest_rows = []

    rows = rules_context.locator("#rulesContainer tbody tr")

    total_rows = await rows.count()

    print()
    print("=" * 78)
    print("RULE DOWNLOAD")
    print("=" * 78)

    print(
        "Rule table rows:",
        total_rows,
    )

    print(
        "Download directory:",
        DOWNLOAD_DIR.resolve(),
    )

    print("=" * 78)

    total_popups = 0

    for row_index in range(total_rows):
        try:
            (
                document_title,
                popup_count,
            ) = await open_rule_table_row(
                rules_context,
                row_index,
            )

            total_popups += popup_count

            for popup_index in range(popup_count):
                try:
                    await download_rule_popup_pdfs(
                        page=page,
                        rules_context=rules_context,
                        table_row_number=(row_index + 1),
                        document_title=(document_title),
                        popup_index=(popup_index),
                        manifest_rows=(manifest_rows),
                    )

                except Exception as exc:
                    print()
                    print(
                        "  ERROR processing " "rulePopup:",
                        repr(exc),
                    )

                    await save_debug(
                        page,
                        (f"row_" f"{row_index + 1}_" f"popup_" f"{popup_index + 1}"),
                    )

                    try:
                        modal = await get_active_modal(rules_context)

                        if modal is not None:
                            await close_modal(
                                page,
                                modal,
                            )

                    except Exception:
                        pass

            await page.wait_for_timeout(400)

        except Exception as exc:
            print()
            print(
                f"ERROR processing " f"table row " f"{row_index + 1}:",
                repr(exc),
            )

            await save_debug(
                page,
                (f"rule_table_row_" f"{row_index + 1}_error"),
            )

    save_manifest(manifest_rows)

    downloaded = sum(1 for item in manifest_rows if (item.get("status") == "downloaded"))

    duplicates = sum(1 for item in manifest_rows if (item.get("status") == "duplicate-skipped"))

    errors = sum(1 for item in manifest_rows if (item.get("status", "").startswith("ERROR")))

    print()
    print("=" * 78)
    print("FINAL SUMMARY")
    print("=" * 78)

    print(
        "Rule table rows:",
        total_rows,
    )

    print(
        "Rule popup entries:",
        total_popups,
    )

    print(
        "PDFs downloaded:",
        downloaded,
    )

    print(
        "Duplicates skipped:",
        duplicates,
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
            headless=True,
            args=[
                "--start-maximized",
            ],
        )

        context = await browser.new_context(
            viewport=None,
            accept_downloads=True,
        )

        page = await context.new_page()

        page.set_default_timeout(DEFAULT_TIMEOUT)

        try:
            # =================================================
            # 1. HOME
            # =================================================

            await open_home(page)

            # =================================================
            # 2. ROBUST RULES NAVIGATION
            # =================================================

            await open_rules_module(page)

            # =================================================
            # 3. SELECT COMPANIES ACT + GO ATOMICALLY
            #
            # IMPORTANT:
            # This returns a FRESH result context.
            # =================================================

            rules_context = await select_companies_act_and_click_go(page)

            # =================================================
            # 4. SHOW ALL RULES
            # =================================================

            await select_all_rules(rules_context)

            # =================================================
            # 5. DOWNLOAD
            # =================================================

            await process_all_rules(
                page,
                rules_context,
            )

            # =================================================
            # 6. KEEP OPEN
            # =================================================

            await keep_browser_open()

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

            try:
                await keep_browser_open()

            except KeyboardInterrupt:
                pass


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print()
        print("Script stopped.")
