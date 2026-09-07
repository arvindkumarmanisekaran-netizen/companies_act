#!/usr/bin/env python3

import asyncio
import csv
import re
from pathlib import Path

from playwright.async_api import async_playwright


# ============================================================
# CONFIGURATION
# ============================================================

START_URL = (
    "https://www.mca.gov.in/content/mca/global/en/home.html"
)

RULES_DIRECT_URL = (
    "https://www.mca.gov.in/content/mca/global/en/"
    "acts-rules/ebooks/rules.html"
)

TARGET_ACT = "The Companies Act, 2013"
TARGET_ACT_DATA_ID = "J105_D"

OUTPUT_ROOT = Path(
    "mca_companies_act_2013"
)

DOWNLOAD_DIR = (
    OUTPUT_ROOT / "rules"
)

DEBUG_DIR = (
    OUTPUT_ROOT / "debug"
)

MANIFEST_FILE = (
    DOWNLOAD_DIR / "downloads.csv"
)

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DEBUG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DEFAULT_TIMEOUT = 30000

NAVIGATION_RETRIES = 10

ACT_OPTIONS_TIMEOUT_SECONDS = 60
GO_RESULTS_TIMEOUT_SECONDS = 60

DOWNLOAD_WAIT_SECONDS = 30


# ============================================================
# MANIFEST
# ============================================================

MANIFEST_FIELDS = [
    "table_row",
    "rules",
    "rule_contains",
    "notification_date",
    "rule_title",
    "original_pdf",
    "saved_filename",
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
            return list(
                csv.DictReader(file)
            )

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


# ============================================================
# GENERAL HELPERS
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
        screenshot_path = (
            DEBUG_DIR
            / f"{safe_name}.png"
        )

        await page.screenshot(
            path=str(
                screenshot_path
            ),
            full_page=True,
        )

        print(
            "  Screenshot:",
            screenshot_path.resolve(),
        )

    except Exception:
        pass

    for frame_index, frame in enumerate(
        page.frames
    ):
        try:
            html = await frame.content()

            html_path = (
                DEBUG_DIR
                / (
                    f"{safe_name}_"
                    f"frame_{frame_index}.html"
                )
            )

            html_path.write_text(
                html,
                encoding="utf-8",
            )

        except Exception:
            pass

    print(
        f"  Debug saved: {name}"
    )


# ============================================================
# FILENAME HELPERS
# ============================================================

def sanitize_filename_component(
    value,
):
    value = clean_text(value)

    # Linux cannot use "/" inside a filename.
    # Windows-invalid characters are also cleaned.
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

    value = value.strip(
        " ."
    )

    return value or "NA"


def truncate_utf8(
    value,
    max_bytes,
):
    raw = value.encode(
        "utf-8"
    )

    if len(raw) <= max_bytes:
        return value

    raw = raw[:max_bytes]

    while raw:
        try:
            return (
                raw.decode(
                    "utf-8"
                ).rstrip()
                + "…"
            )

        except UnicodeDecodeError:
            raw = raw[:-1]

    return ""


def normalize_notification_date(
    value,
):
    """
    Example:

    31/03/2014
        ->
    31-03-2014

    Slash cannot be part of a Linux filename.
    """

    value = clean_text(value)

    value = value.replace(
        "/",
        "-",
    )

    return value


def build_filename(
    rules_name,
    rule_contains,
    notification_date,
    rule_title,
    max_bytes=245,
):
    """
    Required logical format:

    Rules - Rule Contains - Notification Date - Individual Rule .pdf

    Example:

    Chapter I The Companies (Specification of Definitions Details) Rules, 2014
    - Rule 1 to 4
    - 31-03-2014
    - 1. Short Title and Commencement .pdf
    """

    rules_name = (
        sanitize_filename_component(
            rules_name
        )
    )

    rule_contains = (
        sanitize_filename_component(
            rule_contains
        )
    )

    notification_date = (
        normalize_notification_date(
            notification_date
        )
    )

    notification_date = (
        sanitize_filename_component(
            notification_date
        )
    )

    rule_title = (
        sanitize_filename_component(
            rule_title
        )
    )

    components = [
        rules_name,
        rule_contains,
        notification_date,
        rule_title,
    ]

    suffix = " .pdf"
    separator = " - "

    def compose():
        return (
            separator.join(
                components
            )
            + suffix
        )

    filename = compose()

    if (
        len(
            filename.encode("utf-8")
        )
        <= max_bytes
    ):
        return filename

    # --------------------------------------------------------
    # Preserve important metadata while shortening long names.
    # Prefer shortening Rules title first, then rule title.
    # --------------------------------------------------------

    shrink_order = [
        0,
        3,
        1,
    ]

    while (
        len(
            compose().encode("utf-8")
        )
        > max_bytes
    ):
        changed = False

        for index in shrink_order:
            current = components[
                index
            ]

            current_bytes = len(
                current.encode("utf-8")
            )

            if current_bytes <= 30:
                continue

            components[index] = (
                truncate_utf8(
                    current,
                    current_bytes - 10,
                )
            )

            changed = True
            break

        if not changed:
            break

    filename = compose()

    return filename


# ============================================================
# DUPLICATE CHECK
# ============================================================

def destination_exists(
    filename,
):
    destination = (
        DOWNLOAD_DIR
        / filename
    )

    return destination.exists()


# ============================================================
# MCA HOME
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

    await page.wait_for_timeout(
        1500
    )

    print(
        "URL:",
        page.url,
    )

    try:
        print(
            "TITLE:",
            await page.title(),
        )

    except Exception:
        pass

    if (
        response is not None
        and response.status >= 400
    ):
        raise RuntimeError(
            "MCA home returned "
            f"HTTP {response.status}"
        )


# ============================================================
# FIND ACTS & RULES LINK
# ============================================================

async def find_acts_rules_link(
    page,
):
    selectors = [
        (
            '.second-navigation '
            'a[href="/content/mca/global/en/acts-rules.html"]'
        ),
        (
            'a[href="/content/mca/global/en/acts-rules.html"]'
        ),
    ]

    for selector in selectors:
        locator = (
            page.locator(
                selector
            )
        )

        count = (
            await locator.count()
        )

        print(
            f"Acts & Rules selector "
            f"{selector!r}: {count}"
        )

        for index in range(
            count
        ):
            candidate = (
                locator.nth(index)
            )

            try:
                if await candidate.is_visible():
                    return candidate

            except Exception:
                pass

    return None


# ============================================================
# WAIT FOR RULES FORM
# ============================================================

async def wait_for_rules_form(
    page,
    timeout_seconds=20,
):
    loop = (
        asyncio.get_running_loop()
    )

    start = loop.time()

    while (
        loop.time() - start
        < timeout_seconds
    ):
        for (
            frame_index,
            frame,
        ) in enumerate(
            page.frames
        ):
            try:
                dropdown = (
                    frame.locator(
                        "#DropDown_RuleAct"
                    )
                )

                if (
                    await dropdown.count()
                    == 0
                ):
                    continue

                print(
                    "#DropDown_RuleAct "
                    "found in frame "
                    f"#{frame_index}"
                )

                return frame

            except Exception:
                pass

        await page.wait_for_timeout(
            100
        )

    return None


# ============================================================
# CLICK RULES
# ============================================================

async def click_rules_real(
    page,
):
    print()
    print(
        "Searching for Rules link "
        "for real Playwright click..."
    )

    selectors = [
        (
            '.ebooknavigation '
            'a.menuClick'
            '[data-doccategory="Rules"]'
        ),
        (
            'a.menuClick'
            '[data-doccategory="Rules"]'
            '[data-redirect="/ebooks/rules.html"]'
        ),
        (
            'a[data-doccategory="Rules"]'
            '[data-redirect="/ebooks/rules.html"]'
        ),
        (
            'a[val="Rules"]'
            '[data-redirect="/ebooks/rules.html"]'
        ),
    ]

    for _ in range(
        100
    ):
        for (
            frame_index,
            frame,
        ) in enumerate(
            page.frames
        ):
            for selector in selectors:
                try:
                    candidates = (
                        frame.locator(
                            selector
                        )
                    )

                    count = (
                        await candidates.count()
                    )

                except Exception:
                    continue

                for index in range(
                    count
                ):
                    candidate = (
                        candidates.nth(index)
                    )

                    try:
                        visible = (
                            await candidate.is_visible()
                        )

                    except Exception:
                        continue

                    if not visible:
                        continue

                    print(
                        "  Rules link found "
                        "in frame "
                        f"#{frame_index}"
                    )

                    print(
                        "  Selector:",
                        selector,
                    )

                    print(
                        "  URL before click:",
                        page.url,
                    )

                    print(
                        "  Performing real "
                        "Playwright click..."
                    )

                    try:
                        await candidate.click(
                            timeout=10000,
                        )

                    except Exception:
                        await candidate.click(
                            force=True,
                        )

                    for _ in range(
                        100
                    ):
                        if (
                            is_rules_url(
                                page.url
                            )
                        ):
                            print(
                                "  Rules URL reached:",
                                page.url,
                            )

                            return True

                        await page.wait_for_timeout(
                            100
                        )

                    return False

        await page.wait_for_timeout(
            100
        )

    return False


# ============================================================
# OPEN RULES MODULE
# ============================================================

async def open_rules_module(
    page,
):
    for attempt in range(
        1,
        NAVIGATION_RETRIES + 1,
    ):
        print()
        print("=" * 78)

        print(
            "RULES NAVIGATION ATTEMPT "
            f"{attempt}/"
            f"{NAVIGATION_RETRIES}"
        )

        print("=" * 78)

        if not is_home_url(
            page.url
        ):
            await open_home(
                page
            )

        print()
        print("=" * 78)
        print("OPENING ACTS & RULES")
        print("=" * 78)

        acts_link = (
            await find_acts_rules_link(
                page
            )
        )

        if acts_link is None:
            await open_home(
                page
            )

            continue

        print(
            "Acts & Rules link found."
        )

        try:
            print(
                "href:",
                repr(
                    await acts_link.get_attribute(
                        "href"
                    )
                ),
            )

        except Exception:
            pass

        print(
            "Clicking Acts & Rules..."
        )

        try:
            await acts_link.click(
                timeout=10000,
            )

        except Exception:
            await acts_link.click(
                force=True,
            )

        ebooks_seen = False

        for _ in range(
            200
        ):
            if is_ebooks_url(
                page.url
            ):
                ebooks_seen = True
                break

            await page.wait_for_timeout(
                50
            )

        if not ebooks_seen:
            await open_home(
                page
            )

            continue

        print(
            "eBooks page detected:",
            page.url,
        )

        await page.wait_for_timeout(
            500
        )

        print()
        print("=" * 78)
        print("CLICKING RULES")
        print("=" * 78)

        clicked = (
            await click_rules_real(
                page
            )
        )

        if clicked:
            frame = (
                await wait_for_rules_form(
                    page,
                    timeout_seconds=20,
                )
            )

            if frame is not None:
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
                    frame.url,
                )

                print("=" * 78)

                return frame

        print(
            "Using direct Rules URL fallback..."
        )

        await page.goto(
            RULES_DIRECT_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        frame = (
            await wait_for_rules_form(
                page,
                timeout_seconds=20,
            )
        )

        if frame is not None:
            return frame

    raise RuntimeError(
        "Could not load Rules module."
    )


# ============================================================
# WAIT FOR ACT OPTIONS
# ============================================================

async def wait_for_act_options(
    page,
    frame,
):
    print()
    print(
        "Waiting for MCA to populate "
        "Act dropdown options..."
    )

    loop = (
        asyncio.get_running_loop()
    )

    start = loop.time()
    previous_count = None

    while (
        loop.time() - start
        < ACT_OPTIONS_TIMEOUT_SECONDS
    ):
        result = (
            await frame.evaluate(
                """
                () => {
                    const select =
                        document.querySelector(
                            '#DropDown_RuleAct'
                        );

                    if (!select) {
                        return {
                            count: 0,
                            found: false,
                            options: []
                        };
                    }

                    const options =
                        Array.from(
                            select.options
                        );

                    const dump =
                        options.map(
                            (o, index) => ({
                                index,

                                text:
                                    (
                                        o.textContent
                                        || ''
                                    )
                                    .replace(
                                        /\\s+/g,
                                        ' '
                                    )
                                    .trim(),

                                value:
                                    o.value || '',

                                dataId:
                                    o.getAttribute(
                                        'data-id'
                                    ) || '',

                                selected:
                                    o.selected
                            })
                        );

                    const target =
                        dump.find(
                            item =>
                                item.dataId === 'J105_D'
                                ||
                                item.text ===
                                    'The Companies Act, 2013'
                        );

                    return {
                        count:
                            dump.length,

                        found:
                            !!target,

                        target:
                            target || null,

                        options:
                            dump
                    };
                }
                """
            )
        )

        count = (
            result["count"]
        )

        if (
            count
            != previous_count
        ):
            print(
                "  Current option count:",
                count,
            )

            previous_count = count

        if result["found"]:
            print(
                "  Companies Act option "
                "is now available."
            )

            return result

        await page.wait_for_timeout(
            250
        )

    raise RuntimeError(
        "Act dropdown options "
        "did not load."
    )


# ============================================================
# SELECT COMPANIES ACT
# ============================================================

async def select_companies_act(
    page,
    frame,
):
    result = (
        await wait_for_act_options(
            page,
            frame,
        )
    )

    print()
    print(
        "Act options:"
    )

    for option in result[
        "options"
    ]:
        print(
            f"  [{option['index']}] "
            f"{option['text']!r} "
            f"value="
            f"{option['value']!r} "
            f"data-id="
            f"{option['dataId']!r} "
            f"selected="
            f"{option['selected']}"
        )

    target = (
        result["target"]
    )

    print()
    print(
        "Target option index:",
        target["index"],
    )

    print(
        "Target text:",
        target["text"],
    )

    print(
        "Target data-id:",
        target["dataId"],
    )

    dropdown = (
        frame.locator(
            "#DropDown_RuleAct"
        )
    )

    selected = (
        await dropdown.select_option(
            index=target["index"],
        )
    )

    print(
        "Playwright select_option result:",
        selected,
    )

    verification = (
        await frame.evaluate(
            """
            () => {
                const s =
                    document.querySelector(
                        '#DropDown_RuleAct'
                    );

                const o =
                    s.options[
                        s.selectedIndex
                    ];

                return {
                    index:
                        s.selectedIndex,

                    text:
                        (
                            o.textContent
                            || ''
                        )
                        .replace(
                            /\\s+/g,
                            ' '
                        )
                        .trim(),

                    dataId:
                        o.getAttribute(
                            'data-id'
                        ) || ''
                };
            }
            """
        )
    )

    print()
    print(
        "ACT SELECTED"
    )

    print(
        "Selected index:",
        verification["index"],
    )

    print(
        "Selected text:",
        verification["text"],
    )

    print(
        "Selected data-id:",
        verification["dataId"],
    )


# ============================================================
# CLICK GO
# ============================================================

async def click_go_button(
    page,
    frame,
):
    print()
    print("=" * 78)
    print("CLICKING GO")
    print("=" * 78)

    go = (
        frame.locator(
            "#clickGo"
        )
    )

    await go.wait_for(
        state="attached",
        timeout=30000,
    )

    print(
        "Go visible:",
        await go.is_visible(),
    )

    print(
        "Go disabled:",
        await go.is_disabled(),
    )

    print(
        "Go disabled1:",
        repr(
            await go.get_attribute(
                "disabled1"
            )
        ),
    )

    await page.wait_for_timeout(
        500
    )

    print(
        "Clicking Go with "
        "real Playwright click..."
    )

    try:
        await go.click(
            timeout=15000,
        )

        print(
            "Go clicked normally."
        )

    except Exception:
        await go.click(
            force=True,
        )

        print(
            "Go clicked forcefully."
        )


# ============================================================
# WAIT FOR RULE RESULTS
# ============================================================

async def wait_for_rules_results(
    page,
):
    print()
    print(
        "Waiting for Rules results..."
    )

    loop = (
        asyncio.get_running_loop()
    )

    start = loop.time()

    while (
        loop.time() - start
        < GO_RESULTS_TIMEOUT_SECONDS
    ):
        for (
            frame_index,
            frame,
        ) in enumerate(
            page.frames
        ):
            try:
                table = (
                    frame.locator(
                        "#rulesContainer"
                    )
                )

                if (
                    await table.count()
                    == 0
                ):
                    continue

                rows = (
                    frame.locator(
                        "#rulesContainer tbody tr"
                    )
                )

                row_count = (
                    await rows.count()
                )

                useful = 0

                for index in range(
                    row_count
                ):
                    try:
                        if (
                            await rows.nth(
                                index
                            ).locator(
                                ".ruleLink"
                            ).count()
                            > 0
                        ):
                            useful += 1

                    except Exception:
                        pass

                print(
                    "  Results detected "
                    "in frame "
                    f"#{frame_index}: "
                    f"{row_count} row(s), "
                    f"{useful} ruleLink row(s)"
                )

                if useful:
                    print()
                    print(
                        "Rules table loaded."
                    )

                    print(
                        "Initial displayed rows:",
                        row_count,
                    )

                    return frame

            except Exception:
                pass

        await page.wait_for_timeout(
            250
        )

    raise RuntimeError(
        "Rules results did not load."
    )


# ============================================================
# SELECT ACT + GO
# ============================================================

async def select_companies_act_and_click_go(
    page,
):
    print()
    print("=" * 78)

    print(
        "SELECTING THE COMPANIES ACT, 2013"
    )

    print("=" * 78)

    frame = (
        await wait_for_rules_form(
            page,
            timeout_seconds=30,
        )
    )

    if frame is None:
        raise RuntimeError(
            "Act dropdown not found."
        )

    await select_companies_act(
        page,
        frame,
    )

    await click_go_button(
        page,
        frame,
    )

    return (
        await wait_for_rules_results(
            page
        )
    )


# ============================================================
# SELECT ALL 54 ROWS
# ============================================================

async def select_all_rules(
    frame,
):
    print()
    print("=" * 78)
    print("SELECTING ALL RULE ROWS")
    print("=" * 78)

    rows = (
        frame.locator(
            "#rulesContainer tbody tr"
        )
    )

    print(
        "Current displayed rows:",
        await rows.count(),
    )

    selectors = [
        (
            'select['
            'name="rulesContainer_length"'
            ']'
        ),
        (
            'select['
            'aria-controls="rulesContainer"'
            ']'
        ),
        (
            '.dataTables_length select'
        ),
    ]

    dropdown = None

    for selector in selectors:
        candidate = (
            frame.locator(
                selector
            )
        )

        if (
            await candidate.count()
            > 0
        ):
            print(
                "  Length selector matched:"
            )

            print(
                "   ",
                selector,
            )

            dropdown = (
                candidate.first
            )

            break

    if dropdown is None:
        raise RuntimeError(
            "Rows-per-page dropdown "
            "not found."
        )

    print(
        "DataTables length "
        "dropdown found."
    )

    options = (
        dropdown.locator(
            "option"
        )
    )

    print(
        "Options:"
    )

    for index in range(
        await options.count()
    ):
        option = (
            options.nth(index)
        )

        print(
            " ",
            repr(
                await option.get_attribute(
                    "value"
                )
            ),
            "=>",
            repr(
                clean_text(
                    await option.inner_text()
                )
            ),
        )

    await dropdown.select_option(
        value="-1"
    )

    print(
        "Selected value=-1 / All."
    )

    await asyncio.sleep(
        1.5
    )

    print(
        "Final displayed rows:",
        await rows.count(),
    )


# ============================================================
# RULE POPUP LOCATOR
# ============================================================

def rule_popup_locator(
    frame,
):
    return frame.locator(
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
# TABLE ROW METADATA
# ============================================================

async def extract_table_row_metadata(
    row,
):
    """
    Extract these columns from the selected table row:

    Rules
    Rule Contains
    Notification Date

    The site may use td positions instead of explicit
    classes, so position fallback is supported.
    """

    cells = (
        row.locator(
            "td"
        )
    )

    cell_count = (
        await cells.count()
    )

    texts = []

    for index in range(
        cell_count
    ):
        try:
            text = clean_text(
                await cells.nth(
                    index
                ).inner_text()
            )

        except Exception:
            text = ""

        texts.append(
            text
        )

    # --------------------------------------------------------
    # Based on screenshot:
    #
    # td 0 = Rules
    # td 1 = Rule Contains
    # td 2 = Notification Date
    # td 3 = arrow
    # --------------------------------------------------------

    rules_name = (
        texts[0]
        if len(texts) > 0
        else ""
    )

    rule_contains = (
        texts[1]
        if len(texts) > 1
        else ""
    )

    notification_date = (
        texts[2]
        if len(texts) > 2
        else ""
    )

    # --------------------------------------------------------
    # If first cell contains the .ruleLink, prefer its
    # full title instead of potentially truncated visible text.
    # --------------------------------------------------------

    try:
        rule_link = (
            row.locator(
                ".ruleLink"
            ).first
        )

        link_text = clean_text(
            await rule_link.inner_text()
        )

        if link_text:
            rules_name = (
                link_text
            )

    except Exception:
        pass

    return {
        "rules":
            rules_name,

        "rule_contains":
            rule_contains,

        "notification_date":
            notification_date,

        "cells":
            texts,
    }


# ============================================================
# OPEN RULE TABLE ROW
# ============================================================

async def open_rule_table_row(
    frame,
    row_index,
):
    rows = (
        frame.locator(
            "#rulesContainer tbody tr"
        )
    )

    row_count = (
        await rows.count()
    )

    if (
        row_index
        >= row_count
    ):
        raise RuntimeError(
            "Table row disappeared."
        )

    row = (
        rows.nth(
            row_index
        )
    )

    metadata = (
        await extract_table_row_metadata(
            row
        )
    )

    rule_link = (
        row.locator(
            ".ruleLink"
        ).first
    )

    print()
    print("#" * 78)

    print(
        f"RULE TABLE ROW "
        f"{row_index + 1}/"
        f"{row_count}"
    )

    print("#" * 78)

    print(
        "Rules:",
        repr(
            metadata["rules"]
        ),
    )

    print(
        "Rule Contains:",
        repr(
            metadata["rule_contains"]
        ),
    )

    print(
        "Notification Date:",
        repr(
            metadata["notification_date"]
        ),
    )

    print(
        "Raw cells:",
        metadata["cells"],
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

    popup_links = (
        rule_popup_locator(
            frame
        )
    )

    await popup_links.first.wait_for(
        state="visible",
        timeout=30000,
    )

    popup_count = (
        await popup_links.count()
    )

    print(
        "rulePopup count:",
        popup_count,
    )

    return (
        metadata,
        popup_count,
    )


# ============================================================
# ACTIVE MODAL
# ============================================================

async def get_active_modal(
    frame,
):
    candidates = (
        frame.locator(
            ".modal-dialog.modal-sm"
        )
    )

    for index in range(
        await candidates.count()
    ):
        candidate = (
            candidates.nth(index)
        )

        try:
            if (
                await candidate.is_visible()
            ):
                return candidate

        except Exception:
            pass

    return None


async def wait_active_modal(
    frame,
):
    for _ in range(
        80
    ):
        modal = (
            await get_active_modal(
                frame
            )
        )

        if modal is not None:
            return modal

        await asyncio.sleep(
            0.1
        )

    return None


# ============================================================
# OPEN PDF DROPDOWN
# ============================================================

async def open_pdf_dropdown(
    page,
    frame,
    modal,
):
    dropdown = (
        modal.locator(
            "#mypdfDropdown"
        )
    )

    if (
        await dropdown.count()
        == 0
    ):
        dropdown = (
            frame.locator(
                "#mypdfDropdown"
            )
        )

    if (
        await dropdown.count()
        > 0
    ):
        radios = (
            dropdown.first.locator(
                'input[type="radio"]'
            )
        )

        if (
            await radios.count()
            > 0
        ):
            return (
                dropdown.first
            )

    selectors = [
        (
            ".rulespdfDownload "
            ".dropdown-toggle"
        ),
        ".rulespdfDownload button",
        ".rulespdfDownload a",
        ".rulespdfDownload",
    ]

    clicked = False

    for selector in selectors:
        candidate = (
            modal.locator(
                selector
            )
        )

        if (
            await candidate.count()
            == 0
        ):
            candidate = (
                frame.locator(
                    selector
                )
            )

        for index in range(
            await candidate.count()
        ):
            item = (
                candidate.nth(index)
            )

            try:
                if (
                    await item.is_visible()
                ):
                    await item.click(
                        force=True
                    )

                    clicked = True

                    break

            except Exception:
                pass

        if clicked:
            break

    await page.wait_for_timeout(
        200
    )

    dropdown = (
        modal.locator(
            "#mypdfDropdown"
        )
    )

    if (
        await dropdown.count()
        == 0
    ):
        dropdown = (
            frame.locator(
                "#mypdfDropdown"
            )
        )

    if (
        await dropdown.count()
        == 0
    ):
        raise RuntimeError(
            "#mypdfDropdown not found."
        )

    return (
        dropdown.first
    )


# ============================================================
# CURRENT RULE RADIO
# ============================================================

async def find_current_rule_radio(
    dropdown,
):
    """
    Only download:

        Current Rule

    Do NOT download:
        Current Rule with Notes
        Current Rule with Highlights
    """

    selectors = [
        (
            'input[type="radio"]'
            '[value="Current Rule"]'
        ),
        (
            'input[type="radio"]'
            '[aria-label="Current Rule"]'
        ),
        (
            'input[type="radio"]'
            '#rulesDownloadLinks'
        ),
        (
            'input.rulesDownloadLinks'
            '[type="radio"]'
        ),
    ]

    for selector in selectors:
        locator = (
            dropdown.locator(
                selector
            )
        )

        if (
            await locator.count()
            > 0
        ):
            return (
                locator.first
            )

    return None


# ============================================================
# DOWNLOAD EVENT
# ============================================================

async def wait_for_download_event(
    page,
    trigger,
    timeout_seconds,
):
    loop = (
        asyncio.get_running_loop()
    )

    future = (
        loop.create_future()
    )

    def on_download(
        download,
    ):
        if (
            not future.done()
        ):
            future.set_result(
                download
            )

    page.on(
        "download",
        on_download,
    )

    try:
        await trigger()

        try:
            return (
                await asyncio.wait_for(
                    future,
                    timeout=timeout_seconds,
                )
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
# CLICK HIDDEN CURRENT RULE RADIO
# ============================================================

async def trigger_current_rule(
    radio,
):
    """
    MCA radio is hidden.

    Real Playwright click may fail because the input itself
    isn't visible.

    DOM click correctly executes the site's handler.
    """

    return await radio.evaluate(
        """
        element => {
            if (element.disabled) {
                return {
                    ok: false,
                    reason: 'disabled'
                };
            }

            element.click();

            return {
                ok: true,
                method: 'dom-click',
                checked: !!element.checked,

                value:
                    element.getAttribute(
                        'value'
                    ) || '',

                ariaLabel:
                    element.getAttribute(
                        'aria-label'
                    ) || ''
            };
        }
        """
    )


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
        '[data-dismiss="modal"]',
        '[data-bs-dismiss="modal"]',
    ]

    for selector in selectors:
        candidate = (
            modal.locator(
                selector
            )
        )

        for index in range(
            await candidate.count()
        ):
            item = (
                candidate.nth(index)
            )

            try:
                if (
                    await item.is_visible()
                ):
                    await item.click(
                        force=True
                    )

                    await page.wait_for_timeout(
                        250
                    )

                    return

            except Exception:
                pass

    try:
        await page.keyboard.press(
            "Escape"
        )

        await page.wait_for_timeout(
            250
        )

    except Exception:
        pass


# ============================================================
# DOWNLOAD ONE INDIVIDUAL RULE
# ============================================================

async def download_individual_rule(
    page,
    frame,
    table_row_number,
    table_metadata,
    popup_index,
    manifest_rows,
):
    popup_links = (
        rule_popup_locator(
            frame
        )
    )

    popup_count = (
        await popup_links.count()
    )

    if (
        popup_index
        >= popup_count
    ):
        raise RuntimeError(
            "rulePopup disappeared."
        )

    popup_link = (
        popup_links.nth(
            popup_index
        )
    )

    rule_title = clean_text(
        await popup_link.inner_text()
    )

    rules_name = clean_text(
        table_metadata[
            "rules"
        ]
    )

    rule_contains = clean_text(
        table_metadata[
            "rule_contains"
        ]
    )

    notification_date = clean_text(
        table_metadata[
            "notification_date"
        ]
    )

    # ========================================================
    # BUILD DESTINATION BEFORE DOWNLOADING
    # ========================================================

    filename = (
        build_filename(
            rules_name,
            rule_contains,
            notification_date,
            rule_title,
        )
    )

    destination = (
        DOWNLOAD_DIR
        / filename
    )

    print()
    print("-" * 78)

    print(
        f"RULE POPUP "
        f"{popup_index + 1}/"
        f"{popup_count}"
    )

    print("-" * 78)

    print(
        "Individual Rule:",
        repr(
            rule_title
        ),
    )

    print(
        "Target filename:"
    )

    print(
        " ",
        filename,
    )

    # ========================================================
    # DUPLICATE CHECK BEFORE OPENING MODAL/DOWNLOAD
    # ========================================================

    if (
        destination.exists()
    ):
        print(
            "  ALREADY EXISTS - SKIPPING DOWNLOAD"
        )

        manifest_rows.append(
            {
                "table_row":
                    table_row_number,

                "rules":
                    rules_name,

                "rule_contains":
                    rule_contains,

                "notification_date":
                    notification_date,

                "rule_title":
                    rule_title,

                "original_pdf":
                    "",

                "saved_filename":
                    filename,

                "status":
                    "already-exists",
            }
        )

        save_manifest(
            manifest_rows
        )

        return

    # ========================================================
    # OPEN INDIVIDUAL RULE MODAL
    # ========================================================

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

    modal = (
        await wait_active_modal(
            frame
        )
    )

    if (
        modal is None
    ):
        raise RuntimeError(
            "Rule modal did not open."
        )

    print(
        "  Modal opened."
    )

    dropdown = (
        await open_pdf_dropdown(
            page,
            frame,
            modal,
        )
    )

    radios = (
        dropdown.locator(
            'input[type="radio"]'
        )
    )

    print(
        "  Total PDF options:",
        await radios.count(),
    )

    # Print options for diagnostics.
    for index in range(
        await radios.count()
    ):
        radio = (
            radios.nth(index)
        )

        try:
            value = (
                await radio.get_attribute(
                    "value"
                )
            )

        except Exception:
            value = None

        try:
            aria_label = (
                await radio.get_attribute(
                    "aria-label"
                )
            )

        except Exception:
            aria_label = None

        print(
            f"    [{index + 1}] "
            f"value={value!r} "
            f"aria-label={aria_label!r}"
        )

    current_rule_radio = (
        await find_current_rule_radio(
            dropdown
        )
    )

    if (
        current_rule_radio
        is None
    ):
        raise RuntimeError(
            "Current Rule radio "
            "was not found."
        )

    # ========================================================
    # DOWNLOAD CURRENT RULE
    # ========================================================

    async def trigger():
        result = (
            await trigger_current_rule(
                current_rule_radio
            )
        )

        print(
            "  Current Rule trigger:",
            result,
        )

    print(
        "  Downloading Current Rule..."
    )

    download = (
        await wait_for_download_event(
            page,
            trigger,
            DOWNLOAD_WAIT_SECONDS,
        )
    )

    if (
        download is None
    ):
        print(
            "  ERROR: Current Rule "
            "did not trigger a download."
        )

        manifest_rows.append(
            {
                "table_row":
                    table_row_number,

                "rules":
                    rules_name,

                "rule_contains":
                    rule_contains,

                "notification_date":
                    notification_date,

                "rule_title":
                    rule_title,

                "original_pdf":
                    "",

                "saved_filename":
                    filename,

                "status":
                    (
                        "ERROR: "
                        "Current Rule download timeout"
                    ),
            }
        )

        save_manifest(
            manifest_rows
        )

        await close_modal(
            page,
            modal,
        )

        return

    original_pdf = clean_text(
        download.suggested_filename
        or ""
    )

    print(
        "  MCA original filename:",
        repr(
            original_pdf
        ),
    )

    # ========================================================
    # SAVE USING OUR LOGICAL FILENAME
    # ========================================================

    await download.save_as(
        str(
            destination
        )
    )

    print(
        "  SAVED:"
    )

    print(
        " ",
        destination.name,
    )

    manifest_rows.append(
        {
            "table_row":
                table_row_number,

            "rules":
                rules_name,

            "rule_contains":
                rule_contains,

            "notification_date":
                notification_date,

            "rule_title":
                rule_title,

            "original_pdf":
                original_pdf,

            "saved_filename":
                destination.name,

            "status":
                "downloaded",
        }
    )

    save_manifest(
        manifest_rows
    )

    await close_modal(
        page,
        modal,
    )

    await page.wait_for_timeout(
        250
    )


# ============================================================
# PROCESS ALL RULES
# ============================================================

async def process_all_rules(
    page,
    frame,
):
    manifest_rows = (
        load_manifest()
    )

    if (
        manifest_rows
    ):
        print(
            "Loaded existing manifest entries:",
            len(
                manifest_rows
            ),
        )

    rows = (
        frame.locator(
            "#rulesContainer tbody tr"
        )
    )

    total_rows = (
        await rows.count()
    )

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

    for row_index in range(
        total_rows
    ):
        try:
            (
                metadata,
                popup_count,
            ) = (
                await open_rule_table_row(
                    frame,
                    row_index,
                )
            )

            total_popups += (
                popup_count
            )

            for popup_index in range(
                popup_count
            ):
                try:
                    await download_individual_rule(
                        page=page,
                        frame=frame,
                        table_row_number=(
                            row_index + 1
                        ),
                        table_metadata=(
                            metadata
                        ),
                        popup_index=(
                            popup_index
                        ),
                        manifest_rows=(
                            manifest_rows
                        ),
                    )

                except Exception as exc:
                    print()
                    print(
                        "  ERROR processing "
                        "individual rule:",
                        repr(exc),
                    )

                    await save_debug(
                        page,
                        (
                            f"row_"
                            f"{row_index + 1}_"
                            f"rule_"
                            f"{popup_index + 1}"
                        ),
                    )

                    try:
                        modal = (
                            await get_active_modal(
                                frame
                            )
                        )

                        if (
                            modal
                            is not None
                        ):
                            await close_modal(
                                page,
                                modal,
                            )

                    except Exception:
                        pass

            await page.wait_for_timeout(
                300
            )

        except Exception as exc:
            print()
            print(
                "ERROR processing "
                f"table row "
                f"{row_index + 1}:",
                repr(exc),
            )

            await save_debug(
                page,
                (
                    f"table_row_"
                    f"{row_index + 1}_error"
                ),
            )

    save_manifest(
        manifest_rows
    )

    downloaded = sum(
        1
        for row in manifest_rows
        if (
            row.get(
                "status"
            )
            == "downloaded"
        )
    )

    already_exists = sum(
        1
        for row in manifest_rows
        if (
            row.get(
                "status"
            )
            == "already-exists"
        )
    )

    errors = sum(
        1
        for row in manifest_rows
        if (
            row.get(
                "status",
                ""
            ).startswith(
                "ERROR"
            )
        )
    )

    print()
    print("=" * 78)
    print("FINAL SUMMARY")
    print("=" * 78)

    print(
        "Table rows:",
        total_rows,
    )

    print(
        "Individual rules:",
        total_popups,
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
# KEEP PROCESS ALIVE
# ============================================================

async def keep_browser_open():
    print()
    print("=" * 78)
    print("PROCESS WILL REMAIN RUNNING")
    print("=" * 78)

    print(
        "Press Ctrl+C to exit."
    )

    await asyncio.Event().wait()


# ============================================================
# MAIN
# ============================================================

async def main():
    async with async_playwright() as p:

        # ====================================================
        # FIREFOX ONLY
        #
        # Chromium receives HTTP 403 from MCA
        # on this server.
        # ====================================================

        browser = (
            await p.firefox.launch(
                headless=True,
            )
        )

        context = (
            await browser.new_context(
                accept_downloads=True,
                viewport={
                    "width": 1920,
                    "height": 1080,
                },
                locale="en-US",
            )
        )

        page = (
            await context.new_page()
        )

        page.set_default_timeout(
            DEFAULT_TIMEOUT
        )

        # ----------------------------------------------------
        # DOCUMENT RESPONSE LOGGING
        # ----------------------------------------------------

        async def log_response(
            response,
        ):
            try:
                if (
                    "mca.gov.in"
                    in response.url
                    and
                    response.request.resource_type
                    == "document"
                ):
                    print(
                        "[DOCUMENT]",
                        response.status,
                        response.url,
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

            await open_home(
                page
            )

            # =================================================
            # 2. RULES MODULE
            # =================================================

            await open_rules_module(
                page
            )

            # =================================================
            # 3. COMPANIES ACT + GO
            # =================================================

            rules_context = (
                await select_companies_act_and_click_go(
                    page
                )
            )

            # =================================================
            # 4. SELECT ALL 54 ROWS
            # =================================================

            await select_all_rules(
                rules_context
            )

            # =================================================
            # 5. DOWNLOAD CURRENT RULE FOR EACH INDIVIDUAL RULE
            # =================================================

            await process_all_rules(
                page,
                rules_context,
            )

            # =================================================
            # 6. STAY ALIVE
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
# ENTRY
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(
            main()
        )

    except KeyboardInterrupt:
        print()
        print(
            "Script stopped."
        )
