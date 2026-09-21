#!/usr/bin/env bash
# XBot - Linux/macOS cron sarmalayicisi (varsayilan: dry-run)
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUTF8=1
python3 -m xbot run --headless --rapor >> logs/gorev.log 2>&1
