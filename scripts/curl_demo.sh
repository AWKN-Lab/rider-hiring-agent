#!/usr/bin/env bash
# 用契约里的 curl 走一遍：建会话 → 7 轮消息 → progress 7/7 + 结构化 candidate
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8077}"
BASE="http://127.0.0.1:$PORT/api/v1"
python3 -m app.mock_model --port 8099 --log /tmp/model_requests.jsonl &
MOCK_PID=$!
MODEL_BASE_URL="http://127.0.0.1:8099/v1/chat/completions" python3 -m app.devserver --port "$PORT" &
API_PID=$!
trap 'kill $MOCK_PID $API_PID 2>/dev/null || true' EXIT
sleep 1.2

SID=$(curl -sS -X POST "$BASE/agent/sessions" -H 'Content-Type: application/json' -d '{}' \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_id"])')
echo "session_id = $SID"
for t in "我叫小王" "1995年3月" "住在望京小区" "我要全职" "我有电动车" "明天就能到" "跑过半年"; do
  curl -sS -X POST "$BASE/agent/sessions/$SID/messages" -H 'Content-Type: application/json' \
       -d "{\"text\": \"$t\"}" > /tmp/last.json
  printf "  %-12s → progress %s\n" "$t" \
    "$(python3 -c 'import json;d=json.load(open("/tmp/last.json"));p=d.get("progress") or {};print(p.get("collected"),"/",p.get("total"))')"
done
echo
echo "── 最终 candidate ──"
python3 -c 'import json;d=json.load(open("/tmp/last.json"));print(json.dumps(d.get("candidate"),ensure_ascii=False,indent=2))'
echo
echo "── 模型请求体里的手机号/身份证（应为占位符）──"
tail -1 /tmp/model_requests.jsonl | python3 -c 'import json,sys;d=json.load(sys.stdin);print(json.dumps(d.get("messages"),ensure_ascii=False)[:300])'
