"""标准库 HTTP 服务器（无第三方依赖），用于本机验证契约与 curl 演示。

生产用 FastAPI（app/fastapi_app.py）—— 两者共用 app/api.py 的同一份路由与处理器。
    python3 -m app.devserver --port 8077
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .api import Api, ApiError
from .core import ConversationEngine, ModelClient, PolicyKB, Stations, Vault
from .policy_seed import seed_policies


def build_engine() -> ConversationEngine:
    vault = Vault()
    model = ModelClient(primary_url=os.environ.get("MODEL_BASE_URL"),
                        primary_model=os.environ.get("MODEL_NAME", "mock-chat"),
                        backup_url=os.environ.get("MODEL_BACKUP_URL") or os.environ.get("MODEL_BASE_URL"),
                        backup_model=os.environ.get("MODEL_BACKUP_NAME", "mock-chat-backup"),
                        timeout=float(os.environ.get("MODEL_TIMEOUT", "5")))
    return ConversationEngine(vault, model, PolicyKB(seed_policies()), Stations())


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle(self, method: str):
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                self._send(400, {"code": "BAD_REQUEST", "message": "invalid json body"})
                return
            headers = {k.lower(): v for k, v in self.headers.items()}
            try:
                status, payload = api.dispatch(method, parsed.path, query, body, headers)
            except ApiError as exc:
                status, payload = exc.status, exc.body()
            self._send(status, payload)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def log_message(self, *a):  # 安静
            pass

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8077)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    api = Api(build_engine())
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(api))
    print(f"dev server on http://{args.host}:{args.port}  (contract v1)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
