@echo off
rem Build a single PikaChatDesktop.exe (no Python needed on the target PC).
rem Uses a clean virtual env so the exe stays small (~20 MB).
setlocal
cd /d "%~dp0"
if not exist .venv-build (
    python -m venv .venv-build || goto :error
)
call .venv-build\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :error
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name PikaChatDesktop ^
    --icon assets\pika\icon.ico ^
    --add-data "assets;assets" ^
    --hidden-import _cffi_backend ^
    --exclude-module asr --exclude-module numpy --exclude-module onnxruntime ^
    --exclude-module PIL --exclude-module sprites --exclude-module voice ^
    main.py || goto :error
echo.
echo Done: dist\PikaChatDesktop.exe
exit /b 0
:error
echo Build failed.
exit /b 1
