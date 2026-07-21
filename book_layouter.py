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

Spine width is estimated from page count and paper weight.
Gutter offsets push verso/recto content away from the spine curve.
"""

import argparse
import re
import sys
from math import ceil
from pathlib import Path

from pypdf import PdfReader, PdfWriter, PageObject, Transformation
from pypdf.generic import DecodedStreamObject

# ---------------------------------------------------------------------------
# Constants & defaults
# ---------------------------------------------------------------------------
MM_TO_PT = 2.834645669

A4_WIDTH_MM = 297
A4_HEIGHT_MM = 210
DEFAULT_MARGIN_MM = 10

RIGHT_PAGE_LEFT_PAD_MM = 2   # extra padding on the left (cut) side of the right page

# Paper caliper presets (mm per physical sheet, including binding glue/compression)
# Each physical sheet = 4 ebook pages (2 front + 2 back).
PAPER_CALIPERS = {
    "50gsm":  0.20,
    "60gsm":  0.22,
    "70gsm":  0.24,
    "80gsm":  0.26,
    "90gsm":  0.28,
    "100gsm": 0.32,
}
DEFAULT_PAPER_GSM = "50gsm"
DEFAULT_PAPER_CALIPER_MM = PAPER_CALIPERS[DEFAULT_PAPER_GSM]

# Base gutter (safety margin at spine edge of each page)
DEFAULT_BASE_GUTTER_MM = 3.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mm_to_pt(mm: float) -> float:
    """Convert millimeters to PDF points."""
    return mm * MM_TO_PT


def abbreviate(name: str) -> str:
    """Create a short abbreviation from a filename.

    Splits on common separators and takes the first letter of each word.
    'Introduction to Programming' -> 'itp'
    'my_book_title' -> 'mbt'
    'a-tale-of-two-cities' -> 'atotc'
    """
    words = re.split(r'[^a-zA-Z0-9]+', name)
    words = [w for w in words if w]
    if not words:
        return name[:3].lower()
    abbr = ''.join(w[0].lower() for w in words)
    return abbr


def make_output_dir(input_path: str) -> tuple[Path, str]:
    """Create an output folder named after the book and return (dir_path, abbr).

    Folder: <book_name>/
    Files:  <abbr>_layout.pdf, <abbr>_fronts.pdf, <abbr>_backs.pdf
    """
    p = Path(input_path)
    book_name = p.stem
    abbr = abbreviate(book_name)
    out_dir = p.parent / book_name
    out_dir.mkdir(exist_ok=True)
    return out_dir, abbr


def get_page_dimensions(page: PageObject) -> tuple[float, float, float, float]:
    """Get the visible width, height, and mediabox origin of a page in points.

    Returns (width, height, origin_x, origin_y).
    Origin is (mb.left, mb.bottom) — non-zero for cropped/trimmed PDFs.
    """
    mb = page.mediabox
    return float(mb.width), float(mb.height), float(mb.left), float(mb.bottom)


# ---------------------------------------------------------------------------
# Spine & gutter calculations
# ---------------------------------------------------------------------------

def estimate_spine_mm(total_pages: int, paper_caliper_mm: float = DEFAULT_PAPER_CALIPER_MM) -> float:
    """Estimate spine width for perfect binding.

    Each physical sheet = 4 ebook pages (2 front + 2 back).
    Sheets = total_pages / 4.
    Spine (mm) = sheets * paper_caliper_mm.
    """
    sheets = ceil(total_pages / 4)
    return sheets * paper_caliper_mm


def compute_gutter_pt(total_pages: int,
                      paper_caliper_mm: float = DEFAULT_PAPER_CALIPER_MM) -> float:
    """Compute total gutter offset in points.

    Auto-calculated from page count and paper weight:
        sheets = total_pages / 2
        spine  = sheets * caliper
        gutter = BASE_GUTTER_MM + spine / 2

    The spine contribution is halved because it's shared between the two
    leaves that sit on either side of the spine.

    Returns the value in PDF points.
    """
    spine_mm = estimate_spine_mm(total_pages, paper_caliper_mm)
    total_gutter_mm = DEFAULT_BASE_GUTTER_MM + spine_mm / 2
    return mm_to_pt(total_gutter_mm)


# ---------------------------------------------------------------------------
# Page slot geometry & placement
# ---------------------------------------------------------------------------

def _page_slot_positions(out_width: float, out_height: float,
                         margin: float, gutter_pts: float):
    """Compute the slot geometry for each page.

    Returns (slot_width, slot_height, left_x, right_x, slot_y).

    Each page spans from its edge to the absolute center.
    The gutter shrinks the usable content width (spine curve eats
    into the binding edge).  Content is centered within each half.

    Left page:                            Right page:
        ┌─margin─┬gutter┬──content──┬───┐ ┌───┬──content─┬gutter─┬margin─┐
        │        │ spine│  centered │   │ │   │ centered │ spine │       │
    margin                           center                             out_w-margin
    """
    center = out_width / 2
    half_width = center - margin
    content_width = half_width - gutter_pts
    slot_height = out_height - 2 * margin

    # Content is centered in each half: same outer margin and same inner gap.
    left_x = margin + gutter_pts / 2     # centered in left half
    right_x = center + gutter_pts / 2    # centered in right half
    slot_y = margin

    return content_width, slot_height, left_x, right_x, slot_y


def create_output_page(
    left_page: PageObject | None,
    right_page: PageObject | None,
    out_width: float,
    out_height: float,
    margin: float,
    gutter_pts: float,
) -> PageObject:
    """Create one landscape A4 output page with two ebook pages side by side.

    Both pages use the same absolute slot positions so front and back
    sides align perfectly when printed duplex.

    Differential gutter shifts:
        - Left (verso) page: content shifts LEFT (-X) toward outer edge.
        - Right (recto) page: content shifts RIGHT (+X) toward outer edge.
      This pushes content away from the spine curve on both sides.
    """
    slot_w, slot_h, left_x, right_x, slot_y = _page_slot_positions(
        out_width, out_height, margin, gutter_pts
    )

    output = PageObject.create_blank_page(width=out_width, height=out_height)

    # Merge left (verso) page — spine is on the RIGHT edge of this half.
    # Subtract gutter_pts to shift content leftward (away from spine).
    if left_page is not None:
        lw, lh, lox, loy = get_page_dimensions(left_page)
        scale = min(slot_w / lw, slot_h / lh)
        ty = slot_y + (slot_h - lh * scale) / 2 - loy * scale
        tx = left_x + (slot_w - lw * scale) / 2 - lox * scale - gutter_pts
        ctm = Transformation(ctm=(scale, 0, 0, scale, tx, ty))
        output.merge_transformed_page(left_page, ctm=ctm)

    # Merge right (recto) page — spine is on the LEFT edge of this half.
    # Add gutter_pts to shift content rightward (away from spine).
    right_pad = mm_to_pt(RIGHT_PAGE_LEFT_PAD_MM)
    if right_page is not None:
        rw, rh, rox, roy = get_page_dimensions(right_page)
        scale = min(slot_w / rw, slot_h / rh)
        ty = slot_y + (slot_h - rh * scale) / 2 - roy * scale
        tx = right_x + (slot_w - rw * scale) / 2 - rox * scale + gutter_pts + right_pad
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


# ---------------------------------------------------------------------------
# Imposition mapping
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main layout functions
# ---------------------------------------------------------------------------

def run_layout(
    input_path: str,
    output_path: str,
    margin_mm: float = DEFAULT_MARGIN_MM,
    verbose: bool = False,
    test_pages: int | None = None,
    paper_caliper_mm: float = DEFAULT_PAPER_CALIPER_MM,
) -> tuple[int, int]:
    """Run the layout process. Returns (input_page_count, output_page_count).

    Spine width and gutter are auto-calculated from page count and paper
    weight.  Gutter offsets push verso/recto content away from the spine.

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

    spine_mm = estimate_spine_mm(total_input, paper_caliper_mm)
    gutter_pt = compute_gutter_pt(total_input, paper_caliper_mm)
    gutter_mm = DEFAULT_BASE_GUTTER_MM + spine_mm / 2

    npad = ceil(total_input / 4) * 4
    half = npad // 2

    if verbose:
        print(f"Pages: {total_input}  |  Spine: {spine_mm:.2f} mm  |  "
              f"Gutter: {DEFAULT_BASE_GUTTER_MM}+{spine_mm/2:.2f}={gutter_mm:.2f} mm")
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
            out_width, out_height, margin, gutter_pt,
        )
        writer.add_page(front_page)
        total_output += 1

        # Back side
        back_page = create_output_page(
            _page(bl_idx), _page(br_idx),
            out_width, out_height, margin, gutter_pt,
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


def generate_cover(
    cover_pdf: str,
    output_path: str,
    total_pages: int,
    margin_mm: float = DEFAULT_MARGIN_MM,
    paper_caliper_mm: float = DEFAULT_PAPER_CALIPER_MM,
) -> None:
    """Generate a wrap-around cover page from a 2-page cover PDF.

    The cover PDF should have:
        Page 1 = front cover content
        Page 2 = back cover content

    Output is a single wide page:
        Width:  A4_width + spine + A4_width  (420 + spine mm)
        Height: A4 portrait (297 mm)

    Both cover halves get the same gutter shift as interior pages
    (content pushed away from the spine).
    """
    cover_reader = PdfReader(cover_pdf)
    if len(cover_reader.pages) < 2:
        raise ValueError("Cover PDF must have at least 2 pages (front + back cover)")

    back_cover = cover_reader.pages[0]   # page 1 = back cover (left side)
    front_cover = cover_reader.pages[1]  # page 2 = front cover (right side)

    spine_mm = estimate_spine_mm(total_pages, paper_caliper_mm)
    gutter_pt = compute_gutter_pt(total_pages, paper_caliper_mm)

    # Cover dimensions (portrait A4: 210mm wide x 297mm tall)
    a4_portrait_w_pt = mm_to_pt(A4_HEIGHT_MM)   # 210mm
    a4_portrait_h_pt = mm_to_pt(A4_WIDTH_MM)    # 297mm
    spine_pt = mm_to_pt(spine_mm)
    margin_pt = mm_to_pt(margin_mm)

    cover_width = a4_portrait_w_pt * 2 + spine_pt
    cover_height = a4_portrait_h_pt

    # Content area for each cover half
    half_w = a4_portrait_w_pt - margin_pt
    content_h = cover_height - 2 * margin_pt

    output = PageObject.create_blank_page(width=cover_width, height=cover_height)

    # Back cover (left side) — spine is on the RIGHT edge of this half
    # Shift content LEFT by gutter (away from spine)
    if back_cover is not None:
        bw, bh, bxo, byo = get_page_dimensions(back_cover)
        scale = min(half_w / bw, content_h / bh)
        ty = margin_pt + (content_h - bh * scale) / 2 - byo * scale
        tx = margin_pt + (half_w - bw * scale) / 2 - bxo * scale - gutter_pt
        ctm = Transformation(ctm=(scale, 0, 0, scale, tx, ty))
        output.merge_transformed_page(back_cover, ctm=ctm)

    # Front cover (right side) — spine is on the LEFT edge of this half
    # Shift content RIGHT by gutter (away from spine)
    if front_cover is not None:
        fw, fh, fxo, fyo = get_page_dimensions(front_cover)
        scale = min(half_w / fw, content_h / fh)
        ty = margin_pt + (content_h - fh * scale) / 2 - fyo * scale
        # Right half starts after back cover + spine
        right_x = a4_portrait_w_pt + spine_pt + margin_pt
        tx = right_x + (half_w - fw * scale) / 2 - fxo * scale + gutter_pt
        ctm = Transformation(ctm=(scale, 0, 0, scale, tx, ty))
        output.merge_transformed_page(front_cover, ctm=ctm)

    # Draw spine guidelines (dashed lines at spine edges)
    spine_left = a4_portrait_w_pt
    spine_right = a4_portrait_w_pt + spine_pt
    content = (
        f"q 0.5 G 0.3 w [2 2] 0 d "
        f"{spine_left:.2f} 0 m {spine_left:.2f} {cover_height:.2f} l S "
        f"{spine_right:.2f} 0 m {spine_right:.2f} {cover_height:.2f} l S "
        f"Q"
    ).encode("ascii")
    stream = DecodedStreamObject()
    stream.set_data(content)
    guide_page = PageObject.create_blank_page(width=cover_width, height=cover_height)
    guide_page.replace_contents(stream)
    output.merge_page(guide_page)

    writer = PdfWriter()
    writer.add_page(output)
    with open(output_path, "wb") as f:
        writer.write(f)


def split_into_sections(total_pages: int, num_sections: int) -> list[tuple[int, int]]:
    """Divide total_pages into num_sections equal-ish parts.

    Returns list of (start, end) tuples (0-based, end exclusive).
    """
    base, extra = divmod(total_pages, num_sections)
    sections = []
    start = 0
    for i in range(num_sections):
        count = base + (1 if i < extra else 0)
        sections.append((start, start + count))
        start += count
    return sections


def run_sections(
    input_path: str,
    output_prefix: str,
    num_sections: int,
    margin_mm: float = DEFAULT_MARGIN_MM,
    verbose: bool = False,
    paper_caliper_mm: float = DEFAULT_PAPER_CALIPER_MM,
) -> list[dict]:
    """Split a book into sections, lay out each, and auto-split fronts/backs.

    Returns list of dicts with keys:
        section, pages (start,end), layout_path, fronts_path, backs_path, page_count
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    reader = PdfReader(str(input_path))
    total_pages = len(reader.pages)
    sections = split_into_sections(total_pages, num_sections)

    prefix = Path(output_prefix)
    results = []

    for idx, (start, end) in enumerate(sections):
        section_num = idx + 1
        section_count = end - start

        # Write section pages to a temp PDF
        section_stem = f"{prefix.stem}_section{section_num}"
        section_path = str(prefix.parent / f"{section_stem}.pdf")
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])
        with open(section_path, "wb") as f:
            writer.write(f)

        # Layout the section
        layout_path = section_path
        page_in, page_out = run_layout(
            section_path, layout_path, margin_mm, verbose=verbose,
            paper_caliper_mm=paper_caliper_mm,
        )

        # Auto-split fronts/backs
        fronts_path = str(prefix.parent / f"{section_stem}_fronts.pdf")
        backs_path = str(prefix.parent / f"{section_stem}_backs.pdf")
        split_fronts_backs(layout_path, fronts_path, backs_path)

        results.append({
            "section": section_num,
            "pages": (start + 1, end),  # 1-based for display
            "layout_path": layout_path,
            "fronts_path": fronts_path,
            "backs_path": backs_path,
            "page_count": section_count,
        })

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Layout PDF pages for perfect binding (2-up A4 landscape)."
    )
    parser.add_argument("input", help="Input PDF file path")
    parser.add_argument("output", nargs="?", default=None,
                        help="Output PDF file path (auto-generated if omitted)")
    parser.add_argument(
        "--margin",
        type=float,
        default=DEFAULT_MARGIN_MM,
        help=f"Outer margin in mm (default: {DEFAULT_MARGIN_MM})",
    )
    parser.add_argument(
        "--paper",
        default=DEFAULT_PAPER_GSM,
        choices=list(PAPER_CALIPERS.keys()),
        help=f"Paper weight preset (default: {DEFAULT_PAPER_GSM})",
    )
    parser.add_argument(
        "--caliper",
        type=float,
        default=None,
        help="Paper caliper in mm (overrides --paper preset)",
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
    parser.add_argument(
        "--sections",
        type=int,
        default=1,
        help="Divide book into N sections with separate PDFs (default: 1 = no split).",
    )
    parser.add_argument(
        "--cover",
        default=None,
        help="Cover PDF (2 pages: front + back cover). Generates a wrap-around cover page.",
    )

    args = parser.parse_args()

    # Resolve paper caliper
    paper_caliper_mm = args.caliper if args.caliper is not None else PAPER_CALIPERS[args.paper]

    # Auto-generate output folder if not specified
    if args.output is None:
        out_dir, abbr = make_output_dir(args.input)
        output_path = str(out_dir / f"{abbr}_layout.pdf")
    else:
        output_path = args.output

    if args.sections > 1:
        # Section mode — use folder structure
        if args.output is None:
            output_prefix = str(out_dir / abbr)
        else:
            output_prefix = args.output
        try:
            results = run_sections(
                args.input, output_prefix, args.sections,
                margin_mm=args.margin, verbose=args.verbose,
                paper_caliper_mm=paper_caliper_mm,
            )
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"\nDivided into {args.sections} sections:")
        for r in results:
            s, e = r["pages"]
            print(f"  Section {r['section']}: pages {s}-{e} ({r['page_count']} pages)")
            print(f"    Layout: {r['layout_path']}")
            print(f"    Fronts: {r['fronts_path']}")
            print(f"    Backs:  {r['backs_path']}")
        print(f"\nProcess each section one at a time:")
        print(f"  1. Print fronts, reload paper, print backs")
        print(f"  2. Cut, stack Pile A + Pile B, bind")
        print(f"  3. Repeat for next section")
    else:
        # Single output mode
        try:
            total_input, total_output = run_layout(
                args.input, output_path, args.margin,
                verbose=args.verbose, test_pages=args.test_pages,
                paper_caliper_mm=paper_caliper_mm,
            )
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        spine_mm = estimate_spine_mm(total_input, paper_caliper_mm)
        gutter_mm = DEFAULT_BASE_GUTTER_MM + spine_mm / 2
        print(f"Input:  {total_input} pages")
        print(f"Output: {total_output} pages (landscape A4)")
        print(f"Spine:  {spine_mm:.2f} mm ({args.paper})")
        print(f"Gutter: {DEFAULT_BASE_GUTTER_MM} + {spine_mm/2:.2f} = {gutter_mm:.2f} mm (auto)")
        print(f"Written to: {output_path}")

        if args.split:
            p = Path(output_path)
            fronts_path = str(p.with_stem(p.stem + "_fronts"))
            backs_path = str(p.with_stem(p.stem + "_backs"))
            split_fronts_backs(output_path, fronts_path, backs_path)
            print(f"Fronts: {fronts_path}")
            print(f"Backs:  {backs_path}")

        if args.cover:
            if args.output is None:
                cover_path = str(out_dir / f"{abbr}_cover.pdf")
            else:
                cover_path = str(Path(output_path).parent / f"{Path(output_path).stem}_cover.pdf")
            try:
                generate_cover(
                    args.cover, cover_path, total_input,
                    margin_mm=args.margin, paper_caliper_mm=paper_caliper_mm,
                )
                print(f"Cover:  {cover_path}")
            except Exception as e:
                print(f"Error generating cover: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
