#!/usr/bin/env python3

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

START_URL = "https://www.mca.gov.in/content/mca/global/en/home.html"

OUTPUT_DIR = Path("mca_browser_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def save_page_debug(page, prefix):
    print()
    print("=" * 78)
    print(f"SAVING DEBUG: {prefix}")
    print("=" * 78)

    # Screenshot
    screenshot_path = OUTPUT_DIR / f"{prefix}.png"

    try:
        await page.screenshot(
            path=str(screenshot_path),
            full_page=True,
        )
        print("Screenshot:", screenshot_path.resolve())
    except Exception as exc:
        print("Screenshot failed:", repr(exc))

    # HTML for every frame
    for frame_index, frame in enumerate(page.frames):
        try:
            html = await frame.content()

            html_path = OUTPUT_DIR / f"{prefix}_frame_{frame_index}.html"

            html_path.write_text(
                html,
                encoding="utf-8",
            )

            print(
                f"Frame #{frame_index} HTML:",
                html_path.resolve(),
            )

        except Exception as exc:
            print(
                f"Could not save frame #{frame_index}:",
                repr(exc),
            )


async def inspect_page(page, browser_name):
    print()
    print("=" * 78)
    print(f"{browser_name.upper()} - MCA INSPECTION")
    print("=" * 78)

    print("URL:", page.url)

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    try:
        title = await page.title()
    except Exception as exc:
        title = f"<ERROR: {exc!r}>"

    print("TITLE:", title)

    # --------------------------------------------------------
    # BODY TEXT PREVIEW
    # --------------------------------------------------------

    try:
        body_text = await page.locator("body").inner_text(timeout=10000)
    except Exception as exc:
        body_text = f"<ERROR READING BODY: {exc!r}>"

    body_preview = body_text[:5000]

    print()
    print("-" * 78)
    print("BODY TEXT PREVIEW")
    print("-" * 78)
    print(body_preview)

    # --------------------------------------------------------
    # TOTAL ANCHORS
    # --------------------------------------------------------

    try:
        anchor_count = await page.locator("a").count()
    except Exception:
        anchor_count = -1

    print()
    print("TOTAL ANCHORS:", anchor_count)

    # --------------------------------------------------------
    # EXACT ACTS & RULES SELECTORS
    # --------------------------------------------------------

    selectors = [
        '.second-navigation a[href="/content/mca/global/en/acts-rules.html"]',
        'a[href="/content/mca/global/en/acts-rules.html"]',
        'a:has-text("Acts & Rules")',
    ]

    print()
    print("-" * 78)
    print("ACTS & RULES SELECTOR CHECK")
    print("-" * 78)

    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()

            print(f"{selector!r}: {count}")

            for index in range(count):
                candidate = locator.nth(index)

                try:
                    text = await candidate.inner_text(timeout=2000)
                except Exception:
                    text = ""

                try:
                    href = await candidate.get_attribute("href")
                except Exception:
                    href = None

                try:
                    visible = await candidate.is_visible()
                except Exception:
                    visible = False

                print(f"  [{index}] " f"text={text!r} " f"href={href!r} " f"visible={visible}")

        except Exception as exc:
            print(f"{selector!r}: ERROR {exc!r}")

    # --------------------------------------------------------
    # SECOND NAVIGATION CHECK
    # --------------------------------------------------------

    print()
    print("-" * 78)
    print("SECOND NAVIGATION CHECK")
    print("-" * 78)

    second_nav_selectors = [
        ".second-navigation",
        ".ebooknavigation",
        ".second-navigation .ebooknavigation",
    ]

    for selector in second_nav_selectors:
        try:
            count = await page.locator(selector).count()

            print(f"{selector!r}: {count}")

        except Exception as exc:
            print(f"{selector!r}: ERROR {exc!r}")

    # --------------------------------------------------------
    # SEARCH PAGE FOR INTERESTING WORDS
    # --------------------------------------------------------

    interesting_terms = [
        "Acts & Rules",
        "second-navigation",
        "ebooknavigation",
        "Access Denied",
        "Forbidden",
        "captcha",
        "Cloudflare",
        "blocked",
        "enable javascript",
        "error",
    ]

    print()
    print("-" * 78)
    print("INTERESTING TERM CHECK")
    print("-" * 78)

    html = ""

    try:
        html = await page.content()
    except Exception:
        pass

    for term in interesting_terms:
        found = term.lower() in html.lower() or term.lower() in body_text.lower()

        print(f"{term!r}: {found}")

    # --------------------------------------------------------
    # ANCHOR DUMP
    # --------------------------------------------------------

    print()
    print("-" * 78)
    print("FIRST 100 ANCHORS")
    print("-" * 78)

    try:
        anchors = await page.evaluate("""
            () => Array.from(
                document.querySelectorAll('a')
            ).slice(0, 100).map((a, index) => ({
                index,
                text:
                    (a.innerText || '')
                    .replace(/\\s+/g, ' ')
                    .trim(),
                href:
                    a.getAttribute('href') || '',
                cls:
                    a.className || '',
                id:
                    a.id || ''
            }))
            """)

        for anchor in anchors:
            print(anchor)

    except Exception as exc:
        print(
            "Anchor dump failed:",
            repr(exc),
        )

    # --------------------------------------------------------
    # FRAME DUMP
    # --------------------------------------------------------

    print()
    print("-" * 78)
    print("FRAME LIST")
    print("-" * 78)

    for index, frame in enumerate(page.frames):
        print(f"Frame #{index}: {frame.url}")

    # --------------------------------------------------------
    # SAVE FILES
    # --------------------------------------------------------

    await save_page_debug(
        page,
        browser_name.lower(),
    )


async def run_browser(
    playwright,
    browser_name,
):
    print()
    print("#" * 78)
    print(f"STARTING {browser_name.upper()}")
    print("#" * 78)

    browser_type = playwright.chromium if browser_name == "chromium" else playwright.firefox

    try:
        browser = await browser_type.launch(
            headless=True,
        )

    except Exception as exc:
        print()
        print(f"{browser_name.upper()} FAILED TO LAUNCH:")
        print(repr(exc))
        return

    context = await browser.new_context(
        viewport={
            "width": 1920,
            "height": 1080,
        },
        locale="en-US",
    )

    page = await context.new_page()

    page.set_default_timeout(15000)

    # --------------------------------------------------------
    # LOG RESPONSES
    # --------------------------------------------------------

    async def log_response(response):
        try:
            url = response.url

            if "mca.gov.in" in url and response.request.resource_type == "document":
                print(f"[DOCUMENT RESPONSE] " f"{response.status} " f"{url}")

        except Exception:
            pass

    page.on(
        "response",
        log_response,
    )

    # --------------------------------------------------------
    # LOG REQUEST FAILURES
    # --------------------------------------------------------

    async def log_request_failed(request):
        try:
            print(
                "[REQUEST FAILED]",
                request.resource_type,
                request.url,
                request.failure,
            )
        except Exception:
            pass

    page.on(
        "requestfailed",
        log_request_failed,
    )

    try:
        print()
        print("Opening:")
        print(START_URL)

        response = await page.goto(
            START_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        if response is not None:
            print(
                "Main response status:",
                response.status,
            )

            print(
                "Main response URL:",
                response.url,
            )

        await page.wait_for_timeout(5000)

        await inspect_page(
            page,
            browser_name,
        )

    except Exception as exc:
        print()
        print(f"{browser_name.upper()} TEST ERROR:")
        print(repr(exc))

        await save_page_debug(
            page,
            f"{browser_name}_error",
        )

    finally:
        await browser.close()


async def main():
    async with async_playwright() as p:

        # ----------------------------------------------------
        # CHROMIUM
        # ----------------------------------------------------

        await run_browser(
            p,
            "chromium",
        )

        # ----------------------------------------------------
        # FIREFOX
        # ----------------------------------------------------

        await run_browser(
            p,
            "firefox",
        )

    print()
    print("=" * 78)
    print("TEST COMPLETE")
    print("=" * 78)

    print(
        "Debug directory:",
        OUTPUT_DIR.resolve(),
    )

    print()
    print("Expected files include:")

    print("  chromium.png")

    print("  chromium_frame_0.html")

    print("  firefox.png")

    print("  firefox_frame_0.html")


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print()
        print("Stopped.")
