#!/usr/bin/env python3

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


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "document.pdf"


def filename_from_url(url: str, fallback: str) -> str:
    path = urlparse(url).path
    name = Path(path).name

    if not name or "." not in name:
        name = fallback

    if not name.lower().endswith(".pdf"):
        name += ".pdf"

    return sanitize_filename(name)


async def click_text(page, text):
    """
    Try multiple ways of clicking visible text.
    """

    candidates = [
        page.get_by_role("link", name=re.compile(re.escape(text), re.I)),
        page.get_by_role("button", name=re.compile(re.escape(text), re.I)),
        page.get_by_text(text, exact=True),
        page.get_by_text(re.compile(rf"^\s*{re.escape(text)}\s*$", re.I)),
    ]

    for locator in candidates:
        try:
            if await locator.count():
                await locator.first.click()
                return True
        except Exception:
            pass

    return False


async def click_search(page):
    print("Opening Search...")

    if await click_text(page, "Search"):
        await page.wait_for_load_state("domcontentloaded")
        return

    # fallback for image/input based navigation
    possible = page.locator(
        'a:has-text("Search"), ' 'input[value*="Search" i], ' 'button:has-text("Search")'
    )

    if await possible.count():
        await possible.first.click()
        await page.wait_for_load_state("domcontentloaded")
        return

    raise RuntimeError("Could not find the Search control.")


async def click_search_by_ministry(page):
    print("Opening Search by Ministry...")

    if await click_text(page, "Search by Ministry"):
        await page.wait_for_load_state("domcontentloaded")
        return

    locator = page.locator(
        'a:has-text("Search by Ministry"), '
        'input[value*="Ministry" i], '
        'button:has-text("Search by Ministry")'
    )

    if await locator.count():
        await locator.first.click()
        await page.wait_for_load_state("domcontentloaded")
        return

    raise RuntimeError("Could not find Search by Ministry.")


async def select_mca_ministry(page):
    print("Selecting Ministry of Corporate Affairs...")

    selects = page.locator("select")
    count = await selects.count()

    for i in range(count):
        select = selects.nth(i)

        try:
            options = await select.locator("option").all_text_contents()
        except Exception:
            continue

        options_clean = [x.strip() for x in options]

        if any("Ministry of Corporate Affairs" in option for option in options_clean):
            try:
                await select.select_option(label="Ministry of Corporate Affairs")
            except Exception:
                for index, option in enumerate(options_clean):
                    if "Ministry of Corporate Affairs" in option:
                        await select.select_option(index=index)
                        break

            print("Ministry selected.")
            return

    raise RuntimeError(
        "Could not find Ministry dropdown containing " "'Ministry of Corporate Affairs'."
    )


async def select_date_wise(page):
    print("Selecting Date Wise mode...")

    # First try associated label
    label = page.get_by_text(re.compile(r"^\s*Date\s*Wise\s*$", re.I), exact=False)

    try:
        count = await label.count()

        for i in range(count):
            element = label.nth(i)

            try:
                await element.click()
                await page.wait_for_timeout(300)

                # verify some radio is now selected
                checked = page.locator('input[type="radio"]:checked')
                if await checked.count():
                    print("Date Wise selected.")
                    return
            except Exception:
                pass
    except Exception:
        pass

    # Inspect radio buttons and surrounding text
    radios = page.locator('input[type="radio"]')
    radio_count = await radios.count()

    for i in range(radio_count):
        radio = radios.nth(i)

        try:
            value = (await radio.get_attribute("value") or "").lower()
            rid = await radio.get_attribute("id")

            surrounding = ""

            if rid:
                assoc_label = page.locator(f'label[for="{rid}"]')
                if await assoc_label.count():
                    surrounding = (await assoc_label.first.inner_text()).lower()

            if "date" in value or "date" in surrounding:
                await radio.check(force=True)
                print("Date Wise selected.")
                return

        except Exception:
            pass

    # Screenshot suggests second radio is Date Wise
    if radio_count >= 2:
        await radios.nth(1).check(force=True)
        print("Date Wise selected using second-radio fallback.")
        return

    raise RuntimeError("Could not select Date Wise.")


async def determine_date_inputs(page):
    """
    Locate the two visible date inputs appearing in the
    'Date of Issue of Notification' row.
    """

    inputs = page.locator("input:not([type]), " 'input[type="text"], ' 'input[type="date"]')

    count = await inputs.count()

    candidates = []

    for i in range(count):
        el = inputs.nth(i)

        try:
            if not await el.is_visible():
                continue

            value = await el.input_value()

            placeholder = await el.get_attribute("placeholder") or ""

            name = await el.get_attribute("name") or ""

            eid = await el.get_attribute("id") or ""

            combined = " ".join([value, placeholder, name, eid]).lower()

            # Typical Gazette date fields either have a date already
            # or have date-related IDs/names.
            date_pattern = re.compile(
                r"\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}" r"|\d{1,2}[-/]\d{1,2}[-/]\d{4}"
            )

            if (
                date_pattern.search(value)
                or "date" in combined
                or "from" in combined
                or "to" in combined
            ):
                candidates.append(el)

        except Exception:
            pass

    # If exactly what we need was found
    if len(candidates) >= 2:
        return candidates[0], candidates[1]

    # Fallback:
    # collect text inputs whose current values resemble the
    # dates visible in the screenshot.
    visible_text_inputs = []

    for i in range(count):
        el = inputs.nth(i)
        try:
            if await el.is_visible():
                visible_text_inputs.append(el)
        except Exception:
            pass

    for i in range(len(visible_text_inputs) - 1):
        first = visible_text_inputs[i]
        second = visible_text_inputs[i + 1]

        try:
            v1 = await first.input_value()
            v2 = await second.input_value()

            if ("2013" in v1 or "Jan" in v1) and re.search(r"\d{4}", v2):
                return first, second
        except Exception:
            pass

    # Last-resort assumption: final two visible text inputs are dates.
    if len(visible_text_inputs) >= 2:
        return (visible_text_inputs[-2], visible_text_inputs[-1])

    raise RuntimeError("Could not identify From and To date fields.")


async def enter_dates(page):
    print(f"Setting date range: {FROM_DATE} -> {TO_DATE}")

    from_input, to_input = await determine_date_inputs(page)

    await from_input.click()
    await from_input.fill(FROM_DATE)

    await to_input.click()
    await to_input.fill(TO_DATE)

    # Trigger legacy JS onchange/blur handlers
    await from_input.press("Tab")
    await to_input.press("Tab")

    print("Dates entered:", await from_input.input_value(), "to", await to_input.input_value())


async def submit_search(page):
    print("Submitting search...")

    buttons = [
        page.get_by_role("button", name=re.compile(r"^\s*Submit\s*$", re.I)),
        page.locator('input[type="submit"][value*="Submit" i]'),
        page.locator('input[type="button"][value*="Submit" i]'),
        page.get_by_text("Submit", exact=True),
    ]

    for locator in buttons:
        try:
            if await locator.count():
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                    await locator.first.click()

                print("Results page loaded.")
                return

        except PlaywrightTimeoutError:
            # Ajax/postback may have happened without ordinary navigation
            print("No normal navigation detected; " "checking current results page.")
            await page.wait_for_timeout(3000)
            return

        except Exception:
            pass

    raise RuntimeError("Could not find Submit button.")


async def get_pdf_links(page):
    """
    Return PDF-like links on the current results page.
    """

    results = []

    links = page.locator("a[href]")
    count = await links.count()

    for i in range(count):
        link = links.nth(i)

        try:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()

            if not href:
                continue

            absolute_url = urljoin(page.url, href)

            haystack = f"{href} {text}".lower()

            if (
                ".pdf" in haystack
                or "download" in haystack
                or "view pdf" in haystack
                or text.lower() == "pdf"
            ):
                results.append({"url": absolute_url, "text": text})

        except Exception:
            pass

    # remove duplicates while preserving order
    unique = []
    seen = set()

    for item in results:
        if item["url"] in seen:
            continue

        seen.add(item["url"])
        unique.append(item)

    return unique


async def save_pdf_using_context(context, pdf_url, destination):
    """
    Uses Playwright's request context so cookies/session are reused.
    This is important if Gazette PDF URLs require the active session.
    """

    response = await context.request.get(pdf_url, timeout=60000)

    if not response.ok:
        raise RuntimeError(f"HTTP {response.status} for {pdf_url}")

    body = await response.body()

    destination.write_bytes(body)

    return len(body)


async def download_current_page_pdfs(
    page, context, downloaded_urls, manifest_rows, result_page_number
):
    links = await get_pdf_links(page)

    print(f"Page {result_page_number}: " f"found {len(links)} candidate PDF links")

    new_downloads = 0

    for index, item in enumerate(links, start=1):
        url = item["url"]

        if url in downloaded_urls:
            continue

        fallback = f"page_{result_page_number:04d}_" f"document_{index:03d}.pdf"

        filename = filename_from_url(url, fallback)

        # Prevent duplicate filename overwrites
        path = DOWNLOAD_DIR / filename

        if path.exists():
            stem = path.stem
            suffix = path.suffix

            n = 2
            while True:
                alternative = DOWNLOAD_DIR / f"{stem}_{n}{suffix}"

                if not alternative.exists():
                    path = alternative
                    break

                n += 1

        try:
            size = await save_pdf_using_context(context, url, path)

            downloaded_urls.add(url)
            new_downloads += 1

            manifest_rows.append(
                {
                    "result_page": result_page_number,
                    "filename": path.name,
                    "link_text": item["text"],
                    "url": url,
                    "bytes": size,
                    "status": "downloaded",
                }
            )

            print(f"  [{new_downloads}] " f"{path.name} " f"({size / 1024:.1f} KB)")

        except Exception as exc:
            print(f"  ERROR downloading {url}: {exc}")

            manifest_rows.append(
                {
                    "result_page": result_page_number,
                    "filename": "",
                    "link_text": item["text"],
                    "url": url,
                    "bytes": "",
                    "status": f"ERROR: {exc}",
                }
            )

    return new_downloads


async def get_numeric_pagination_links(page):
    """
    Detect visible anchors whose text is purely numeric.

    Example:
        1 2 3 4 5 6 7 8 9 10
    """

    links = page.locator("a")
    count = await links.count()

    pages = {}

    for i in range(count):
        link = links.nth(i)

        try:
            if not await link.is_visible():
                continue

            text = (await link.inner_text()).strip()

            if not re.fullmatch(r"\d+", text):
                continue

            number = int(text)

            # Avoid absurdly large unrelated numeric links
            if number < 1 or number > 100000:
                continue

            pages[number] = link

        except Exception:
            pass

    return pages


async def click_page_number(page, number):
    """
    Re-fetch locator immediately before clicking because legacy
    postbacks usually invalidate all old DOM nodes.
    """

    matching = page.locator("a", has_text=re.compile(rf"^\s*{number}\s*$"))

    count = await matching.count()

    for i in range(count):
        candidate = matching.nth(i)

        try:
            text = (await candidate.inner_text()).strip()

            if text != str(number):
                continue

            if not await candidate.is_visible():
                continue

            print(f"Opening results page {number}...")

            try:
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
                    await candidate.click()

            except PlaywrightTimeoutError:
                # likely ASP.NET postback/AJAX
                await page.wait_for_timeout(2000)

            return True

        except Exception:
            pass

    return False


async def process_pagination(page, context, downloaded_urls, manifest_rows):
    """
    Traverse numeric pagination.

    This intentionally re-scans the pagination after every click
    because old Government/ASP.NET pages often replace the whole DOM.
    """

    visited_pages = set()
    current_page = 1

    while True:

        if current_page not in visited_pages:
            visited_pages.add(current_page)

            await download_current_page_pdfs(
                page, context, downloaded_urls, manifest_rows, current_page
            )

        numeric_pages = await get_numeric_pagination_links(page)

        available_numbers = sorted(numeric_pages.keys())

        print("Visible pagination:", available_numbers)

        unvisited = [n for n in available_numbers if n not in visited_pages]

        if unvisited:
            next_page = unvisited[0]

            clicked = await click_page_number(page, next_page)

            if clicked:
                current_page = next_page
                continue

        #
        # Some sites show only a block such as:
        #
        # 1 2 3 4 5 6 7 8 9 10 Next
        #
        # and later:
        #
        # 11 12 13 ...
        #
        # Try "Next" / ">" when all currently visible page numbers
        # are already processed.
        #
        next_candidates = [
            page.get_by_role("link", name=re.compile(r"^\s*Next\s*$", re.I)),
            page.locator('a:has-text("Next")'),
            page.locator('a:text-is(">")'),
            page.locator('a:text-is(">>")'),
        ]

        advanced = False

        for locator in next_candidates:
            try:
                if not await locator.count():
                    continue

                candidate = locator.first

                if not await candidate.is_visible():
                    continue

                try:
                    async with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
                        await candidate.click()

                except PlaywrightTimeoutError:
                    await page.wait_for_timeout(2000)

                # Determine the new active/visible numeric page.
                new_numbers = sorted((await get_numeric_pagination_links(page)).keys())

                possible = [n for n in new_numbers if n not in visited_pages]

                if possible:
                    current_page = possible[0]
                else:
                    current_page = max(visited_pages, default=current_page) + 1

                advanced = True
                break

            except Exception:
                pass

        if advanced:
            continue

        print("No unvisited pagination links remain.")
        break


def write_manifest(rows):
    with MANIFEST_FILE.open("w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(
            f, fieldnames=["result_page", "filename", "link_text", "url", "bytes", "status"]
        )

        writer.writeheader()
        writer.writerows(rows)


async def main():
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    downloaded_urls = set()
    manifest_rows = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])

        context = await browser.new_context(accept_downloads=True, viewport=None)

        page = await context.new_page()

        page.set_default_timeout(15000)

        try:
            print("Opening eGazette...")
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)

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
                f"\n  To       : {TO_DATE}\n"
            )

            await submit_search(page)

            # Give old server-rendered page a little extra time
            await page.wait_for_timeout(3000)

            await process_pagination(page, context, downloaded_urls, manifest_rows)

        except Exception as exc:
            print("\nFATAL ERROR:", exc)

            try:
                await page.screenshot(
                    path=str(DOWNLOAD_DIR / "error_screenshot.png"), full_page=True
                )

                print("Saved debugging screenshot:" "\n ", DOWNLOAD_DIR / "error_screenshot.png")
            except Exception:
                pass

        finally:
            write_manifest(manifest_rows)

            print("\n-------------------------------")
            print(f"Unique PDFs downloaded: " f"{len(downloaded_urls)}")
            print(f"Download directory: " f"{DOWNLOAD_DIR.resolve()}")
            print(f"Manifest: " f"{MANIFEST_FILE.resolve()}")
            print("-------------------------------")

            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
