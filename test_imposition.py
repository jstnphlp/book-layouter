"""Verify the global half-offset imposition mapping.

Formula (1-indexed):
    half        = npad / 2
    front-left  = 2i + 1
    front-right = half + 2i + 1
    back-left   = half + 2i + 2   (swapped)
    back-right  = 2i + 2          (swapped)

After cutting the entire stack at once:
    Pile A (left halves)  = pages 1..half
    Pile B (right halves) = pages half+1..npad
Concatenate A then B for correct reading order.
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

    pile_a_fronts = []   # front-left pages, in sheet order
    pile_a_backs = []    # back-left pages, in sheet order
    pile_b_fronts = []   # front-right pages, in sheet order
    pile_b_backs = []    # back-right pages, in sheet order

    for i, s in enumerate(sheets):
        fl = s["front_left"]
        fr = s["front_right"]
        bl = s["back_left"]
        br = s["back_right"]

        def _fmt(idx):
            return str(idx + 1) if idx is not None else "--"

        print(f"  {i:>5}  {_fmt(fl):>4}  {_fmt(fr):>4}  {_fmt(bl):>4}  {_fmt(br):>4}")

        pile_a_fronts.append(fl)
        pile_a_backs.append(bl)
        pile_b_fronts.append(fr)
        pile_b_backs.append(br)

    def _pages(idxs):
        return [p + 1 for p in idxs if p is not None]

    a_fronts = _pages(pile_a_fronts)
    a_backs = _pages(pile_a_backs)
    b_fronts = _pages(pile_b_fronts)
    b_backs = _pages(pile_b_backs)

    # Reading order: for each pile, fronts then backs (bound at left edge,
    # each leaf shows front then back when flipped)
    reading_a = []
    for j in range(len(pile_a_fronts)):
        if pile_a_fronts[j] is not None:
            reading_a.append(pile_a_fronts[j] + 1)
        if pile_a_backs[j] is not None:
            reading_a.append(pile_a_backs[j] + 1)

    reading_b = []
    for j in range(len(pile_b_fronts)):
        if pile_b_fronts[j] is not None:
            reading_b.append(pile_b_fronts[j] + 1)
        if pile_b_backs[j] is not None:
            reading_b.append(pile_b_backs[j] + 1)

    print(f"\n  Pile A fronts: {a_fronts}")
    print(f"  Pile A backs:  {a_backs}")
    print(f"  Pile A reads:  {reading_a}")
    print(f"  Pile B fronts: {b_fronts}")
    print(f"  Pile B backs:  {b_backs}")
    print(f"  Pile B reads:  {reading_b}")
    print(f"  Combined (A+B): {reading_a + reading_b}")

    expected = list(range(1, total_pages + 1))
    if reading_a + reading_b == expected:
        print("  [OK] CORRECT")
    else:
        print(f"  [FAIL] WRONG -- expected {expected}")


if __name__ == "__main__":
    for n in (8, 12, 20, 10):
        verify(n)
