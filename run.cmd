setlocal enabledelayedexpansion

if "%~1"=="" (
    echo ui ^| dev ^| build ^| linux
    goto :end
)

if "%~1"=="sim" (
    echo ========== Start sim ===========
    @REM start "" gos\plc_reader\plcsrv.exe --config configs/hardware/plc.json
    go run gos\vsp_sim\main.go
)

if "%~1"=="ui" (
    echo ========== UI ===========
    for /d %%i in (src\ui\*) do (
        set folder_name=%%~nxi
        if exist "%%i\_view.ui" (
            del /f /q "%%i\_view.py"
            pyside6-uic "%%i\_view.ui" -o "%%i\_view.py"
            echo Generated: %%i\_view.py
        )
    )
)

if "%~1"=="dev" (
    echo ========== Build ===========
    uv run src\main.py
)

if "%~1"=="build" (
    echo ========== Build ==========
    pushd "%~dp0"

    if exist "_build" rmdir /s /q "_build"
    if exist "_dist" rmdir /s /q "_dist"

    uv run pyinstaller --noconfirm ^
        --clean ^
        --onefile ^
        --name main ^
        --hidden-import="_elementtree" ^
        --hidden-import="xml.etree.cElementTree" ^
        --paths . ^
        --paths libs ^
        --collect-submodules ui ^
        --collect-submodules broker ^
        --collect-submodules plc ^
        --collect-submodules vsp ^
        --collect-submodules wf ^
        --collect-submodules pdf ^
        --hidden-import PySide6.QtWebEngineCore ^
        --hidden-import PySide6.QtWebEngineWidgets ^
        --distpath _dist ^
        --workpath _build ^
        --specpath _build ^
        main.py
    if errorlevel 1 (
        popd
        exit /b 1
    )

    echo Copying runtime and configuration files...
    xcopy "runtime" "_dist\runtime\" /E /I /Y >nul
    copy /Y "app.ini" "_dist\app.ini" >nul
    popd

    echo Build complete!
)


if "%~1"=="zip" (
    echo ========== Push to Vmware ===========
    for /f "delims=" %%i in ('powershell -Command "Get-Date -Format 'yyyy-MMdd-HH-mm'"') do set TS=%%i
    if not exist "..\.bak" mkdir "..\.bak"
    powershell -Command "Get-ChildItem -Path 'main' -Recurse | Where-Object { $_.FullName -notmatch '\__pycache__' } | Compress-Archive -DestinationPath 'main-!TS!.zip' -Force"
    move "main-!TS!.zip" "..\.bak\"
)

:end
exit /b
echo off
