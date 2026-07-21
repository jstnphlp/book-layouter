@echo off
echo Building Book Layouter...
echo.

py -m pip install -r requirements.txt

py -m PyInstaller --onefile --windowed --name "Book Layouter" gui.py

echo.
echo Done! The executable is in: dist\Book Layouter.exe
echo You can copy that file to any Windows PC and run it directly.
pause
