# book-layouter

Automatic 2-up A4 landscape imposition for perfect binding. Takes a PDF ebook and produces a print-ready PDF arranged for cutting each sheet in half vertically and stacking the halves for binding.

## Setup

```
py -m pip install -r requirements.txt
```

## GUI App

Launch the desktop app:

```
py gui.py
```

1. Click **Browse** to select your input PDF
2. Choose where to save the output (auto-filled)
3. Adjust margin/gutter if needed
4. Click **Convert**

## CLI Usage

```
py book_layouter.py input.pdf output.pdf
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--margin` | `10` | Outer margin in mm around each sheet |
| `--gutter` | `5` | Spine gutter in mm (extra space for glue binding) |

### Example

```
py book_layouter.py ebook.pdf print_ready.pdf --margin 12 --gutter 6
```

## Layout

Each output page is A4 landscape (297 × 210 mm) with two ebook pages side-by-side. **Odd pages on front, even pages on back** (directly behind their odd counterpart). A dashed center guideline marks where to cut.

```
Sheet 1, Front (odd):           Sheet 1, Back (even):
┌──────────┬──────────┐        ┌──────────┬──────────┐
│  Page 1  │  Page 3  │        │  Page 2  │  Page 4  │
│          │          │        │ (behind 1)│(behind 3)│
└──────────┴──────────┘        └──────────┴──────────┘
         │ (dashed cut line)           │ (dashed cut line)

Sheet 2, Front:                  Sheet 2, Back:
┌──────────┬──────────┐        ┌──────────┬──────────┐
│  Page 5  │  Page 7  │        │  Page 6  │  Page 8  │
└──────────┴──────────┘        └──────────┴──────────┘
```

### How it works

1. Print double-sided (duplex) on A4
2. Cut each sheet in half vertically along the dashed guideline
3. Stack all left halves on top of all right halves
4. Perfect bind at the left edge

**Result:** Pages read 1, 2, 3, 4, 5, 6, 7, 8 ... in correct order.

- Dashed center guideline for easy cutting
- Spine gutter accounts for ~5mm of glue in perfect binding
- Pages are **scaled proportionally** to fit (no stretching)
- Remainder pages (not divisible by 4) get blank slots
