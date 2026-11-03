"""任务 1 的核心：对话编排 + 字段抽取 + 护栏 + 脱敏前置 + 政策检索 + 模型适配 + 降级。

设计原则（对齐 #1808 验收标准）：
* **纯标准库**：FastAPI / Postgres / Redis / 大模型都是**可插拔的外壳**，
  核心逻辑不依赖任何第三方包 ⇒ 单元测试与评测在干净机器上一条命令可跑。
* **脱敏在送模型之前**：手机号 / 身份证号先进保险箱换成占位符，模型只看到〔手机号_1〕。
* **决定权在规则**：字段抽取、政策命中、护栏判定都由确定性规则给出 ⇒ 指标可复现。
* **模型可降级**：主模型超时/不可用 ⇒ 自动切备用；备用也不可用 ⇒ 降级为表单模式，报名不中断。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import contract as C

# ══════════════════════════════════════════════════════════════════════
# 保险箱（任务 5 提供；这里用可插拔实现 + 默认 mock）
# ══════════════════════════════════════════════════════════════════════
class Vault:
    """tokenize：真实值 → 占位符；detokenize：占位符 → 真实值（需权限 + 写审计）。"""

    def __init__(self, allowed_types=("phone", "id_card", "bank_card", "name", "address")):
        self.allowed_types = tuple(allowed_types)
        self._store: dict[str, dict] = {}
        self._counters: dict[str, int] = {}
        self.audit: list[dict] = []

    @staticmethod
    def _label(t: str) -> str:
        return {"phone": "手机号", "id_card": "身份证号", "bank_card": "银行卡号",
                "name": "姓名", "address": "地址"}.get(t, t)

    def tokenize(self, kind: str, value: str) -> str:
        if kind not in self.allowed_types:
            raise ValueError(f"unsupported tokenize type: {kind}")
        self._counters[kind] = self._counters.get(kind, 0) + 1
        token = f"〔{self._label(kind)}_{self._counters[kind]}〕"
        self._store[token] = {"type": kind, "value": value}
        return token

    def detokenize(self, token: str, reason: str, authorized: bool = False) -> str:
        if not authorized:
            raise PermissionError(C.E_VAULT_PERMISSION_DENIED)
        if not reason:
            raise ValueError(C.E_VAULT_REASON_REQUIRED)
        rec = self._store.get(token)
        if not rec:
            raise KeyError(C.E_VAULT_TOKEN_UNKNOWN)
        self.audit.append({"token": token, "reason": reason, "ts": time.time()})
        return rec["value"]


# ══════════════════════════════════════════════════════════════════════
# 模型适配（OpenAI 兼容；主/备 + 超时 + tokens/耗时记录 + 请求体留痕）
# ══════════════════════════════════════════════════════════════════════
@dataclass
class ModelCall:
    model: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    degraded: bool = False
    error: str | None = None


class ModelClient:
    """主模型 + 备用模型；都不可用 ⇒ degraded=True（表单模式）。"""

    def __init__(self, primary_url: str | None = None, primary_model: str = "mock-chat",
                 backup_url: str | None = None, backup_model: str = "mock-chat-backup",
                 timeout: float = 5.0, transport=None):
        self.primary_url = primary_url
        self.primary_model = primary_model
        self.backup_url = backup_url or primary_url
        self.backup_model = backup_model
        self.timeout = timeout
        self.calls: list[ModelCall] = []
        # transport(text, model) -> {"content": str, "usage": {...}}；测试可注入
        self.transport: Callable[[str, str], dict] = transport or self._http

    def _http(self, text: str, model: str) -> dict:
        url = self.primary_url if model == self.primary_model else self.backup_url
        if not url:
            raise RuntimeError("no model endpoint configured")
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": text}],
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": "rider-hiring-agent/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        usage = data.get("usage") or {}
        return {"content": data["choices"][0]["message"]["content"],
                "usage": {"prompt_tokens": usage.get("prompt_tokens", 0),
                          "completion_tokens": usage.get("completion_tokens", 0)}}

    def chat(self, text: str) -> tuple[str, ModelCall]:
        """返回 (回复文本, 调用记录)。两个模型都失败 ⇒ 回复空串 + degraded=True。"""
        for url, model in ((self.primary_url, self.primary_model),
                           (self.backup_url, self.backup_model)):
            if not url:
                continue
            t0 = time.time()
            try:
                out = self.transport(text, model)
                call = ModelCall(model=model,
                                 latency_ms=int((time.time() - t0) * 1000),
                                 prompt_tokens=out.get("usage", {}).get("prompt_tokens", 0),
                                 completion_tokens=out.get("usage", {}).get("completion_tokens", 0))
                self.calls.append(call)
                return out.get("content", ""), call
            except Exception as exc:  # 超时 / 连接失败 / 5xx
                self.calls.append(ModelCall(model=model,
                                            latency_ms=int((time.time() - t0) * 1000),
                                            error=f"{type(exc).__name__}: {exc}"))
        degraded = ModelCall(model="none", latency_ms=0, degraded=True,
                             error="all models unavailable")
        self.calls.append(degraded)
        return "", degraded

    def stats(self) -> dict:
        return {
            "calls": len(self.calls),
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "completion_tokens": sum(c.completion_tokens for c in self.calls),
            "total_latency_ms": sum(c.latency_ms for c in self.calls),
            "degraded": any(c.degraded for c in self.calls),
        }


# ══════════════════════════════════════════════════════════════════════
# 政策知识库（关键词 + 向量混合检索；每条回答带出处；查不到 ⇒ 转人工）
# ══════════════════════════════════════════════════════════════════════
@dataclass
class PolicyDoc:
    id: str
    city: str
    version: str
    title: str
    text: str
    keywords: list[str] = field(default_factory=list)

    def citation(self) -> dict:
        return {"doc_id": self.id, "title": self.title,
                "version": self.version, "city": self.city}


class PolicyKB:
    def __init__(self, docs: list[PolicyDoc] | None = None):
        self.docs = docs or []
        self._vectors = {d.id: self._embed(d.text + " " + " ".join(d.keywords)) for d in self.docs}
        self._dense = {d.id: self._embed_dense(d.text + " " + " ".join(d.keywords)) for d in self.docs}

    DENSE_DIM = 256

    @staticmethod
    def _embed(text: str) -> dict[str, float]:
        """稀疏词袋向量（纯标准库，用于关键词侧）。"""
        vec: dict[str, float] = {}
        for token in re.findall(r"[一-鿿A-Za-z0-9]+", text.lower()):
            vec[token] = vec.get(token, 0.0) + 1.0
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    @staticmethod
    def _embed_dense(text: str) -> list[float]:
        """256 维稠密哈希向量 —— pgvector 的 vector(256) 可直接存这个。

        公式与稀疏侧一致：混合分 = 0.65 * 关键词命中 + 0.35 * 余弦。
        """
        dim = PolicyKB.DENSE_DIM
        vec = [0.0] * dim
        for token in re.findall(r"[一-鿿A-Za-z0-9]+", text.lower()):
            h = hashlib.sha1(token.encode("utf-8")).digest()
            vec[h[0] % dim] += 1.0
            vec[h[1] % dim] += 0.5
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(k, 0.0) for k, v in a.items())

    def _keyword_score(self, query: str, doc: PolicyDoc) -> float:
        q = query.lower()
        hits = sum(1 for kw in doc.keywords if kw.lower() in q)
        for token in re.findall(r"[一-鿿]{2,}", query):
            if token in doc.text:
                hits += 1
        return hits

    def search(self, query: str, city: str | None = None, top_k: int = 3) -> list[tuple[PolicyDoc, float]]:
        scored: list[tuple[PolicyDoc, float]] = []
        for doc in self.docs:
            if city and doc.city != city and doc.city != "ALL":
                continue
            kw = self._keyword_score(query, doc)
            vec = self._cosine(self._embed(query), self._vectors[doc.id])
            score = 0.65 * kw + 0.35 * vec
            if score > 0:
                scored.append((doc, round(score, 4)))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def answer(self, query: str, city: str | None = None) -> dict:
        hits = self.search(query, city)
        if not hits:
            return {"found": False, "handoff": True,
                    "reason": C.E_POLICY_NOT_FOUND,
                    "reply": "这个问题我暂时没有查到有出处的政策条目，"
                             "已经为你转接人工同事，会有人继续跟进。"}
        doc, score = hits[0]
        return {"found": True, "handoff": False, "score": score,
                "doc": doc, "citation": doc.citation(),
                "reply": f"{doc.text}\n\n—— 出处：{doc.title}（版本 {doc.version}）"}


# ══════════════════════════════════════════════════════════════════════
# 工具（任务 3 的接口用 mock；可约时段；转人工）
# ══════════════════════════════════════════════════════════════════════
class Stations:
    def __init__(self, stations=None):
        self.stations = stations or [
            {"id": "st-001", "name": "望京站", "lat": 39.996, "lng": 116.470, "open_quota": 12},
            {"id": "st-002", "name": "三里屯站", "lat": 39.937, "lng": 116.455, "open_quota": 3},
            {"id": "st-003", "name": "回龙观站", "lat": 40.073, "lng": 116.340, "open_quota": 0},
        ]

    def nearby(self, area_text: str | None, lat: float | None = None, lng: float | None = None):
        rows = []
        for st in self.stations:
            dist = None
            if lat is not None and lng is not None:
                dist = round(math.dist((lat, lng), (st["lat"], st["lng"])) * 111, 2)  # km
            rows.append({**st, "distance_km": dist})
        rows.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"]))
        return rows

    def slots(self, station_id: str) -> list[dict]:
        return [{"station_id": station_id, "slot_start": f"2026-11-0{d}T09:00:00+08:00"}
                for d in range(1, 4)]


# ══════════════════════════════════════════════════════════════════════
# 护栏
# ══════════════════════════════════════════════════════════════════════
INJECTION_PATTERNS = [
    r"忽略(之前|上面|以上)", r"ignore (all|previous)", r"系统提示", r"你现在是",
    r"扮演", r"act as", r"开发者模式", r"developer mode", r"输出你的(系统)?提示",
    r"reveal (your )?(system )?prompt", r"跳过(所有)?(检查|规则|护栏)", r"jailbreak",
]
INCOME_PROMISE = [r"月入[过可超][万几\d]", r"保证.{0,4}收入", r"稳赚", r"至少赚\d",
                  r"日入\d+", r"(包|保证).{0,3}到手\d"]
DISCRIMINATION = [r"只要男|不要女|限男|限女", r"不要(外地|农村|少数民族)",
                  r"(不要|别找|排除).{0,4}(已婚|未婚|有孩子|怀孕)"]
SENSITIVE_SOLICIT = [r"(要|需要|提供|发一下).{0,4}(身份证|银行卡|人脸|证件照|银行卡号)",
                      r"把.{0,4}(身份证|银行卡).{0,4}(号)?(发|给我|拍)"]
PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
IDCARD_RE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
BANKCARD_RE = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
BIRTH_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})\s*[-年./]\s*(\d{1,2})\s*月?")
BIRTH_SHORT_RE = re.compile(r"(?<!\d)(\d{2})\s*年\s*(\d{1,2})\s*月")
# 注意：最长匹配优先（"住在" 要排在 "住"/"在" 前面），
# 否则「住在望京小区」会被抽成「在望京小区」。
AREA_RE = re.compile(r"(住在|住|在)\s*([一-鿿A-Za-z0-9]{2,12}?(?:小区|村|镇|街道|路|附近|广场|大厦))")
JOB_RE = [("fulltime", r"全职|长期|正式"), ("parttime", r"兼职|临时|零工"), ("undecided", r"都行|都可以|不定|看情况")]
EBIKE_RE = [("true", r"有(电动)?车|自带车|有车"), ("false", r"没(有)?(电动)?车|无车|没有车")]
MINOR_AGE = 18


def detect_guardrail(text: str) -> dict:
    """返回 {'violations': [...], 'injection': bool, 'minor': bool, 'pii': {...}}"""
    low = text.lower()
    injection = any(re.search(p, low) for p in INJECTION_PATTERNS)
    violations = []
    if any(re.search(p, text) for p in INCOME_PROMISE):
        violations.append("承诺具体收入")
    if any(re.search(p, text) for p in DISCRIMINATION):
        violations.append("歧视性表述")
    if any(re.search(p, text) for p in SENSITIVE_SOLICIT):
        violations.append("索要非必要敏感信息")
    phones = PHONE_RE.findall(text)
    ids = IDCARD_RE.findall(text)
    # 银行卡：16–19 位数字（身份证已在上面先匹配掉了）
    cards = [c for c in BANKCARD_RE.findall(text) if c not in ids]
    return {"violations": violations, "injection": injection,
            "phones": phones, "id_cards": ids, "bank_cards": cards}


# ══════════════════════════════════════════════════════════════════════
# 对话引擎
# ══════════════════════════════════════════════════════════════════════
QUICK = {
    "name_token": ["小王", "李师傅", "叫我老张"],
    "birth_ym": ["1995年3月", "1998-07", "2001年11月"],
    "area_text": ["望京附近", "回龙观小区", "三里屯"],
    "job_type": ["全职", "兼职", "都可以"],
    "has_ebike": ["有电动车", "没有车", "暂时没有"],
    "start_text": ["明天就能到", "下周一", "随时"],
    "experience_text": ["跑过半年", "第一次跑", "做过一年"],
}


@dataclass
class Session:
    id: str
    created_at: float
    turns: list[dict] = field(default_factory=list)
    candidate: dict = field(default_factory=dict)
    slot_index: int = 0
    status: str = "collecting"      # collecting|complete|end_minor|handoff
    pending_confirm: dict | None = None
    handoff_reason: str | None = None
    model_calls: list[dict] = field(default_factory=list)


class ConversationEngine:
    def __init__(self, vault: Vault, model: ModelClient, kb: PolicyKB,
                 stations: Stations, city: str = "BJ"):
        self.vault = vault
        self.model = model
        self.kb = kb
        self.stations = stations
        self.city = city
        self.sessions: dict[str, Session] = {}
        # 送模型前的文本留痕（隐私用例断言"原值没出现"用）
        self.sent_texts: list[str] = []

    # ── 会话 ──────────────────────────────────────────────────────────
    def create_session(self) -> Session:
        sid = str(uuid.uuid4())
        s = Session(id=sid, created_at=time.time())
        s.candidate = {k: None for k in C.SLOT_KEYS}
        s.candidate.update({
            "id": sid, "status": "collecting", "source_channel": "agent_chat",
            "health_cert": "unknown",
            "consent_version": "v1", "consent_at": None, "retention_until": None,
            "station_id": None, "created_at": s.created_at, "updated_at": s.created_at,
        })
        self.sessions[sid] = s
        return s

    # ── 字段抽取 ──────────────────────────────────────────────────────
    def extract(self, text: str, sess: Session) -> dict:
        """从口语输入里抽结构化值；只填还没填的槽位。"""
        out: dict[str, Any] = {}
        g = detect_guardrail(text)

        m = BIRTH_RE.search(text) or BIRTH_SHORT_RE.search(text)
        if m:
            year = int(m.group(1)); month = int(m.group(2))
            if year < 100:
                year += 1900 if year >= 30 else 2000
            if 1 <= month <= 12:
                out["birth_ym"] = f"{year:04d}-{month:02d}"

        m = AREA_RE.search(text)
        if m:
            out["area_text"] = m.group(2)

        for key, pat in JOB_RE:
            if re.search(pat, text):
                out["job_type"] = key
                break
        for key, pat in EBIKE_RE:
            if re.search(pat, text):
                out["has_ebike"] = (key == "true")
                break
        if re.search(r"跑过|做过|有经验|经验", text):
            out["experience_text"] = text.strip()[:40]
        if re.search(r"明天|后天|下周|随时|今天|周[一二三四五六日天]", text):
            out["start_text"] = text.strip()[:40]
        if re.search(r"叫我|我叫|我是|姓", text):
            name = re.search(r"叫我([一-鿿]{1,4})", text) or \
                   re.search(r"我叫([一-鿿]{1,4})", text)
            if name:
                out["name_token"] = self.vault.tokenize("name", name.group(1))
        if g["phones"]:
            out["phone_token"] = self.vault.tokenize("phone", g["phones"][0])
        return out

    # ── 主流程 ────────────────────────────────────────────────────────
    def handle_message(self, session_id: str, text: str) -> dict:
        sess = self.sessions.get(session_id)
        if not sess:
            return {"error": {"code": C.E_UNKNOWN_SESSION, "message": "session not found"}}
        if sess.status in ("end_minor", "handoff"):
            return self._terminal_reply(sess, text)

        g = detect_guardrail(text)

        # 1) 未成年识别 ⇒ 立即终止
        born = self.extract(text, sess).get("birth_ym") or sess.candidate.get("birth_ym")
        if born:
            y, mth = born.split("-")
            now = time.localtime()
            age = now.tm_year - int(y) - (1 if now.tm_mon > int(mth) else 0)
            if age < MINOR_AGE:
                sess.candidate["birth_ym"] = born
                sess.status = "end_minor"
                sess.turns.append({"text": text, "reply": "end_minor", "ts": time.time()})
                return {"reply": "抱歉，未满 18 周岁我们暂时不能安排报名。"
                                  "祝您一切顺利！", "quick_replies": [],
                        "status": "end_minor", "end_minor": True,
                        "candidate": self._public_candidate(sess),
                        "model_calls": sess.model_calls[-3:]}

        # 2) 提示词注入 ⇒ 忽略（不执行、不进入模型指令）
        if g["injection"]:
            sess.turns.append({"text": text, "reply": "ignored-injection", "ts": time.time()})
            reply = ("这条消息里有些内容我没法照做。我还是按原流程帮你完成登记："
                     f"{self._next_prompt(sess)}")
            return {"reply": reply, "quick_replies": self._quick_for(sess),
                    "status": sess.status, "candidate": self._public_candidate(sess),
                    "ignored_injection": True, "model_calls": sess.model_calls[-3:]}

        # 3) 政策问题
        if self._is_policy_question(text):
            ans = self.kb.answer(text, self.city)
            if not ans["found"]:
                sess.status = "handoff"
                sess.handoff_reason = ans["reason"]
                sess.turns.append({"text": text, "reply": ans["reply"], "ts": time.time()})
                return {"reply": ans["reply"], "quick_replies": [],
                        "status": "handoff", "handoff": True,
                        "candidate": self._public_candidate(sess)}
            sess.turns.append({"text": text, "reply": ans["reply"], "ts": time.time()})
            return {"reply": ans["reply"], "quick_replies": [],
                    "citation": ans["citation"], "status": sess.status,
                    "candidate": self._public_candidate(sess)}

        # 4) 抽取 + 填槽
        fields = self.extract(text, sess)
        for k, v in fields.items():
            if sess.candidate.get(k) in (None, ""):
                sess.candidate[k] = v
        sess.candidate["updated_at"] = time.time()

        # 5) 转人工（用户明确要求）
        if re.search(r"转人工|人工|客服|真人", text):
            sess.status = "handoff"
            sess.handoff_reason = "user_requested"
            sess.turns.append({"text": text, "reply": "handoff", "ts": time.time()})
            return {"reply": "好的，已经为你转接人工同事。", "quick_replies": [],
                    "status": "handoff", "handoff": True,
                    "candidate": self._public_candidate(sess)}

        # 6) 生成回复（先脱敏再送模型）
        safe_text = self._scrub(text)
        prompt_text = self._prompt_for(sess, safe_text)
        self.sent_texts.append(prompt_text)
        reply, call = self.model.chat(prompt_text)
        sess.model_calls.append({"model": call.model, "latency_ms": call.latency_ms,
                                 "prompt_tokens": call.prompt_tokens,
                                 "completion_tokens": call.completion_tokens,
                                 "degraded": call.degraded, "error": call.error})

        if call.degraded:
            # 降级：表单模式，报名不中断
            reply = self._form_reply(sess)
        else:
            reply = reply or self._next_prompt(sess)

        # 7) 是否收齐
        missing = [k for k in C.SLOT_KEYS if sess.candidate.get(k) in (None, "")]
        if not missing:
            sess.status = "complete"
            sess.candidate["status"] = "complete"
            reply = self._confirm_reply(sess)
        else:
            reply = reply if not self._is_policy_question(text) else reply

        sess.turns.append({"text": text, "reply": reply, "ts": time.time()})
        return {"reply": reply, "quick_replies": self._quick_for(sess),
                "progress": {"collected": len(C.SLOT_KEYS) - len(missing),
                             "total": len(C.SLOT_KEYS),
                             "missing": [C.SLOT_LABELS[m] for m in missing]},
                "status": sess.status, "candidate": self._public_candidate(sess),
                "model_calls": sess.model_calls[-3:]}

    # ── 辅助 ──────────────────────────────────────────────────────────
    def _scrub(self, text: str) -> str:
        """送模型前的脱敏：手机号 / 身份证 → 占位符（真实值只在服务端）。"""
        out = text
        for phone in detect_guardrail(text)["phones"]:
            out = out.replace(phone, self.vault.tokenize("phone", phone))
        for idc in detect_guardrail(text)["id_cards"]:
            out = out.replace(idc, self.vault.tokenize("id_card", idc))
        for card in detect_guardrail(text)["bank_cards"]:
            out = out.replace(card, self.vault.tokenize("bank_card", card))
        return out

    @staticmethod
    def _is_policy_question(text: str) -> bool:
        return bool(re.search(r"政策|规定|补贴|保险|结算|罚款|休息|派单|报酬|保障|社保", text))

    def _next_prompt(self, sess: Session) -> str:
        for k in C.SLOT_KEYS:
            if sess.candidate.get(k) in (None, ""):
                return f"方便告诉我你的{C.SLOT_LABELS[k]}吗？"
        return "信息已经收集齐了，我复述一下确认一下。"

    def _quick_for(self, sess: Session) -> list[str]:
        for k in C.SLOT_KEYS:
            if sess.candidate.get(k) in (None, ""):
                return QUICK.get(k, [])
        return []

    def _form_reply(self, sess: Session) -> str:
        """表单模式（模型不可用时的降级路径）：照样推进采集，不中断报名。"""
        return f"（已切换到表单模式）{self._next_prompt(sess)}"

    def _confirm_reply(self, sess: Session) -> str:
        c = sess.candidate
        return ("我复述一下，确认对不对："
                f"称呼 {c.get('name_token')}，出生年月 {c.get('birth_ym')}，"
                f"意向区域 {c.get('area_text')}，岗位意向 {c.get('job_type')}，"
                f"车辆 {'有' if c.get('has_ebike') else '无'}，"
                f"到岗时间 {c.get('start_text')}，配送经验 {c.get('experience_text')}。"
                "有不对的地方告诉我，我改。")

    def _prompt_for(self, sess: Session, text: str) -> str:
        return (f"[任务1 骑手招聘助手] 已收集：{ {k: sess.candidate.get(k) for k in C.SLOT_KEYS} }。"
                f"用户说：{text}")

    def _terminal_reply(self, sess: Session, text: str) -> dict:
        msg = ("这次登记已经结束了。" if sess.status == "end_minor"
               else "已经为你转接人工同事，会有人继续跟进。")
        return {"reply": msg, "quick_replies": [], "status": sess.status,
                "candidate": self._public_candidate(sess),
                "model_calls": sess.model_calls[-3:]}

    def _public_candidate(self, sess: Session) -> dict:
        return {k: sess.candidate.get(k) for k in C.CANDIDATE_FIELDS}
