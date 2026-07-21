#!/usr/bin/env python3
"""Book Layouter GUI — Desktop app for perfect binding 2-up imposition."""

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path

from book_layouter import (
    run_layout, split_fronts_backs, remove_pages, parse_page_ranges,
    estimate_spine_mm, DEFAULT_MARGIN_MM,
)
from pypdf import PdfReader


class BookLayouterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Book Layouter")
        self.root.resizable(False, False)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.margin_var = tk.StringVar(value=str(DEFAULT_MARGIN_MM))
        self.test_pages_var = tk.StringVar(value="")

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}

        # --- Input file ---
        tk.Label(self.root, text="Input PDF:").grid(row=0, column=0, sticky="e", **pad)
        tk.Entry(self.root, textvariable=self.input_path, width=45).grid(row=0, column=1, **pad)
        tk.Button(self.root, text="Browse...", command=self._browse_input).grid(row=0, column=2, **pad)

        # --- Output file ---
        tk.Label(self.root, text="Output PDF:").grid(row=1, column=0, sticky="e", **pad)
        tk.Entry(self.root, textvariable=self.output_path, width=45).grid(row=1, column=1, **pad)
        tk.Button(self.root, text="Browse...", command=self._browse_output).grid(row=1, column=2, **pad)

        # --- Settings ---
        settings_frame = tk.LabelFrame(self.root, text="Settings", padx=12, pady=8)
        settings_frame.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)

        tk.Label(settings_frame, text="Margin (mm):").grid(row=0, column=0, sticky="e", padx=(0, 4))
        tk.Entry(settings_frame, textvariable=self.margin_var, width=8).grid(row=0, column=1)

        tk.Label(settings_frame, text="Spine:").grid(row=0, column=2, sticky="e", padx=(16, 4))
        tk.Label(settings_frame, text="auto (50gsm)", fg="gray").grid(row=0, column=3)

        tk.Label(settings_frame, text="Test pages:").grid(row=1, column=0, sticky="e", padx=(0, 4), pady=(4, 0))
        tk.Entry(settings_frame, textvariable=self.test_pages_var, width=8).grid(row=1, column=1, pady=(4, 0))
        tk.Label(settings_frame, text="leave empty for full book", fg="gray").grid(
            row=1, column=2, columnspan=2, sticky="w", padx=(16, 0), pady=(4, 0)
        )

        # --- Convert button ---
        self.convert_btn = tk.Button(
            self.root, text="Convert", width=16, height=2, command=self._convert
        )
        self.convert_btn.grid(row=3, column=0, columnspan=3, pady=(8, 4))

        # --- Tools row ---
        tools_frame = tk.Frame(self.root)
        tools_frame.grid(row=4, column=0, columnspan=3, pady=(0, 4))

        tk.Button(tools_frame, text="Split Fronts/Backs", width=18, command=self._split).pack(side="left", padx=4)
        tk.Button(tools_frame, text="Remove Pages", width=18, command=self._remove_pages).pack(side="left", padx=4)

        # --- Status ---
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var, fg="gray").grid(
            row=5, column=0, columnspan=3, pady=(0, 12)
        )

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select input PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.input_path.set(path)
            p = Path(path)
            self.output_path.set(str(p.parent / f"{p.stem}_layout.pdf"))

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save output PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if path:
            self.output_path.set(path)

    def _convert(self):
        input_path = self.input_path.get().strip()
        output_path = self.output_path.get().strip()

        if not input_path:
            messagebox.showwarning("Missing input", "Please select an input PDF file.")
            return
        if not output_path:
            messagebox.showwarning("Missing output", "Please choose an output file path.")
            return

        try:
            margin = float(self.margin_var.get())
        except ValueError:
            messagebox.showerror("Invalid settings", "Margin must be a number.")
            return

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

        self.convert_btn.config(state="disabled")
        self.status_var.set("Converting...")
        self.root.update_idletasks()

        try:
            total_in, total_out = run_layout(
                input_path, output_path, margin, test_pages=test_pages,
            )
            spine = estimate_spine_mm(total_in)

            # Auto-split into fronts and backs for manual duplex
            p = Path(output_path)
            fronts_path = str(p.with_stem(p.stem + "_fronts"))
            backs_path = str(p.with_stem(p.stem + "_backs"))
            split_fronts_backs(output_path, fronts_path, backs_path)

            front_count = len(PdfReader(fronts_path).pages)
            back_count = len(PdfReader(backs_path).pages)

            self.status_var.set(f"Done - {total_in} pages -> {total_out} sheets")

            mode = f"TEST ({test_pages} pages)" if test_pages else "Full book"
            messagebox.showinfo(
                "Success",
                f"Layout complete! ({mode})\n\n"
                f"Input:  {total_in} pages\n"
                f"Output: {total_out} landscape A4 sheets\n"
                f"Spine:  {spine:.2f} mm (50gsm estimate)\n\n"
                f"Fronts: {front_count} pages -> {fronts_path}\n"
                f"Backs:  {back_count} pages -> {backs_path}\n\n"
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
