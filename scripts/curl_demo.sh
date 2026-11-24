#!/usr/bin/env bash
# 用契约里的 curl 走一遍：建会话 → 7 轮消息 → progress 7/7 + 结构化 candidate
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8077}"
# mock 模型的端口与工作目录改为**可配**：
# 原实现把 8099 硬编码在本脚本里 ⇒ 只要该端口被占用（本机实测就被别的进程占着），
# mock 起不来，而 API 侧会走内置兜底把 7 轮跑完，最后才在 `tail` 那步炸掉
# ⇒ 表现成"跑了一半"的假象。现在：端口可配 + 启动即校验 + 中间产物隔离 + 失败立即退出。
MOCK_PORT="${MOCK_PORT:-8099}"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/rider-curl-demo.XXXXXX")"
MODEL_LOG="$WORKDIR/model_requests.jsonl"
LAST_JSON="$WORKDIR/last.json"
BASE="http://127.0.0.1:$PORT/api/v1"

python3 -m app.mock_model --port "$MOCK_PORT" --log "$MODEL_LOG" &
MOCK_PID=$!
MODEL_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1/chat/completions" python3 -m app.devserver --port "$PORT" &
API_PID=$!
cleanup() {
  kill $MOCK_PID $API_PID 2>/dev/null || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT
sleep 1.2

# fail fast：mock 没起来就立刻退出，不要让脚本半跑
if ! kill -0 "$MOCK_PID" 2>/dev/null; then
  echo "mock 模型未启动（端口 $MOCK_PORT 可能被占用）⇒ 用 MOCK_PORT=<空闲端口> 重跑" >&2
  exit 3
fi

SID=$(curl -sS -X POST "$BASE/agent/sessions" -H 'Content-Type: application/json' -d '{}' \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_id"])')
echo "session_id = $SID"
for t in "我叫小王" "1995年3月" "住在望京小区" "我要全职" "我有电动车" "明天就能到" "跑过半年"; do
  curl -sS -X POST "$BASE/agent/sessions/$SID/messages" -H 'Content-Type: application/json' \
       -d "{\"text\": \"$t\"}" > "$LAST_JSON"
  printf "  %-12s → progress %s\n" "$t" \
    "$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));p=d.get("progress") or {};print(p.get("collected"),"/",p.get("total"))' "$LAST_JSON")"
done
echo
echo "── 最终 candidate ──"
python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps(d.get("candidate"),ensure_ascii=False,indent=2))' "$LAST_JSON"
echo
echo "── 模型请求体里的手机号/身份证（应为占位符）──"
tail -1 "$MODEL_LOG" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(json.dumps(d.get("messages"),ensure_ascii=False)[:300])'
