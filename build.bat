@echo off
pip install pyinstaller
pyinstaller --onefile --windowed --name OnpliaProgressApp app.py
echo.
echo Built exe at dist\OnpliaProgressApp.exe
