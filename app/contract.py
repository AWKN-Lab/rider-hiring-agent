"""共用接口契约 v1 —— 本仓库的实现必须逐项对齐。

来源：ClawHunt #1808《骑手招聘 Agent 化信息收集平台 · 任务 1/5》
契约是 5 个任务共用的，所以这里只放"必须一致"的部分，
任务 1 自己的实现放在 app/core.py。

许可：仅使用 MIT / Apache-2.0 / BSD / PostgreSQL 许可的依赖。
"""
from __future__ import annotations

API_PREFIX = "/api/v1"

# ── 候选人 candidate（契约原文字段）────────────────────────────────────
CANDIDATE_FIELDS = [
    "id", "name_token", "phone_token", "birth_ym", "area_text", "job_type",
    "has_ebike", "start_text", "experience_text", "health_cert",
    "source_channel", "station_id", "status", "consent_version", "consent_at",
    "retention_until", "created_at", "updated_at",
]
JOB_TYPES = ["fulltime", "parttime", "undecided"]
HEALTH_CERTS = ["none", "holding", "processing", "unknown"]
CANDIDATE_STATUSES = [
    "new", "collecting", "complete", "booked", "interviewed", "hired",
    "rejected", "handoff",
]

# ── 站点 station / 预约 booking ────────────────────────────────────────
STATION_FIELDS = ["id", "name", "lat", "lng", "open_quota"]
BOOKING_FIELDS = ["id", "candidate_id", "station_id", "slot_start",
                  "status"]  # status: booked|cancelled|done|no_show

# ── 事件（outbox + Webhook，HMAC-SHA256 签名）─────────────────────────
EVENT_TYPES = [
    "candidate.created", "candidate.updated", "candidate.completed",
    "booking.created", "booking.cancelled", "handoff.created",
]

# ── 任务 1 提供的接口 ─────────────────────────────────────────────────
# POST /api/v1/agent/sessions            → {session_id}
# POST /api/v1/agent/sessions/{id}/messages {text} → {reply, quick_replies[...], ...}
# POST /api/v1/vault/tokenize {type,value} → {token}
# POST /api/v1/vault/detokenize {token,reason} → 需权限 + 写审计
# 错误体统一 {code, message}
ERROR_BODY_KEYS = ["code", "message"]

# ── 错误码 ───────────────────────────────────────────────────────────
E_UNKNOWN_SESSION = "AGENT_SESSION_UNKNOWN"
E_SESSION_TOKEN_REQUIRED = "AGENT_SESSION_TOKEN_REQUIRED"
E_SESSION_TOKEN_INVALID = "AGENT_SESSION_TOKEN_INVALID"
E_VAULT_PERMISSION_DENIED = "VAULT_PERMISSION_DENIED"
E_VAULT_REASON_REQUIRED = "VAULT_REASON_REQUIRED"
E_VAULT_TOKEN_UNKNOWN = "VAULT_TOKEN_UNKNOWN"
E_POLICY_NOT_FOUND = "POLICY_NOT_FOUND"
E_END_MINOR = "AGENT_END_MINOR"
E_FIELD_INVALID = "AGENT_FIELD_INVALID"
E_BAD_REQUEST = "BAD_REQUEST"

# ── 路由表（契约测试直接比对这份表；FastAPI 层与标准库层共用）────────
ROUTES = [
    ("POST", "/api/v1/agent/sessions", "create_session"),
    ("POST", "/api/v1/agent/sessions/{session_id}/messages", "post_message"),
    ("GET", "/api/v1/agent/sessions/{session_id}", "get_session"),
    ("POST", "/api/v1/vault/tokenize", "vault_tokenize"),
    ("POST", "/api/v1/vault/detokenize", "vault_detokenize"),
    ("GET", "/api/v1/agent/policy/search", "policy_search"),
    ("GET", "/api/v1/agent/policy/answer", "policy_answer"),
    ("GET", "/api/v1/agent/stations", "list_stations"),
    ("GET", "/api/v1/agent/slots", "list_slots"),
    ("GET", "/api/v1/agent/report/daily", "daily_report"),
    ("GET", "/api/v1/agent/eval/metrics", "eval_metrics"),
    ("GET", "/api/v1/healthz", "healthz"),
    ("GET", "/openapi.json", "openapi"),
]

# ── 会话 7 项（顺序即采集顺序）────────────────────────────────────────
SLOTS = [
    ("name_token", "称呼"),
    ("birth_ym", "出生年月"),
    ("area_text", "意向区域"),
    ("job_type", "岗位意向"),
    ("has_ebike", "车辆"),
    ("start_text", "到岗时间"),
    ("experience_text", "配送经验"),
]
SLOT_KEYS = [k for k, _ in SLOTS]
SLOT_LABELS = dict(SLOTS)

# ── 验收阈值（评测脚本按此判定）──────────────────────────────────────
ACCEPTANCE = {
    "extraction_accuracy_min": 0.95,
    "policy_qa_accuracy_min": 0.90,
    "violation_max": 0,
    "dataset_min": 300,
    "counter_examples_min": 30,
    "prompt_injection_min": 10,
    "model": "runner-up",
    "license_ok": ["MIT", "Apache-2.0", "BSD", "PostgreSQL"],
}
