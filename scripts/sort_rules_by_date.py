#!/usr/bin/env python3

import re
from pathlib import Path
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================

RULES_DIR = Path("mca_companies_act_2013/rules")

# Set True first if you only want to preview changes.
DRY_RUN = False


# ============================================================
# DATE EXTRACTION
# ============================================================


def extract_notification_date(filename):
    """
    Finds a date like:

        31-03-2014

    from filenames such as:

        Chapter I ... - Rule 1 to 4 - 31-03-2014 -
        1. Short Title and Commencement .pdf

    Returns:
        datetime object
        or None
    """

    matches = re.findall(
        r"(?<!\d)" r"(\d{1,2})-(\d{1,2})-(\d{4})" r"(?!\d)",
        filename,
    )

    if not matches:
        return None

    # Usually there should only be one date.
    # Take the first valid date.
    for day, month, year in matches:
        try:
            return datetime(
                int(year),
                int(month),
                int(day),
            )

        except ValueError:
            continue

    return None


# ============================================================
# REMOVE OLD SORT PREFIX
# ============================================================


def remove_existing_sort_prefix(filename):
    """
    Makes script safe to rerun.

    Removes:

        2014-03-31 -

    from the start if already present.
    """

    return re.sub(
        r"^\d{4}-\d{2}-\d{2}\s+-\s+",
        "",
        filename,
        count=1,
    )


# ============================================================
# UNIQUE DESTINATION
# ============================================================


def unique_destination(path):
    """
    Avoid accidental overwrite.

    Example:

        name.pdf
        name (2).pdf
        name (3).pdf
    """

    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix

    counter = 2

    while True:
        candidate = path.with_name(f"{stem} ({counter}){suffix}")

        if not candidate.exists():
            return candidate

        counter += 1


# ============================================================
# MAIN
# ============================================================


def main():
    print()
    print("=" * 78)
    print("SORT MCA RULE PDFs BY NOTIFICATION DATE")
    print("=" * 78)

    print(
        "Folder:",
        RULES_DIR.resolve(),
    )

    print(
        "Dry run:",
        DRY_RUN,
    )

    print("=" * 78)

    if not RULES_DIR.exists():
        raise SystemExit(f"Folder does not exist:\n" f"{RULES_DIR.resolve()}")

    pdf_files = sorted(RULES_DIR.glob("*.pdf"))

    print(
        "PDF files found:",
        len(pdf_files),
    )

    renamed = 0
    skipped = 0
    no_date = 0

    for index, path in enumerate(
        pdf_files,
        start=1,
    ):
        original_name = path.name

        # -----------------------------------------------
        # Remove prefix if script was run previously
        # -----------------------------------------------

        base_name = remove_existing_sort_prefix(original_name)

        # -----------------------------------------------
        # Extract DD-MM-YYYY
        # -----------------------------------------------

        date = extract_notification_date(base_name)

        if date is None:
            print()
            print(f"[{index}/{len(pdf_files)}] " "NO DATE")

            print(
                " ",
                original_name,
            )

            no_date += 1
            continue

        # -----------------------------------------------
        # Convert to YYYY-MM-DD
        # -----------------------------------------------

        sort_date = date.strftime("%Y-%m-%d")

        new_name = f"{sort_date} - " f"{base_name}"

        destination = path.with_name(new_name)

        # -----------------------------------------------
        # Already correct
        # -----------------------------------------------

        if path.name == destination.name:
            print()
            print(f"[{index}/{len(pdf_files)}] " "ALREADY SORTED")

            print(
                " ",
                path.name,
            )

            skipped += 1
            continue

        # -----------------------------------------------
        # Collision protection
        # -----------------------------------------------

        if destination.exists() and destination != path:
            destination = unique_destination(destination)

        print()
        print(f"[{index}/{len(pdf_files)}]")

        print(
            "OLD:",
            original_name,
        )

        print(
            "NEW:",
            destination.name,
        )

        # -----------------------------------------------
        # Rename
        # -----------------------------------------------

        if not DRY_RUN:
            path.rename(destination)

        renamed += 1

    print()
    print("=" * 78)
    print("COMPLETE")
    print("=" * 78)

    print(
        "PDF files:",
        len(pdf_files),
    )

    print(
        "Renamed:",
        renamed,
    )

    print(
        "Already sorted:",
        skipped,
    )

    print(
        "No date found:",
        no_date,
    )

    print("=" * 78)


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
