import asyncio
import csv
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://egazette.gov.in/"
DOWNLOAD_DIR = Path("egazette_mca_pdfs")
MANIFEST_FILE = DOWNLOAD_DIR / "downloads.csv"

FROM_DATE = "01-Jan-2013"
TO_DATE = datetime.now().strftime("%d-%b-%Y")


async def debug_page(page, name):
    """
    Save screenshot + HTML + list of links/inputs/buttons.
    This is extremely useful for old government websites.
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)

    screenshot = DOWNLOAD_DIR / f"{safe}.png"
    html_file = DOWNLOAD_DIR / f"{safe}.html"
    links_file = DOWNLOAD_DIR / f"{safe}_links.txt"

    try:
        await page.screenshot(path=str(screenshot), full_page=True)
    except Exception as e:
        print("Could not save screenshot:", e)

    try:
        html = await page.content()
        html_file.write_text(html, encoding="utf-8")
    except Exception as e:
        print("Could not save HTML:", e)

    try:
        rows = []

        links = page.locator("a")
        count = await links.count()

        for i in range(count):
            link = links.nth(i)

            try:
                text = (await link.inner_text()).strip()
            except Exception:
                text = ""

            href = await link.get_attribute("href")
            onclick = await link.get_attribute("onclick")
            target = await link.get_attribute("target")

            rows.append(f"""
LINK #{i}
TEXT    : {text!r}
HREF    : {href!r}
ONCLICK : {onclick!r}
TARGET  : {target!r}
-------------------------------
""")

        links_file.write_text("\n".join(rows), encoding="utf-8")

    except Exception as e:
        print("Could not dump links:", e)

    print(f"Debug files saved for '{name}'")


async def wait_for_page_stable(page, timeout=15000):
    """
    Old sites often never reach networkidle cleanly.
    Try several increasingly relaxed waits.
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass

    try:
        await page.wait_for_load_state("load", timeout=5000)
    except Exception:
        pass

    await page.wait_for_timeout(1000)


async def click_exact_visible_text(page, text):
    """
    Click exact text across links/buttons/elements.
    """
    pattern = re.compile(rf"^\s*{re.escape(text)}\s*$", re.I)

    candidates = [
        page.get_by_role("link", name=pattern),
        page.get_by_role("button", name=pattern),
        page.get_by_text(pattern),
        page.locator("a", has_text=pattern),
        page.locator("button", has_text=pattern),
        page.locator('input[type="button"]'),
        page.locator('input[type="submit"]'),
    ]

    for locator in candidates:
        try:
            count = await locator.count()

            for i in range(count):
                el = locator.nth(i)

                if not await el.is_visible():
                    continue

                tag = await el.evaluate("(e) => e.tagName.toLowerCase()")

                if tag == "input":
                    value = (await el.get_attribute("value") or "").strip()

                    if not pattern.match(value):
                        continue

                try:
                    await el.scroll_into_view_if_needed()
                except Exception:
                    pass

                try:
                    await el.click(timeout=5000)
                    return True
                except Exception:
                    try:
                        await el.click(timeout=5000, force=True)
                        return True
                    except Exception:
                        continue

        except Exception:
            continue

    return False


async def click_search(page):
    print("Opening Search...")

    await wait_for_page_stable(page)

    for attempt in range(1, 4):
        print(f"  Search attempt {attempt}/3")

        found = await click_exact_visible_text(page, "Search")

        if found:
            await wait_for_page_stable(page)

            # Give old JS/postback time to replace page
            await page.wait_for_timeout(1000)

            return

        await page.wait_for_timeout(1500)

    await debug_page(page, "search_not_found")

    raise RuntimeError("Could not find Search control.")


async def page_contains_ministry_search(page):
    """
    Check whether Search by Ministry is present.
    """
    try:
        text = await page.locator("body").inner_text()
        return bool(re.search(r"Search\s+by\s+Ministry", text, re.I))
    except Exception:
        return False


async def click_search_by_ministry(page):
    print("Opening Search by Ministry...")

    #
    # Important:
    # wait for the actual menu to become present.
    #
    for attempt in range(1, 6):
        print(f"  Waiting for ministry search " f"({attempt}/5)...")

        await wait_for_page_stable(page)

        if await page_contains_ministry_search(page):
            print("  Search by Ministry text detected.")

            success = await click_exact_visible_text(page, "Search by Ministry")

            if success:
                await wait_for_page_stable(page)
                await page.wait_for_timeout(750)
                return

        #
        # Maybe Search click did not actually transition.
        #
        body = ""
        try:
            body = await page.locator("body").inner_text()
        except Exception:
            pass

        print("  Current URL:", page.url)

        print("  Body preview:", repr(body[:300]))

        await page.wait_for_timeout(1500)

    await debug_page(page, "search_by_ministry_not_found")

    raise RuntimeError("Could not find Search by Ministry.")


async def select_mca_ministry(page):
    print("Selecting Ministry of Corporate Affairs...")

    selects = page.locator("select")
    count = await selects.count()

    print(f"  Found {count} <select> elements.")

    for i in range(count):
        select = selects.nth(i)

        try:
            if not await select.is_visible():
                continue

            options = await select.locator("option").all_text_contents()

            clean = [option.strip() for option in options]

            if any("Ministry of Corporate Affairs" in option for option in clean):
                for option in clean:
                    if "Ministry of Corporate Affairs" in option:
                        await select.select_option(label=option)

                        print("Ministry selected:", option)
                        return

        except Exception:
            continue

    await debug_page(page, "ministry_dropdown_not_found")

    raise RuntimeError("Could not locate Ministry of Corporate Affairs.")


async def select_date_wise(page):
    print("Selecting Date Wise mode...")

    radios = page.locator('input[type="radio"]')

    count = await radios.count()

    print(f"  Found {count} radio controls.")

    #
    # First try matching labels.
    #
    labels = page.locator("label")

    for i in range(await labels.count()):
        label = labels.nth(i)

        try:
            text = (await label.inner_text()).strip()

            if re.fullmatch(r"Date\s*Wise", text, re.I):
                await label.click()
                await page.wait_for_timeout(300)

                if await page.locator('input[type="radio"]:checked').count():
                    print("Date Wise selected.")
                    return
        except Exception:
            pass

    #
    # Screenshot shows Month/Year first,
    # Date Wise second.
    #
    if count >= 2:
        await radios.nth(1).check(force=True)

        print("Date Wise selected using radio #2.")
        return

    await debug_page(page, "date_wise_not_found")

    raise RuntimeError("Could not select Date Wise.")


async def determine_date_inputs(page):
    inputs = page.locator('input[type="text"], ' "input:not([type])")

    visible = []

    for i in range(await inputs.count()):
        el = inputs.nth(i)

        try:
            if await el.is_visible():
                visible.append(el)
        except Exception:
            pass

    #
    # Prefer inputs whose existing values resemble dates.
    #
    date_inputs = []

    pattern = re.compile(r"\d{1,2}-[A-Za-z]{3}-\d{4}")

    for el in visible:
        try:
            value = await el.input_value()

            if pattern.fullmatch(value.strip()):
                date_inputs.append(el)

        except Exception:
            pass

    if len(date_inputs) >= 2:
        return (date_inputs[0], date_inputs[1])

    #
    # Fallback: last two visible text fields.
    #
    if len(visible) >= 2:
        return (visible[-2], visible[-1])

    raise RuntimeError("Could not determine date inputs.")


async def enter_dates(page):
    print(f"Setting date range: " f"{FROM_DATE} -> {TO_DATE}")

    from_input, to_input = await determine_date_inputs(page)

    await from_input.fill(FROM_DATE)
    await from_input.press("Tab")

    await to_input.fill(TO_DATE)
    await to_input.press("Tab")

    print("Dates entered:", await from_input.input_value(), "to", await to_input.input_value())


async def submit_search(page):
    print("Submitting search...")

    await debug_page(page, "before_submit")

    buttons = page.locator('input[type="submit"], ' 'input[type="button"], ' "button")

    count = await buttons.count()

    for i in range(count):
        button = buttons.nth(i)

        try:
            value = await button.get_attribute("value") or ""

            text = ""

            try:
                text = await button.inner_text()
            except Exception:
                pass

            combined = (value + " " + text).strip()

            if not re.search(r"\bSubmit\b", combined, re.I):
                continue

            if not await button.is_visible():
                continue

            print("  Clicking submit control:", repr(combined))

            before_url = page.url

            try:
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                    await button.click()

            except PlaywrightTimeoutError:
                print("  No full navigation event; " "likely postback/AJAX.")

            await wait_for_page_stable(page)

            #
            # Critical:
            # old server pages often modify DOM AFTER
            # DOMContentLoaded.
            #
            await page.wait_for_timeout(3000)

            print("  URL before:", before_url)

            print("  URL after :", page.url)

            await debug_page(page, "after_submit")

            return

        except Exception as exc:
            print("  Submit candidate error:", exc)

    await debug_page(page, "submit_not_found")

    raise RuntimeError("Could not find Submit button.")


async def inspect_results(page):
    """
    Print everything useful from result page.

    We deliberately inspect:
    - anchor href
    - onclick handlers
    - image links
    - javascript links
    - forms
    - buttons
    - pagination-looking controls
    """

    print("\n========== RESULT PAGE INSPECTION ==========")

    print("URL:", page.url)

    body_text = ""

    try:
        body_text = await page.locator("body").inner_text()
    except Exception:
        pass

    print("\nBODY TEXT PREVIEW:\n")
    print(body_text[:5000])

    print("\n========== LINKS ==========")

    links = page.locator("a")
    link_count = await links.count()

    print(f"Total <a> tags: {link_count}")

    for i in range(link_count):
        a = links.nth(i)

        try:
            text = (await a.inner_text()).strip()
        except Exception:
            text = ""

        href = await a.get_attribute("href")

        onclick = await a.get_attribute("onclick")

        title = await a.get_attribute("title")

        if text or href or onclick:
            print(
                f"\n[{i}]"
                f"\n text    = {text!r}"
                f"\n href    = {href!r}"
                f"\n onclick = {onclick!r}"
                f"\n title   = {title!r}"
            )

    print("\n========== INPUTS ==========")

    inputs = page.locator("input")
    input_count = await inputs.count()

    for i in range(input_count):
        el = inputs.nth(i)

        print(
            f"[{i}]",
            "type=",
            await el.get_attribute("type"),
            "name=",
            await el.get_attribute("name"),
            "value=",
            await el.get_attribute("value"),
            "onclick=",
            await el.get_attribute("onclick"),
        )

    print("\n========== FORMS ==========")

    forms = page.locator("form")

    for i in range(await forms.count()):
        form = forms.nth(i)

        print(
            f"[{i}]",
            "action=",
            await form.get_attribute("action"),
            "method=",
            await form.get_attribute("method"),
        )

    print("\n============================================\n")


async def main():
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])

        context = await browser.new_context(accept_downloads=True, viewport=None)

        page = await context.new_page()

        #
        # Government websites can be slow.
        #
        page.set_default_timeout(20000)

        try:
            print("Opening eGazette...")

            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)

            await wait_for_page_stable(page)

            await click_search(page)

            await click_search_by_ministry(page)

            await select_mca_ministry(page)

            await select_date_wise(page)

            await enter_dates(page)

            print(
                "\nSearch configuration:"
                f"\n  Ministry : Ministry of Corporate Affairs"
                f"\n  Mode     : Date Wise"
                f"\n  From     : {FROM_DATE}"
                f"\n  To       : {TO_DATE}"
                "\n"
            )

            await submit_search(page)

            #
            # For now don't attempt download.
            # First determine exact result structure.
            #
            await inspect_results(page)

            print("\nInspection complete.")

            print("Please inspect:")

            print(f"  {DOWNLOAD_DIR / 'after_submit.png'}")

            print(f"  {DOWNLOAD_DIR / 'after_submit.html'}")

            print(f"  {DOWNLOAD_DIR / 'after_submit_links.txt'}")

            #
            # Keep browser alive briefly so you can inspect manually.
            #
            print("\nBrowser will remain open for 30 seconds...")

            await page.wait_for_timeout(30000)

        except Exception as exc:
            print("\nFATAL ERROR:", repr(exc))

            await debug_page(page, "fatal_error")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
