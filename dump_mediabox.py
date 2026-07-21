"""Dump mediabox details for specific pages in a PDF.

Usage:
    py dump_mediabox.py input.pdf              # pages 0 and 8
    py dump_mediabox.py input.pdf 0 1 2 3      # specific page indices
"""

import sys
from pypdf import PdfReader


def dump(pdf_path: str, indices: list[int]):
    reader = PdfReader(pdf_path)
    total = len(reader.pages)

    print(f"File: {pdf_path}  ({total} pages)")
    print()
    print(f"  {'Page':>5}  {'Left':>8}  {'Bottom':>8}  {'Right':>8}  {'Top':>8}  {'Width':>8}  {'Height':>8}")
    print(f"  {'-----':>5}  {'--------':>8}  {'--------':>8}  {'--------':>8}  {'--------':>8}  {'--------':>8}  {'--------':>8}")

    for idx in indices:
        if idx < 0 or idx >= total:
            print(f"  {idx:>5}  (out of range)")
            continue
        page = reader.pages[idx]
        mb = page.mediabox
        left = float(mb.left)
        bottom = float(mb.bottom)
        right = float(mb.right)
        top = float(mb.top)
        w = float(mb.width)
        h = float(mb.height)
        flag = "  *" if left != 0 or bottom != 0 else ""
        print(f"  {idx:>5}  {left:>8.1f}  {bottom:>8.1f}  {right:>8.1f}  {top:>8.1f}  {w:>8.1f}  {h:>8.1f}{flag}")

    if any(
        float(reader.pages[i].mediabox.left) != 0 or float(reader.pages[i].mediabox.bottom) != 0
        for i in indices if 0 <= i < total
    ):
        print()
        print("  (* = non-zero origin)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py dump_mediabox.py input.pdf [page_indices...]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if len(sys.argv) > 2:
        indices = [int(x) for x in sys.argv[2:]]
    else:
        indices = [0, 8]

    dump(pdf_path, indices)
