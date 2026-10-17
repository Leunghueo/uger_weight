#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Change to the directory containing this script (the 'main' folder)
cd "$(dirname "$0")"

echo "Starting build process..."

# 1. Clean up old build directories (relative to current 'main' folder)
rm -rf kylin_build kylin_dist

# 2. Run PyInstaller
# We use 'uv run' to ensure it uses your project's dependencies
uv run pyinstaller --noconfirm \
    --clean \
    --onefile \
    --name main \
    --add-binary "/home/lh/miniconda3/envs/py312/lib/libsqlite3.so.0:." \
    --add-data "/home/lh/miniconda3/envs/py312/lib/python3.12/lib-dynload/_sqlite3.cpython-312-x86_64-linux-gnu.so:./python3.12/lib-dynload/" \
    --add-binary "/home/lh/miniconda3/envs/py312/lib/libexpat.so.1:." \
    --hidden-import="_elementtree" \
    --hidden-import="xml.etree.cElementTree" \
    --paths . \
    --paths libs \
    --collect-submodules ui \
    --collect-submodules broker \
    --collect-submodules vsp \
    --collect-submodules pdf \
    --hidden-import PySide6.QtWebEngineCore \
    --hidden-import PySide6.QtWebEngineWidgets \
    --distpath kylin_dist \
    --workpath kylin_build \
    --specpath kylin_build \
    main.py

# 3. Copy required assets
echo "Copying runtime and configuration files..."
cp -a runtime kylin_dist/runtime
cp -f app.ini kylin_dist/app.ini

echo "Build complete!"