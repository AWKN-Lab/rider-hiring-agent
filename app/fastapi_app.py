"""FastAPI 适配层（契约要求 Python 3.12 + FastAPI）。

本文件**只做适配**：路由、校验、业务逻辑全部复用 app/api.py 与 app/core.py，
所以"契约测试跑的那份代码"与"生产跑的那份代码"是同一份实现。

依赖（许可均为 MIT / BSD / Apache-2.0）：
    fastapi  uvicorn  pydantic  psycopg[binary]  redis  httpx
FastAPI 不在时给出清晰提示（而不是 ImportError 栈）。
"""
from __future__ import annotations

import os

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "FastAPI 未安装。生产环境：pip install -r requirements.txt（见 docker-compose.yml）。"
        "无 FastAPI 时可用标准库等价实现：python3 -m app.devserver --port 8077"
    ) from exc

from . import contract as C
from .api import Api, ApiError
from .core import ConversationEngine, ModelClient, PolicyKB, Stations, Vault
from .policy_seed import seed_policies

app = FastAPI(title="Rider Hiring Agent API", version="1.0.0",
              description="任务 1/5：Agent 对话引擎与政策知识库（共用接口契约 v1）")


def build_engine() -> ConversationEngine:
    vault = Vault()
    model = ModelClient(primary_url=os.environ.get("MODEL_BASE_URL"),
                        primary_model=os.environ.get("MODEL_NAME", "mock-chat"),
                        backup_url=os.environ.get("MODEL_BACKUP_URL") or os.environ.get("MODEL_BASE_URL"),
                        backup_model=os.environ.get("MODEL_BACKUP_NAME", "mock-chat-backup"),
                        timeout=float(os.environ.get("MODEL_TIMEOUT", "5")))
    return ConversationEngine(vault, model, PolicyKB(seed_policies()), Stations())


api = Api(build_engine())


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "rider-hiring-agent", "contract": "v1"}


@app.get("/openapi.json")
def openapi_json():
    return api.handle_openapi({}, {}, {}, {})[1]


@app.post("/api/v1/agent/sessions")
def create_session():
    status, payload = api.dispatch("POST", "/api/v1/agent/sessions", {}, {}, {})
    return JSONResponse(payload, status_code=status)


@app.post("/api/v1/agent/sessions/{session_id}/messages")
async def post_message(session_id: str, request: Request):
    body = await request.json()
    headers = {k.lower(): v for k, v in request.headers.items()}
    status, payload = api.dispatch("POST", f"/api/v1/agent/sessions/{session_id}/messages",
                                   {}, body, headers)
    return JSONResponse(payload, status_code=status)


@app.get("/api/v1/agent/sessions/{session_id}")
def get_session(session_id: str):
    status, payload = api.dispatch("GET", f"/api/v1/agent/sessions/{session_id}", {}, {}, {})
    return JSONResponse(payload, status_code=status)


@app.post("/api/v1/vault/tokenize")
async def vault_tokenize(request: Request):
    body = await request.json()
    status, payload = api.dispatch("POST", "/api/v1/vault/tokenize", {}, body,
                                   {k.lower(): v for k, v in request.headers.items()})
    return JSONResponse(payload, status_code=status)


@app.post("/api/v1/vault/detokenize")
async def vault_detokenize(request: Request):
    body = await request.json()
    status, payload = api.dispatch("POST", "/api/v1/vault/detokenize", {}, body,
                                   {k.lower(): v for k, v in request.headers.items()})
    return JSONResponse(payload, status_code=status)


@app.get("/api/v1/agent/policy/search")
def policy_search(q: str = "", city: str | None = None):
    status, payload = api.dispatch("GET", "/api/v1/agent/policy/search", {"q": q, "city": city}, {}, {})
    return JSONResponse(payload, status_code=status)


@app.get("/api/v1/agent/policy/answer")
def policy_answer(q: str = "", city: str | None = None):
    status, payload = api.dispatch("GET", "/api/v1/agent/policy/answer", {"q": q, "city": city}, {}, {})
    return JSONResponse(payload, status_code=status)


@app.get("/api/v1/agent/stations")
def stations(area_text: str | None = None):
    status, payload = api.dispatch("GET", "/api/v1/agent/stations", {"area_text": area_text}, {}, {})
    return JSONResponse(payload, status_code=status)


@app.get("/api/v1/agent/slots")
def slots(station_id: str = ""):
    status, payload = api.dispatch("GET", "/api/v1/agent/slots", {"station_id": station_id}, {}, {})
    return JSONResponse(payload, status_code=status)


@app.get("/api/v1/agent/report/daily")
def daily_report():
    status, payload = api.dispatch("GET", "/api/v1/agent/report/daily", {}, {}, {})
    return JSONResponse(payload, status_code=status)


@app.get("/api/v1/agent/eval/metrics")
def eval_metrics():
    status, payload = api.dispatch("GET", "/api/v1/agent/eval/metrics", {}, {}, {})
    return JSONResponse(payload, status_code=status)
