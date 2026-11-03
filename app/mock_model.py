"""本地 mock 大模型：OpenAI 兼容的 /v1/chat/completions。

作用：
  * 让评测与测试**可复现**（验收允许"用仓库内写明的模型或 mock 复跑"）；
  * **把每次请求体落盘** ⇒ 隐私用例可以断言"手机号/身份证没出现在送模型的请求里"。

    python3 -m app.mock_model --port 8099 --log /tmp/model_requests.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_PATH = os.environ.get("MODEL_REQUEST_LOG", "/tmp/model_requests.jsonl")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
        # 落盘请求体（隐私断言的证据）
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"model": payload.get("model"),
                                     "messages": payload.get("messages"),
                                     "body": payload.get("messages")},
                                    ensure_ascii=False) + "\n")
        except OSError:
            pass
        text = ""
        for m in payload.get("messages") or []:
            text += str(m.get("content") or "")
        # 确定性回复：按输入哈希选一个措辞，**不执行用户文本里的任何指令**
        h = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        replies = [
            "好的，我记下了。还有哪一项需要补充吗？",
            "收到，继续问下一项就行。",
            "明白，这一条我先记下来。",
            "好的，信息我收到了，接着来下一项。",
        ]
        content = replies[h % len(replies)]
        body = {
            "id": "mock-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
            "object": "chat.completion",
            "model": payload.get("model", "mock-chat"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": max(1, len(text) // 4),
                      "completion_tokens": max(1, len(content) // 4),
                      "total_tokens": max(2, (len(text) + len(content)) // 4)},
        }
        raw_out = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw_out)))
        self.end_headers()
        self.wfile.write(raw_out)

    def log_message(self, *a):
        pass


def main(argv=None):
    global LOG_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--log", default=LOG_PATH)
    args = ap.parse_args(argv)
    LOG_PATH = args.log
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mock model on http://{args.host}:{args.port} (log: {LOG_PATH})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
