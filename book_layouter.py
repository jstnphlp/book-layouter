#!/usr/bin/env python3
"""Book Layouter — Perfect binding 2-up imposition for A4 landscape.

Global half-offset imposition for manual-duplex printers.

Takes a PDF ebook and produces a print-ready PDF where each landscape A4
sheet holds 2 ebook pages side-by-side.  Back-left/right are swapped to
correct for a manual flip that mirrors left-right.

Workflow:
    1. Convert → produces laid-out PDF (auto-split into _fronts and _backs)
    2. Print _fronts, reload paper, print _backs
    3. Cut the ENTIRE stack at once vertically along the dashed guideline
    4. Left halves = Pile A (pages 1..half), right halves = Pile B (half+1..N)
    5. Stack Pile A then Pile B, perfect bind — pages read 1,2,3,…N

Spine width is estimated from page count and paper weight (default 50gsm).
"""

import argparse
import sys
from math import ceil
from pathlib import Path

from pypdf import PdfReader, PdfWriter, PageObject, Transformation
from pypdf.generic import DecodedStreamObject

# Constants
MM_TO_PT = 2.834645669
RIGHT_PAGE_LEFT_PAD_MM = 2   # extra padding on the left (cut) side of the right page
A4_WIDTH_MM = 297
A4_HEIGHT_MM = 210
DEFAULT_MARGIN_MM = 10

# 50gsm uncoated: ~0.04 mm per leaf (600-660 PPI)
# Each physical sheet = 2 leaves after cutting
CALIPER_MM_PER_LEAF = 0.04


def mm_to_pt(mm: float) -> float:
    """Convert millimeters to PDF points."""
    return mm * MM_TO_PT


def get_page_dimensions(page: PageObject) -> tuple[float, float, float, float]:
    """Get the visible width, height, and mediabox origin of a page in points.

    Returns (width, height, origin_x, origin_y).
    Origin is (mb.left, mb.bottom) — non-zero for cropped/trimmed PDFs.
    """
    mb = page.mediabox
    return float(mb.width), float(mb.height), float(mb.left), float(mb.bottom)


def estimate_spine_mm(total_pages: int, caliper: float = CALIPER_MM_PER_LEAF) -> float:
    """Estimate spine width for perfect binding.

    Each physical A4 sheet produces 2 leaves after cutting.
    Each leaf = 2 ebook pages (front + back).
    Spine width = num_leaves * caliper.
    """
    num_leaves = ceil(total_pages / 2)
    return num_leaves * caliper


def _page_slot_positions(out_width: float, out_height: float,
                         margin: float, spine_offset: float):
    """Compute the slot geometry for each page.

    Returns (slot_width, slot_height, left_x, right_x, slot_y).

    Each page spans from its edge to the absolute center.
    The spine_offset shrinks the usable content width (glue eats
    into the binding edge).  Content is centered within each half.

    Left page:                            Right page:
        ┌─margin─┬spine┬──content──┬─────┐ ┌─────┬──content─┬spine─┬margin─┐
        │        │glue │  centered │     │ │     │ centered │ glue │       │
    margin                           center                             out_w-margin
    """
    center = out_width / 2
    half_width = center - margin
    content_width = half_width - spine_offset
    slot_height = out_height - 2 * margin

    # Content is centered in each half: same outer margin and same inner gap.
    left_x = margin + spine_offset / 2     # centered in left half
    right_x = center + spine_offset / 2    # centered in right half
    slot_y = margin

    return content_width, slot_height, left_x, right_x, slot_y


def create_output_page(
    left_page: PageObject | None,
    right_page: PageObject | None,
    out_width: float,
    out_height: float,
    margin: float,
    spine_offset: float,
) -> PageObject:
    """Create one landscape A4 output page with two ebook pages side by side.

    Both pages use the same absolute slot positions so front and back
    sides align perfectly when printed duplex.
    """
    slot_w, slot_h, left_x, right_x, slot_y = _page_slot_positions(
        out_width, out_height, margin, spine_offset
    )

    output = PageObject.create_blank_page(width=out_width, height=out_height)

    # Merge left page
    # slot_w already reserves the spine gutter, so centering happens
    # within the remaining content width, not the full half-page width.
    # Subtract mediabox origin so the transform is relative to the page's
    # actual visible origin, not an assumed (0,0).
    if left_page is not None:
        lw, lh, lox, loy = get_page_dimensions(left_page)
        scale = min(slot_w / lw, slot_h / lh)  # fit-to-fill, preserving aspect ratio
        ty = slot_y + (slot_h - lh * scale) / 2 - loy * scale
        tx = left_x + (slot_w - lw * scale) / 2 - lox * scale
        ctm = Transformation(ctm=(scale, 0, 0, scale, tx, ty))
        output.merge_transformed_page(left_page, ctm=ctm)

    # Merge right page
    # Extra left-side padding shifts content away from the cut line.
    right_pad = mm_to_pt(RIGHT_PAGE_LEFT_PAD_MM)
    if right_page is not None:
        rw, rh, rox, roy = get_page_dimensions(right_page)
        scale = min(slot_w / rw, slot_h / rh)
        ty = slot_y + (slot_h - rh * scale) / 2 - roy * scale
        tx = right_x + (slot_w - rw * scale) / 2 - rox * scale + right_pad
        ctm = Transformation(ctm=(scale, 0, 0, scale, tx, ty))
        output.merge_transformed_page(right_page, ctm=ctm)

    # Add center guideline (absolute center — same position front and back)
    _add_guideline(output, out_width, out_height)

    return output


def _add_guideline(page: PageObject, out_width: float, out_height: float):
    """Draw a dashed vertical line at the absolute center of the page."""
    center_x = out_width / 2

    content = (
        f"q 0.5 G 0.4 w [3 3] 0 d "
        f"{center_x:.2f} 0 m {center_x:.2f} {out_height:.2f} l "
        f"S Q"
    ).encode("ascii")

    stream = DecodedStreamObject()
    stream.set_data(content)

    guideline_page = PageObject.create_blank_page(width=out_width, height=out_height)
    guideline_page.replace_contents(stream)
    page.merge_page(guideline_page)


def compute_imposition(total_pages: int) -> list[dict[str, int | None]]:
    """Compute the page-to-slot mapping for every output sheet.

    Returns a list of dicts, one per sheet, each with keys:
        front_left, front_right, back_left, back_right
    Values are 0-based page indices, or None for blank slots.

    Global half-offset formula (1-indexed page numbers):
        half        = npad / 2
        front-left  = 2i + 1
        front-right = half + 2i + 1
        back-left   = half + 2i + 2   (swapped — manual flip mirrors L/R)
        back-right  = 2i + 2          (swapped — manual flip mirrors L/R)

    After cutting the entire stack at once, left halves form Pile A
    (pages 1..half, already in order) and right halves form Pile B
    (pages half+1..npad, already in order).  Concatenate A then B —
    no interleaving needed.
    """
    npad = ceil(total_pages / 4) * 4
    half = npad // 2
    num_sheets = npad // 4

    sheets = []
    for i in range(num_sheets):
        fl = 2 * i              # front-left  (0-based)
        fr = half + 2 * i       # front-right
        bl = half + 2 * i + 1   # back-left   (swapped)
        br = 2 * i + 1          # back-right  (swapped)

        sheets.append({
            "front_left":   fl if fl < total_pages else None,
            "front_right":  fr if fr < total_pages else None,
            "back_left":    bl if bl < total_pages else None,
            "back_right":   br if br < total_pages else None,
        })
    return sheets


def run_layout(
    input_path: str,
    output_path: str,
    margin_mm: float = DEFAULT_MARGIN_MM,
    verbose: bool = False,
    test_pages: int | None = None,
) -> tuple[int, int]:
    """Run the layout process. Returns (input_page_count, output_page_count).

    Spine width is auto-estimated from page count and 50gsm caliper.

    If test_pages is set, only the first N pages of the input are used.
    Useful for verifying the imposition before committing to a full book.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    out_width = mm_to_pt(A4_WIDTH_MM)
    out_height = mm_to_pt(A4_HEIGHT_MM)
    margin = mm_to_pt(margin_mm)

    reader = PdfReader(str(input_path))
    writer = PdfWriter()

    all_pages = reader.pages
    if test_pages is not None:
        pages = all_pages[:test_pages]
    else:
        pages = all_pages
    total_input = len(pages)
    total_output = 0

    spine_mm = estimate_spine_mm(total_input)
    spine_pt = mm_to_pt(spine_mm)

    npad = ceil(total_input / 4) * 4
    half = npad // 2

    if verbose:
        print(f"Pages: {total_input}  |  Spine estimate: {spine_mm:.2f} mm")
        print()
        print(f"  {'Page':>4}  {'W':>6}  {'H':>6}  {'Left':>6}  {'Bot':>6}")
        print(f"  {'----':>4}  {'------':>6}  {'------':>6}  {'------':>6}  {'------':>6}")
        for pg_idx, pg in enumerate(pages):
            pw, ph, px, py = get_page_dimensions(pg)
            origin_flag = "" if px == 0 and py == 0 else "  *"
            print(f"  {pg_idx + 1:>4}  {pw:>6.1f}  {ph:>6.1f}  {px:>6.1f}  {py:>6.1f}{origin_flag}")
        if any(get_page_dimensions(p)[2] != 0 or get_page_dimensions(p)[3] != 0 for p in pages):
            print("  (* = non-zero mediabox origin)")
        print()
        print(f"  {'Sheet':>5}  {'FL':>4}  {'FR':>4}  {'BL':>4}  {'BR':>4}")
        print(f"  {'-----':>5}  {'----':>4}  {'----':>4}  {'----':>4}  {'----':>4}")

    sheets = compute_imposition(total_input)

    for sheet_idx, sheet in enumerate(sheets):
        def _page(idx: int | None) -> PageObject | None:
            return pages[idx] if idx is not None else None

        fl_idx = sheet["front_left"]
        fr_idx = sheet["front_right"]
        bl_idx = sheet["back_left"]
        br_idx = sheet["back_right"]

        if verbose:
            def _fmt(idx: int | None) -> str:
                return str(idx + 1) if idx is not None else "--"
            print(f"  {sheet_idx:>5}  {_fmt(fl_idx):>4}  {_fmt(fr_idx):>4}  "
                  f"{_fmt(bl_idx):>4}  {_fmt(br_idx):>4}")

        # Front side
        front_page = create_output_page(
            _page(fl_idx), _page(fr_idx),
            out_width, out_height, margin, spine_pt,
        )
        writer.add_page(front_page)
        total_output += 1

        # Back side
        back_page = create_output_page(
            _page(bl_idx), _page(br_idx),
            out_width, out_height, margin, spine_pt,
        )
        writer.add_page(back_page)
        total_output += 1

    if verbose:
        pile_a_last = min(half, total_input)
        pile_b_first = half + 1
        pile_b_last = min(npad, total_input)
        print()
        print(f"  Pile A (left halves)  = pages 1-{pile_a_last}")
        print(f"  Pile B (right halves) = pages {pile_b_first}-{pile_b_last}")
        print()
        print("  Cut the ENTIRE stack at once, keep piles in sheet order,")
        print("  then place Pile B after Pile A.  No interleaving needed.")

    with open(output_path, "wb") as f:
        writer.write(f)

    return total_input, total_output


def parse_page_ranges(spec: str, total_pages: int) -> set[int]:
    """Parse a page-range spec like '1,3,5-8' into a set of 0-based indices.

    Accepts comma-separated values, each either a single number or a
    dash-separated range.  Numbers are 1-based (user-facing).
    """
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            lo, hi = int(lo.strip()), int(hi.strip())
            for n in range(lo, hi + 1):
                if 1 <= n <= total_pages:
                    pages.add(n - 1)
        else:
            n = int(part)
            if 1 <= n <= total_pages:
                pages.add(n - 1)
    return pages


def remove_pages(pdf_path: str, output_path: str, pages_to_remove: set[int]):
    """Write a new PDF excluding the given 0-based page indices."""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if i not in pages_to_remove:
            writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)


def split_fronts_backs(pdf_path: str, fronts_path: str, backs_path: str):
    """Split a laid-out PDF into front-only and back-only PDFs.

    Output pages at even indices (0, 2, 4, …) are fronts.
    Output pages at odd  indices (1, 3, 5, …) are backs.

    Useful for manual duplex: print fronts_path first, reload paper,
    then print backs_path.
    """
    reader = PdfReader(pdf_path)

    fronts_writer = PdfWriter()
    backs_writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if i % 2 == 0:
            fronts_writer.add_page(page)
        else:
            backs_writer.add_page(page)

    with open(fronts_path, "wb") as f:
        fronts_writer.write(f)
    with open(backs_path, "wb") as f:
        backs_writer.write(f)


def main():
    parser = argparse.ArgumentParser(
        description="Layout PDF pages for perfect binding (2-up A4 landscape)."
    )
    parser.add_argument("input", help="Input PDF file path")
    parser.add_argument("output", help="Output PDF file path")
    parser.add_argument(
        "--margin",
        type=float,
        default=DEFAULT_MARGIN_MM,
        help=f"Outer margin in mm (default: {DEFAULT_MARGIN_MM})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print per-sheet page assignments and spine estimate.",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        default=False,
        help="Also split output into _fronts.pdf and _backs.pdf for manual duplex.",
    )
    parser.add_argument(
        "--test-pages",
        type=int,
        default=None,
        help="Only process the first N pages (for test printing before full run).",
    )

    args = parser.parse_args()

    try:
        total_input, total_output = run_layout(
            args.input, args.output, args.margin,
            verbose=args.verbose,
            test_pages=args.test_pages,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Input:  {total_input} pages")
    print(f"Output: {total_output} pages (landscape A4)")
    print(f"Spine:  {estimate_spine_mm(total_input):.2f} mm (50gsm estimate)")
    print(f"Written to: {args.output}")

    if args.split:
        p = Path(args.output)
        fronts_path = str(p.with_stem(p.stem + "_fronts"))
        backs_path = str(p.with_stem(p.stem + "_backs"))
        split_fronts_backs(args.output, fronts_path, backs_path)
        print(f"Fronts: {fronts_path}")
        print(f"Backs:  {backs_path}")


if __name__ == "__main__":
    main()
