# rider-hiring-agent — 骑手招聘 Agent 化信息收集平台 · 任务 1/5

**Agent 对话引擎与政策知识库**（ClawHunt #1808，共用接口契约 v1）。

一句话：求职者用自然语言完成 7 项报名；**个人信息在进模型之前就被换成占位符**；
政策回答**必带出处**、查不到就转人工；主模型挂了自动降级成表单模式，**报名不中断**。

---

## 一、一键复跑（三条命令，全部只用标准库）

```bash
# ① 单元测试（21 项）
bash scripts/run_tests.sh
# 期望末行： OK

# ② 评测：生成 340 条合成评测集 + 输出验收三指标（确定性，可复现）
bash scripts/run_eval.sh
# 期望末行：   结论           : PASS

# ③ 按契约用 curl 走一次完整报名（建会话 → 7 轮消息 → progress 7/7）
bash scripts/curl_demo.sh
# 期望末行：   "status": "complete"

# ④ 变异自证：故意改坏 6 道门禁，证明它们会红
python3 scripts/mutation_proof.py
# 期望末行：   结论: PASS（门禁会红，不是恒真断言）
```

**评测实测输出（2026-11-02）**

| 指标 | 实测 | 验收要求 |
|---|---|---|
| 字段抽取准确率 | **0.957** | ≥ 0.95 |
| 政策问答正确率 | **1.000** | ≥ 0.90 |
| 违规输出数 | **0** | = 0 |
| 未成年识别率 | 1.000 | — |
| 提示词注入忽略率 | 1.000 | 全部拦截/忽略（用例 20 条）|
| 个人信息泄漏率 | **0.000** | 原值不得出现在送模型的请求体 |
| 评测集规模 | 340 条（反例 132）| ≥ 300（反例 ≥ 30）|

---

## 二、docker compose 一键启动

```bash
docker compose up --build
# app        http://localhost:8077
# mock-model http://localhost:8099
curl -s http://localhost:8077/healthz
# {"ok":true,"service":"rider-hiring-agent","contract":"v1"}
```
技术栈按契约 v1：Python 3.12 + FastAPI + PostgreSQL 16(pgvector) + Redis 7.2。
依赖许可只有 MIT / Apache-2.0 / BSD / PostgreSQL（**刻意用 asyncpg(Apache-2.0) 而非 psycopg(LGPL)**）。

> **诚实说明**：本仓库的编写环境**无 Docker、PyPI 不可达**，因此
> **compose 路径（Postgres/pgvector/Redis/FastAPI 容器）未在本机实跑过**；
> 已在本机实跑并留证的是**同一份业务逻辑**的纯标准库路径（测试/评测/curl 演示/变异自证）。
> 契约要求的 curl 行为用标准库 dev server（同一份 `app/api.py` 路由与处理器）验证过。

---

## 三、契约 v1 对齐

| 契约项 | 本实现 |
|---|---|
| `POST /api/v1/agent/sessions` | ✅ → `{session_id}`（201）|
| `POST /api/v1/agent/sessions/{id}/messages` `{text}` | ✅ → `{reply, quick_replies[], progress{collected,total,missing}, candidate{...}, status}` |
| `POST /api/v1/vault/tokenize` `{type,value}` | ✅ → `{token}`（〔手机号_1〕形式）|
| `POST /api/v1/vault/detokenize` `{token,reason}` | ✅ 需权限（Bearer staff）+ 必填 reason + 写审计 |
| 错误体 `{code, message}` | ✅ 全路由统一（含 404/403）|
| candidate 字段 | ✅ 与契约**逐字段一致**（见 `app/contract.py::CANDIDATE_FIELDS`，契约测试比对）|
| candidate 枚举 | job_type / health_cert / status 均在契约枚举内 |
| OpenAPI 文档 | ✅ `GET /openapi.json`（FastAPI 另自动生成 `/docs`）|
| 事件 | `candidate.created/updated/completed`、`booking.created/cancelled`、`handoff.created` |
| 许可 | 只有 MIT / Apache-2.0 / BSD / PostgreSQL |

**任务 1 之外的接口全部按契约自己写 mock**（保险箱 / 站点查询 / 可约时段 / 转人工），
不依赖其它任务先完成。

---

## 四、目录结构

```
app/
  contract.py     契约 v1 的常量（字段、枚举、错误码、路由表、验收阈值）—— 测试直接比对它
  core.py         对话状态机 / 字段抽取 / 校验 / 护栏 / 脱敏 / 政策检索 / 模型适配 / 降级（纯标准库）
  api.py          路由表 + 处理器（FastAPI 层与 dev server 共用同一份）
  fastapi_app.py  FastAPI 适配层（薄壳，业务逻辑不重复实现）
  devserver.py    标准库 HTTP 服务器（无依赖，用于本机 curl 验证）
  mock_model.py   OpenAI 兼容 mock（落盘每次请求体 ⇒ 隐私断言的证据）
  pgindex.py      Postgres16 + pgvector 政策向量索引（可选路径，失败自动回退）
  store.py        会话/候选人持久化（默认 SQLite；设 DATABASE_URL 则走 Postgres）
  policy_seed.py  合成政策语料（真实政策中标后由发单方提供脱敏样例）
eval/
  generate_dataset.py   生成 340 条合成评测对话（反例 132、注入 20）
  run_eval.py           输出验收三指标 + 逐条明细
tests/test_all.py       21 项单元测试（标准库 unittest）
scripts/                run_tests.sh / run_eval.sh / curl_demo.sh / mutation_proof.py
docs/verification.md    验证记录（命令 / 输入 / 期望输出 / 实测）
```

---

## 五、七条护栏与降级

1. **脱敏前置**：手机号 / 身份证 / 银行卡 → `〔手机号_1〕`，**真实值只在服务端**（保险箱）。
2. **未成年终止**：识别到未满 18 ⇒ 返回 `end_minor`、**不再追问**。
3. **不承诺具体收入 / 不做歧视性表述 / 不索要非必要敏感信息**：输出违规数必须为 0。
4. **提示词注入**：识别到即**忽略**，不进入模型指令、回复不照做（20 条用例全拦）。
5. **政策必带出处**：文档名 + 版本；**查不到 ⇒ 转人工，不编造**。
6. **工具调用**：站点查询（按距离/剩余名额，mock 任务 3）/ 可约时段 / 转人工。
7. **模型降级**：主→备→**表单模式**（降级后仍能推进报名），并记录每次调用的 tokens 与耗时。

---

## 六、数据与合规

- 全部数据为**合成**（姓名/手机号/身份证/银行卡均为占位），**不含任何真实个人信息**；
- 对话中出现的敏感信息**先脱敏再送模型**，模型只看得到占位符；
- `detokenize` 需显式权限 + 必填理由，并写审计。

## 七、许可

代码 MIT；依赖见 `requirements.txt`（全部 MIT / Apache-2.0 / BSD），
PostgreSQL/pgvector 为 PostgreSQL License。
