"""路由表 + 处理器（纯标准库）。FastAPI 层与 dev server 共用同一份实现。

契约：错误体统一 {code, message}；REST 前缀 /api/v1；JSON。
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import contract as C
from .core import ConversationEngine


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def body(self) -> dict:
        return {"code": self.code, "message": self.message}


def _path_params(route: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", route)


class Api:
    def __init__(self, engine: ConversationEngine, store=None):
        self.engine = engine
        self.store = store
        self.routes = {m + " " + p: h for m, p, h in C.ROUTES}

    # ── 派发 ──────────────────────────────────────────────────────────
    def dispatch(self, method: str, path: str, query: dict, body: dict,
                 headers: dict) -> tuple[int, dict]:
        clean = path.rstrip("/") or "/"
        for (m, p, h) in C.ROUTES:
            if m != method:
                continue
            p_clean = p.rstrip("/") or "/"
            pp = _path_params(p)
            if not pp:
                if p_clean == clean:
                    return self._call(h, {}, query, body, headers)
                continue
            pattern = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", re.escape(p).replace(r"\{", "{").replace(r"\}", "}")) + "$"
            pattern = re.escape(p_clean)
            pattern = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", pattern)
            m2 = re.match(pattern, clean)
            if m2:
                return self._call(h, m2.groupdict(), query, body, headers)
        return 404, {"code": C.E_BAD_REQUEST, "message": f"no route for {method} {path}"}

    def _call(self, handler, params, query, body, headers) -> tuple[int, dict]:
        fn = getattr(self, "handle_" + handler)
        try:
            result = fn(params, query, body, headers)
        except ApiError as exc:
            return exc.status, exc.body()
        except PermissionError as exc:
            return 403, {"code": C.E_VAULT_PERMISSION_DENIED, "message": str(exc)}
        except KeyError as exc:
            return 404, {"code": str(exc), "message": "not found"}
        except ValueError as exc:
            return 400, {"code": C.E_BAD_REQUEST, "message": str(exc)}
        status, payload = result if isinstance(result, tuple) else (200, result)
        return status, payload

    # ── 处理器 ────────────────────────────────────────────────────────
    def handle_create_session(self, params, query, body, headers):
        sess = self.engine.create_session()
        if self.store:
            self.store.save_session(sess)
        return 201, {"session_id": sess.id, "status": sess.status,
                     "candidate": self.engine._public_candidate(sess)}

    def handle_post_message(self, params, query, body, headers):
        sid = params["session_id"]
        token = headers.get("x-agent-session-token") or headers.get("x-session-token")
        if token is not None and token != sid:
            raise ApiError(C.E_SESSION_TOKEN_INVALID, "session token mismatch", status=403)
        text = (body or {}).get("text")
        if not isinstance(text, str) or not text.strip():
            raise ApiError(C.E_BAD_REQUEST, "text is required")
        out = self.engine.handle_message(sid, text)
        if "error" in out:
            raise ApiError(out["error"]["code"], out["error"]["message"], status=404)
        if self.store:
            sess = self.engine.sessions.get(sid)
            if sess:
                self.store.save_session(sess)
        return 200, out

    def handle_get_session(self, params, query, body, headers):
        sess = self.engine.sessions.get(params["session_id"])
        if not sess:
            raise ApiError(C.E_UNKNOWN_SESSION, "session not found", status=404)
        return 200, {"session_id": sess.id, "status": sess.status,
                     "candidate": self.engine._public_candidate(sess),
                     "turns": len(sess.turns)}

    def handle_vault_tokenize(self, params, query, body, headers):
        kind = (body or {}).get("type"); value = (body or {}).get("value")
        if not kind or not isinstance(value, str):
            raise ApiError(C.E_BAD_REQUEST, "type and value are required")
        try:
            token = self.engine.vault.tokenize(kind, value)
        except ValueError as exc:
            raise ApiError(C.E_BAD_REQUEST, str(exc))
        return 200, {"token": token}

    def handle_vault_detokenize(self, params, query, body, headers):
        token = (body or {}).get("token"); reason = (body or {}).get("reason")
        auth = headers.get("authorization", "")
        authorized = auth.startswith("Bearer ") and "staff" in auth
        try:
            value = self.engine.vault.detokenize(token, reason or "", authorized=authorized)
        except PermissionError as exc:
            raise ApiError(C.E_VAULT_PERMISSION_DENIED, str(exc), status=403)
        except ValueError as exc:
            raise ApiError(C.E_VAULT_REASON_REQUIRED, str(exc))
        except KeyError as exc:
            raise ApiError(C.E_VAULT_TOKEN_UNKNOWN, "unknown token", status=404)
        return 200, {"value": value}

    def handle_policy_search(self, params, query, body, headers):
        q = query.get("q", "")
        hits = self.engine.kb.search(q, query.get("city"))
        return 200, {"query": q, "hits": [{"doc_id": d.id, "title": d.title,
                                           "version": d.version, "city": d.city,
                                           "score": s} for d, s in hits]}

    def handle_policy_answer(self, params, query, body, headers):
        q = query.get("q", "")
        ans = self.engine.kb.answer(q, query.get("city"))
        if not ans["found"]:
            return 200, {"found": False, "handoff": True, "reason": ans["reason"],
                         "reply": ans["reply"]}
        return 200, {"found": True, "handoff": False, "reply": ans["reply"],
                     "citation": ans["citation"]}

    def handle_list_stations(self, params, query, body, headers):
        rows = self.engine.stations.nearby(query.get("area_text"))
        return 200, {"stations": rows}

    def handle_list_slots(self, params, query, body, headers):
        sid = query.get("station_id", "")
        return 200, {"slots": self.engine.stations.slots(sid)}

    def handle_daily_report(self, params, query, body, headers):
        sessions = list(self.engine.sessions.values())
        done = [s for s in sessions if s.status == "complete"]
        minor = [s for s in sessions if s.status == "end_minor"]
        handoff = [s for s in sessions if s.status == "handoff"]
        return 200, {"generated_at": sessions[0].created_at if sessions else None,
                     "total_sessions": len(sessions), "completed": len(done),
                     "end_minor": len(minor), "handoff": len(handoff),
                     "model_stats": self.engine.model.stats()}

    def handle_eval_metrics(self, params, query, body, headers):
        path = self.store.eval_metrics_path() if self.store else None
        if not path:
            return 200, {"available": False}
        with open(path, encoding="utf-8") as fh:
            return 200, json.load(fh)

    def handle_healthz(self, params, query, body, headers):
        return 200, {"ok": True, "service": "rider-hiring-agent", "contract": "v1"}

    def handle_openapi(self, params, query, body, headers):
        paths = {}
        for m, p, h in C.ROUTES:
            spec = {"summary": h, "responses": {"200": {"description": "ok"}}}
            if "{" in p:
                pp = _path_params(p)
                spec["parameters"] = [{"name": x, "in": "path", "required": True,
                                       "schema": {"type": "string"}} for x in pp]
            paths.setdefault(p, {})[m.lower()] = spec
        return 200, {"openapi": "3.1.0", "info": {"title": "Rider Hiring Agent API",
                                                  "version": "1.0.0"},
                     "paths": paths,
                     "components": {"schemas": {"Error": {"type": "object", "required": C.ERROR_BODY_KEYS,
                                                           "properties": {"code": {"type": "string"},
                                                                         "message": {"type": "string"}}}}}}
