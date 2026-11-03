#!/usr/bin/env bash
# 一条命令跑全部单元测试（只用标准库）
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -v
