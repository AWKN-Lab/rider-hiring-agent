#!/usr/bin/env python3
"""变异自证：故意把门禁改坏，**证明它们会红**。

恒真的测试等于没有测试。这里对每一道门禁注入一个行为变异，
然后跑对应的检查，**要求它失败**；任何一道变异没被抓住 ⇒ 证明失败 ⇒ 非零退出。

    python3 scripts/mutation_proof.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (名称, 文件, 原片段, 变异片段, 要跑的命令)
MUTATIONS = [
    ("关掉未成年终止", "app/core.py",
     "            if age < MINOR_AGE:", "            if False:",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ("关掉送模型前的脱敏", "app/core.py",
     "        safe_text = self._scrub(text)",
     "        safe_text = text",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ("让政策查询瞎编（不查不到）", "app/core.py",
     "        if not hits:\n            return {\"found\": False, \"handoff\": True,",
     "        if False:\n            return {\"found\": False, \"handoff\": True,",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ("关掉提示词注入拦截", "app/core.py",
     "        if g[\"injection\"]:",
     "        if False:",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ("让护栏永远说没问题", "app/core.py",
     "    if any(re.search(p, text) for p in INCOME_PROMISE):",
     "    if False:",
     [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ("让抽取失准（区域永远抽不到）", "app/core.py",
     "        m = AREA_RE.search(text)",
     "        m = None",
     [sys.executable, "eval/run_eval.py"]),
]


def run(cmd, cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    return proc.returncode, proc.stdout


def main() -> int:
    caught, missed = [], []
    for name, rel, old, new, cmd in MUTATIONS:
        tmp = Path(tempfile.mkdtemp(prefix="mut-"))
        work = tmp / "repo"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
            "__pycache__", ".git", "data", "eval/dataset"))
        target = work / rel
        text = target.read_text(encoding="utf-8")
        if old not in text:
            print(f"  ⚠️ {name}: 变异锚点没找到（跳过）")
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        code, out = run(cmd, work)
        marker = "FAILED" if "unittest" in " ".join(cmd) else "结论           : FAIL"
        right_reason = marker in out
        if code != 0 and right_reason:
            caught.append(name)
            tail = [l for l in out.splitlines() if l.strip()][-1:] or [""]
            print(f"  ✅ 抓住：{name:<22} → 检查变红（{tail[0][:70]}）")
        else:
            missed.append(name)
            why = "检查仍然全绿（门禁形同虚设）" if code == 0 else "红了，但不是因该变异而红（理由不对）"
            print(f"  ❌ 没抓住：{name:<22} → {why}")
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n  变异 {len(MUTATIONS)} 个 → 抓住 {len(caught)} 个，漏 {len(missed)} 个")
    print(f"  结论: {'PASS（门禁会红，不是恒真断言）' if not missed else 'FAIL: ' + ', '.join(missed)}")
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
