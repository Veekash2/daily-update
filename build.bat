@echo off
pip install pyinstaller
pyinstaller --onefile --windowed --name LetMeMakeYourLifeEasier --icon=app_icon.ico app.py
echo.
echo Built exe at dist\LetMeMakeYourLifeEasier.exe
