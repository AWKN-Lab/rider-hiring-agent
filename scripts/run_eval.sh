#!/usr/bin/env bash
# 一条命令跑评测：生成数据集 + 输出验收三指标（确定性，可复现）
set -euo pipefail
cd "$(dirname "$0")/.."
python3 eval/generate_dataset.py
python3 eval/run_eval.py
