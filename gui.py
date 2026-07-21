#!/usr/bin/env python3
"""Book Layouter GUI — Desktop app for perfect binding 2-up imposition."""

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path

from book_layouter import (
    run_layout, run_sections, split_fronts_backs, remove_pages, generate_cover,
    parse_page_ranges, estimate_spine_mm, compute_gutter_pt, make_output_dir,
    PAPER_CALIPERS, DEFAULT_PAPER_GSM, DEFAULT_PAPER_CALIPER_MM,
    DEFAULT_BASE_GUTTER_MM, DEFAULT_MARGIN_MM, MM_TO_PT,
    A4_WIDTH_MM, A4_HEIGHT_MM,
)
from pypdf import PdfReader


# ---------------------------------------------------------------------------
# Layout preview canvas
# ---------------------------------------------------------------------------

class LayoutPreview(tk.Canvas):
    """Draws a scaled diagram of one A4 landscape sheet showing page slots,
    spine gutter, margins, and the cut line.  Updates when settings change."""

    # Drawing scale: 1mm = this many pixels
    SCALE = 1.4
    PAD = 10  # pixels of padding around the diagram

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(bg="white", highlightthickness=0)

    def redraw(self, margin_mm: float, gutter_mm: float, spine_mm: float = 0):
        """Redraw the diagram with the given margin, gutter, and spine."""
        self.delete("all")
        s = self.SCALE
        pad = self.PAD

        # A4 landscape dimensions
        w = A4_WIDTH_MM
        h = A4_HEIGHT_MM
        center = w / 2

        # Pixel offsets for the drawing origin
        ox = pad
        oy = pad

        # Canvas size
        self.configure(width=int(w * s + 2 * pad), height=int(h * s + 2 * pad))

        # --- Outer sheet ---
        self._rect(ox, oy, w, h, outline="#333", width=2)

        # --- Margin guides ---
        self._rect(ox + margin_mm, oy + margin_mm,
                   w - 2 * margin_mm, h - 2 * margin_mm,
                   outline="#bbb", dash=(2, 2))

        # --- Left page slot ---
        left_slot_x = margin_mm
        slot_w = (center - margin_mm) - gutter_mm / 2
        slot_h = h - 2 * margin_mm
        self._rect(ox + left_slot_x, oy + margin_mm,
                   slot_w, slot_h, fill="#e8f0fe", outline="#999")

        # --- Right page slot ---
        right_slot_x = center + gutter_mm / 2
        self._rect(ox + right_slot_x, oy + margin_mm,
                   slot_w, slot_h, fill="#fef3e0", outline="#999")

        # --- Gutter region (light red) ---
        gutter_x = center - gutter_mm / 2
        self._rect(ox + gutter_x, oy, gutter_mm, h,
                   fill="#ffcccc", outline="#cc6666")

        # --- Spine region (dark red, centered in gutter) ---
        if spine_mm > 0:
            spine_x = center - spine_mm / 2
            self._rect(ox + spine_x, oy, spine_mm, h,
                       fill="#cc4444", outline="#992222")

        # --- Cut line (dashed center) ---
        cx = ox + center
        self.create_line(cx, oy, cx, oy + h * s,
                         fill="#cc0000", dash=(4, 3), width=1)

        # --- Labels ---
        self._label(ox + left_slot_x + slot_w / 2, oy + margin_mm + slot_h / 2,
                    "Left\n(verso)", "#333")
        self._label(ox + right_slot_x + slot_w / 2, oy + margin_mm + slot_h / 2,
                    "Right\n(recto)", "#333")
        self._label(ox + center, oy + h / 2,
                    f"spine\n{spine_mm:.1f}mm", "#fff")
        self._label(ox + center, oy + h * 0.25,
                    f"gutter {gutter_mm:.1f}mm", "#cc0000")

        # --- Dimension annotations ---
        # Spine width
        if spine_mm > 0:
            self._dim_line(ox + center - spine_mm / 2, oy - 5,
                           ox + center + spine_mm / 2, oy - 5,
                           f"spine {spine_mm:.1f}mm", "#992222")

        # Gutter width (offset below spine)
        self._dim_line(ox + center - gutter_mm / 2, oy - 14,
                       ox + center + gutter_mm / 2, oy - 14,
                       f"gutter {gutter_mm:.1f}mm", "#cc0000")

        # Slot width
        self._dim_line(ox + left_slot_x, oy + h + 5,
                       ox + left_slot_x + slot_w, oy + h + 5,
                       f"{slot_w:.1f}mm", "#666")

        # Margin
        self._dim_line(ox, oy + h + 12,
                       ox + margin_mm, oy + h + 12,
                       f"{margin_mm}mm", "#999")

    def _rect(self, x, y, w, h, **kwargs):
        s = self.SCALE
        self.create_rectangle(x * s, y * s, (x + w) * s, (y + h) * s, **kwargs)

    def _label(self, x, y, text, color):
        s = self.SCALE
        self.create_text(x * s, y * s, text=text, fill=color,
                         font=("Segoe UI", 8), justify="center")

    def _dim_line(self, x1, y1, x2, y2, label, color):
        s = self.SCALE
        self.create_line(x1 * s, y1 * s, x2 * s, y2 * s, fill=color, width=1)
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        self.create_text(mx * s, my * s, text=label, fill=color,
                         font=("Segoe UI", 7), anchor="n")


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class BookLayouterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Book Layouter")
        self.root.resizable(False, False)

        self.input_path = tk.StringVar()
        self.cover_path = tk.StringVar()
        self.margin_var = tk.StringVar(value=str(DEFAULT_MARGIN_MM))
        self.test_pages_var = tk.StringVar(value="")
        self.sections_var = tk.StringVar(value="1")
        self.paper_var = tk.StringVar(value=DEFAULT_PAPER_GSM)
        self.page_count = 0  # updated when a file is selected

        self._build_ui()
        self._update_preview()

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}

        # --- Input file ---
        tk.Label(self.root, text="Input PDF:").grid(row=0, column=0, sticky="e", **pad)
        tk.Entry(self.root, textvariable=self.input_path, width=45).grid(row=0, column=1, **pad)
        tk.Button(self.root, text="Browse...", command=self._browse_input).grid(row=0, column=2, **pad)

        # --- Cover file (optional) ---
        tk.Label(self.root, text="Cover PDF:").grid(row=1, column=0, sticky="e", **pad)
        tk.Entry(self.root, textvariable=self.cover_path, width=45).grid(row=1, column=1, **pad)
        tk.Button(self.root, text="Browse...", command=self._browse_cover).grid(row=1, column=2, **pad)

        # --- Settings ---
        settings_frame = tk.LabelFrame(self.root, text="Settings", padx=12, pady=8)
        settings_frame.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)

        # Row 0: Margin & Paper weight
        tk.Label(settings_frame, text="Margin (mm):").grid(row=0, column=0, sticky="e", padx=(0, 4))
        margin_entry = tk.Entry(settings_frame, textvariable=self.margin_var, width=8)
        margin_entry.grid(row=0, column=1)
        margin_entry.bind("<KeyRelease>", lambda e: self._update_preview())

        tk.Label(settings_frame, text="Paper:").grid(row=0, column=2, sticky="e", padx=(16, 4))
        paper_menu = tk.OptionMenu(settings_frame, self.paper_var, *PAPER_CALIPERS.keys())
        paper_menu.config(width=8)
        paper_menu.grid(row=0, column=3)
        self.paper_var.trace_add("write", lambda *a: self._update_preview())

        # Row 1: Sections & Test pages
        tk.Label(settings_frame, text="Sections:").grid(row=1, column=0, sticky="e", padx=(0, 4), pady=(4, 0))
        tk.Entry(settings_frame, textvariable=self.sections_var, width=8).grid(row=1, column=1, pady=(4, 0))
        tk.Label(settings_frame, text="1=no split, 4=quarter", fg="gray").grid(
            row=1, column=2, columnspan=2, sticky="w", padx=(16, 0), pady=(4, 0)
        )

        tk.Label(settings_frame, text="Test pages:").grid(row=2, column=0, sticky="e", padx=(0, 4), pady=(4, 0))
        tk.Entry(settings_frame, textvariable=self.test_pages_var, width=8).grid(row=2, column=1, pady=(4, 0))
        tk.Label(settings_frame, text="leave empty for full book", fg="gray").grid(
            row=2, column=2, columnspan=2, sticky="w", padx=(16, 0), pady=(4, 0)
        )

        # --- Preview & Dimensions (side by side) ---
        preview_frame = tk.LabelFrame(self.root, text="Layout Preview", padx=8, pady=8)
        preview_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(4, 4))

        self.preview = LayoutPreview(preview_frame, width=440, height=320)
        self.preview.pack(side="left")

        # Dimension readout
        dim_frame = tk.Frame(preview_frame)
        dim_frame.pack(side="left", padx=(12, 0), anchor="n")

        tk.Label(dim_frame, text="Dimensions", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.dim_spine = tk.Label(dim_frame, text="Spine: —", fg="#333", anchor="w", justify="left")
        self.dim_spine.pack(anchor="w", pady=(4, 0))
        self.dim_gutter = tk.Label(dim_frame, text="Gutter: —", fg="#333", anchor="w", justify="left")
        self.dim_gutter.pack(anchor="w", pady=(2, 0))
        self.dim_slot = tk.Label(dim_frame, text="Slot: —", fg="#333", anchor="w", justify="left")
        self.dim_slot.pack(anchor="w", pady=(2, 0))
        self.dim_margin = tk.Label(dim_frame, text="Margin: —", fg="#333", anchor="w", justify="left")
        self.dim_margin.pack(anchor="w", pady=(2, 0))
        self.dim_sheet = tk.Label(dim_frame, text="Sheet: —", fg="#666", anchor="w", justify="left")
        self.dim_sheet.pack(anchor="w", pady=(8, 0))

        # --- Convert button ---
        self.convert_btn = tk.Button(
            self.root, text="Convert", width=16, height=2, command=self._convert
        )
        self.convert_btn.grid(row=4, column=0, columnspan=3, pady=(8, 4))

        # --- Tools row ---
        tools_frame = tk.Frame(self.root)
        tools_frame.grid(row=5, column=0, columnspan=3, pady=(0, 4))

        tk.Button(tools_frame, text="Split Fronts/Backs", width=18, command=self._split).pack(side="left", padx=4)
        tk.Button(tools_frame, text="Remove Pages", width=18, command=self._remove_pages).pack(side="left", padx=4)

        # --- Status ---
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var, fg="gray").grid(
            row=6, column=0, columnspan=3, pady=(0, 12)
        )

    # ------------------------------------------------------------------
    # Preview & dimension updates
    # ------------------------------------------------------------------

    def _update_preview(self, *args):
        """Redraw the layout preview and dimension readout."""
        try:
            margin = float(self.margin_var.get())
        except ValueError:
            margin = DEFAULT_MARGIN_MM

        paper = self.paper_var.get()
        caliper = PAPER_CALIPERS.get(paper, DEFAULT_PAPER_CALIPER_MM)

        pages = self.page_count if self.page_count > 0 else 0
        spine_mm = estimate_spine_mm(pages, caliper) if pages > 0 else 0
        gutter_mm = DEFAULT_BASE_GUTTER_MM + spine_mm / 2

        # Redraw canvas
        self.preview.redraw(margin, gutter_mm, spine_mm)

        # Update dimension labels
        center_mm = A4_WIDTH_MM / 2
        slot_w = center_mm - margin - gutter_mm / 2
        slot_h = A4_HEIGHT_MM - 2 * margin

        if pages > 0:
            self.dim_spine.config(text=f"Spine:    {spine_mm:.2f} mm  ({pages}pg, {paper})")
            self.dim_gutter.config(text=f"Gutter:   {DEFAULT_BASE_GUTTER_MM} + {spine_mm/2:.2f} = {gutter_mm:.2f} mm")
        else:
            self.dim_spine.config(text="Spine:    (add a file to calculate)")
            self.dim_gutter.config(text="Gutter:   (add a file to calculate)")
        self.dim_slot.config(text=f"Slot:     {slot_w:.1f} x {slot_h:.1f} mm")
        self.dim_margin.config(text=f"Margin:   {margin} mm")
        self.dim_sheet.config(text=f"Sheet:    {A4_WIDTH_MM} x {A4_HEIGHT_MM} mm (landscape A4)")

    # ------------------------------------------------------------------
    # File dialogs
    # ------------------------------------------------------------------

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select input PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.input_path.set(path)
            # Read page count and update preview immediately
            try:
                self.page_count = len(PdfReader(path).pages)
            except Exception:
                self.page_count = 0
            self._update_preview()

    def _browse_cover(self):
        path = filedialog.askopenfilename(
            title="Select cover PDF (2 pages: front + back)",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.cover_path.set(path)

    # ------------------------------------------------------------------
    # Convert
    # ------------------------------------------------------------------

    def _convert(self):
        input_path = self.input_path.get().strip()

        if not input_path:
            messagebox.showwarning("Missing input", "Please select an input PDF file.")
            return

        try:
            margin = float(self.margin_var.get())
        except ValueError:
            messagebox.showerror("Invalid settings", "Margin must be a number.")
            return

        paper = self.paper_var.get()
        paper_caliper_mm = PAPER_CALIPERS.get(paper, DEFAULT_PAPER_CALIPER_MM)

        test_pages = None
        tp_str = self.test_pages_var.get().strip()
        if tp_str:
            try:
                test_pages = int(tp_str)
                if test_pages < 1:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid settings", "Test pages must be a positive number.")
                return

        try:
            sections = int(self.sections_var.get())
            if sections < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid settings", "Sections must be a positive number.")
            return

        self.convert_btn.config(state="disabled")
        self.status_var.set("Converting...")
        self.root.update_idletasks()

        try:
            out_dir, abbr = make_output_dir(input_path)

            if sections > 1:
                # Section mode
                output_prefix = str(out_dir / abbr)
                results = run_sections(
                    input_path, output_prefix, sections,
                    margin_mm=margin, paper_caliper_mm=paper_caliper_mm,
                )
                summary = f"Output folder: {out_dir}\n\n"
                summary += f"Paper: {paper} ({paper_caliper_mm} mm/sheet)\n\n"
                summary += f"Divided into {sections} sections:\n\n"
                for r in results:
                    s, e = r["pages"]
                    summary += (f"Section {r['section']}: pages {s}-{e} "
                               f"({r['page_count']} pages)\n")
                    summary += f"  {Path(r['fronts_path']).name}\n"
                    summary += f"  {Path(r['backs_path']).name}\n\n"
                summary += "Process each section one at a time:\n"
                summary += "1. Print fronts, reload, print backs\n"
                summary += "2. Cut, stack Pile A + Pile B, bind"
                self.status_var.set(f"Done - {sections} sections created")
                messagebox.showinfo("Success", summary)
            else:
                # Single output
                layout_path = str(out_dir / f"{abbr}_layout.pdf")
                total_in, total_out = run_layout(
                    input_path, layout_path, margin,
                    test_pages=test_pages,
                    paper_caliper_mm=paper_caliper_mm,
                )
                spine = estimate_spine_mm(total_in, paper_caliper_mm)
                gutter = DEFAULT_BASE_GUTTER_MM + spine / 2

                fronts_path = str(out_dir / f"{abbr}_fronts.pdf")
                backs_path = str(out_dir / f"{abbr}_backs.pdf")
                split_fronts_backs(layout_path, fronts_path, backs_path)

                front_count = len(PdfReader(fronts_path).pages)
                back_count = len(PdfReader(backs_path).pages)

                # Cover generation
                cover_msg = ""
                cover_input = self.cover_path.get().strip()
                if cover_input:
                    cover_out = str(out_dir / f"{abbr}_cover.pdf")
                    try:
                        generate_cover(
                            cover_input, cover_out, total_in,
                            margin_mm=margin, paper_caliper_mm=paper_caliper_mm,
                        )
                        cover_msg = f"\nCover:    {Path(cover_out).name}\n"
                    except Exception as e:
                        cover_msg = f"\nCover error: {e}\n"

                self.status_var.set(f"Done - {total_in} pages -> {total_out} sheets")
                mode = f"TEST ({test_pages} pages)" if test_pages else "Full book"
                messagebox.showinfo(
                    "Success",
                    f"Layout complete! ({mode})\n\n"
                    f"Folder: {out_dir}\n\n"
                    f"Input:  {total_in} pages\n"
                    f"Output: {total_out} landscape A4 sheets\n"
                    f"Paper:  {paper} ({paper_caliper_mm} mm/sheet)\n"
                    f"Spine:  {spine:.2f} mm\n"
                    f"Gutter: {DEFAULT_BASE_GUTTER_MM} + {spine/2:.2f} = {gutter:.2f} mm (auto)\n"
                    f"{cover_msg}\n"
                    f"Files:\n"
                    f"  {abbr}_layout.pdf\n"
                    f"  {abbr}_fronts.pdf ({front_count} pages)\n"
                    f"  {abbr}_backs.pdf ({back_count} pages)\n\n"
                    f"Print fronts first, reload paper, then print backs.",
                )
        except FileNotFoundError:
            messagebox.showerror("File not found", f"Could not find:\n{input_path}")
            self.status_var.set("Error - file not found")
        except Exception as e:
            messagebox.showerror("Error", f"Something went wrong:\n{e}")
            self.status_var.set("Error")
        finally:
            self.convert_btn.config(state="normal")

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def _split(self):
        """Split a laid-out PDF into fronts-only and backs-only files."""
        pdf_path = filedialog.askopenfilename(
            title="Select a laid-out PDF to split",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not pdf_path:
            return

        p = Path(pdf_path)

        fronts_path = filedialog.asksaveasfilename(
            title="Save fronts PDF as",
            initialfile=f"{p.stem}_fronts.pdf",
            initialdir=str(p.parent),
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not fronts_path:
            return

        backs_path = filedialog.asksaveasfilename(
            title="Save backs PDF as",
            initialfile=f"{p.stem}_backs.pdf",
            initialdir=str(p.parent),
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not backs_path:
            return

        try:
            split_fronts_backs(pdf_path, fronts_path, backs_path)
            front_count = len(PdfReader(fronts_path).pages)
            back_count = len(PdfReader(backs_path).pages)
            messagebox.showinfo(
                "Split complete",
                f"Fronts: {front_count} pages\n{fronts_path}\n\n"
                f"Backs: {back_count} pages\n{backs_path}",
            )
        except Exception as e:
            messagebox.showerror("Error", f"Split failed:\n{e}")

    def _remove_pages(self):
        """Remove selected pages from a PDF and save a new copy."""
        pdf_path = filedialog.askopenfilename(
            title="Select PDF to remove pages from",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not pdf_path:
            return

        try:
            reader = PdfReader(pdf_path)
            total = len(reader.pages)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read PDF:\n{e}")
            return

        spec = simpledialog.askstring(
            "Remove Pages",
            f"This PDF has {total} pages.\n\n"
            f"Enter page numbers to REMOVE:\n"
            f"(e.g. 1,3 or 1-4,7 or 1,3-5,9)",
            parent=self.root,
        )
        if not spec:
            return

        try:
            to_remove = parse_page_ranges(spec, total)
        except ValueError:
            messagebox.showerror("Invalid input", "Could not parse page numbers.")
            return

        if not to_remove:
            messagebox.showinfo("Nothing to remove", "No valid pages matched.")
            return

        remaining = total - len(to_remove)
        removed_str = ", ".join(str(n + 1) for n in sorted(to_remove))

        p = Path(pdf_path)
        output_path = filedialog.asksaveasfilename(
            title="Save trimmed PDF as",
            initialfile=f"{p.stem}_trimmed.pdf",
            initialdir=str(p.parent),
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not output_path:
            return

        try:
            remove_pages(pdf_path, output_path, to_remove)
            messagebox.showinfo(
                "Done",
                f"Removed pages: {removed_str}\n\n"
                f"Original: {total} pages\n"
                f"Result:   {remaining} pages\n\n"
                f"Saved to:\n{output_path}",
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed:\n{e}")


def main():
    root = tk.Tk()
    BookLayouterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
