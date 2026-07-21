"""Display the global half-offset imposition mapping (swapped backs).

Formula (1-indexed):
    half        = npad / 2
    front-left  = 2i + 1
    front-right = half + 2i + 1
    back-left   = half + 2i + 2   (swapped — manual flip mirrors L/R)
    back-right  = 2i + 2          (swapped — manual flip mirrors L/R)

After cutting the entire stack at once:
    Pile A (left halves)  = pages 1..half
    Pile B (right halves) = pages half+1..npad
Stack Pile A then Pile B, perfect bind.

Note: the physical reading order depends on your specific flip and
binding method.  Verify with a test print before committing to a
full book.
"""

from book_layouter import compute_imposition, estimate_spine_mm
from math import ceil


def verify(total_pages: int):
    sheets = compute_imposition(total_pages)
    spine = estimate_spine_mm(total_pages)
    npad = ceil(total_pages / 4) * 4
    half = npad // 2

    print(f"\n{'='*60}")
    print(f"  total_pages = {total_pages}   npad = {npad}   "
          f"half = {half}   sheets = {len(sheets)}   spine = {spine:.2f} mm")
    print(f"{'='*60}")
    print(f"  {'Sheet':>5}  {'FL':>4}  {'FR':>4}  {'BL':>4}  {'BR':>4}")
    print(f"  {'-----':>5}  {'----':>4}  {'----':>4}  {'----':>4}  {'----':>4}")

    pile_a = []
    pile_b = []

    for i, s in enumerate(sheets):
        def _fmt(idx):
            return str(idx + 1) if idx is not None else "--"

        print(f"  {i:>5}  {_fmt(s['front_left']):>4}  {_fmt(s['front_right']):>4}  "
              f"{_fmt(s['back_left']):>4}  {_fmt(s['back_right']):>4}")

        pile_a.append(s["front_left"])
        pile_a.append(s["back_left"])
        pile_b.append(s["front_right"])
        pile_b.append(s["back_right"])

    def _pages(idxs):
        return [p + 1 for p in idxs if p is not None]

    a = _pages(pile_a)
    b = _pages(pile_b)

    print(f"\n  Pile A (left halves)  = {a}")
    print(f"  Pile B (right halves) = {b}")
    print(f"  Combined (A+B)        = {a + b}")


if __name__ == "__main__":
    for n in (8, 12, 20, 10):
        verify(n)
