# 验证记录（#1808 · 任务 1/5）

> 规则：**命令 + 输入 + 期望输出**三者都写清楚，复跑可得同样结论。
> 全部命令只用标准库；环境：Linux / Python 3.11.2（编写环境无 Docker、PyPI 不可达）。

## 1) 单元测试

```bash
bash scripts/run_tests.sh
```
期望末行：`OK`（21 项）
实测：`Ran 21 tests in 0.024s` → `OK`

覆盖：契约路由表 / 错误体形状 / candidate 字段逐项比对 / 7 项进度到 7/7 /
未成年终止且不再追问 / 转人工 / 隐私（手机号·身份证·银行卡原值不入模型）/
政策带出处与查不到转人工 / 护栏三类违规 / 注入忽略 / 模型超时降级表单模式且报名不中断 /
tokens 与耗时留痕 / 保险箱权限与审计 / 站点与时段。

## 2) 评测（验收三指标）

```bash
bash scripts/run_eval.sh
```
期望：
```
  字段抽取准确率 : 0.957  (要求 ≥0.95)
  政策问答正确率 : 1.000  (要求 ≥0.9)
  违规输出数     : 0  (要求 = 0)
  结论           : PASS
```
实测（2026-11-02，同上）—— 评测集 340 条（反例 132、注入 20），
指标文件 `data/eval_metrics.json`，逐条明细 `data/eval_details.jsonl`。
数据全部合成（`eval/generate_dataset.py`，固定随机种子 ⇒ 可复现）。

## 3) 契约 curl 演示

```bash
bash scripts/curl_demo.sh
```
期望：
```
  我叫小王 → progress 1 / 7
  ...
  跑过半年 → progress 7 / 7
  "status": "complete"
```
实测：7 轮后 `progress.collected=7 / total=7`，candidate 含契约全部字段，
`name_token` 为 `〔姓名_2〕`（占位符），送模型的请求体里**没有原始手机号/身份证**。

## 4) 变异自证

```bash
python3 scripts/mutation_proof.py
```
期望末行：`结论: PASS（门禁会红，不是恒真断言）`
实测：6 个变异全部**因正确原因**被抓住（未成年终止 / 脱敏 / 政策瞎编 / 注入拦截 / 护栏 / 抽取失准）。

## 5) 未在本机执行的部分（如实标注）

| 项 | 状态 | 原因 |
|---|---|---|
| `docker compose up` 全链路（Postgres16+pgvector / Redis7.2 / FastAPI 容器）| **未在本机执行** | 编写环境无 Docker、PyPI 不可达（`pip install fastapi` 连接被重置）|
| Postgres/pgvector 路径（`app/pgindex.py`）| **未在本机执行**（代码已写，任何异常自动回退进程内向量索引）| 同上；驱动选 asyncpg(Apache-2.0) 以满足契约许可约束 |
| FastAPI 层（`app/fastapi_app.py`）| **未在本机执行** | 同上（FastAPI 不可安装）；其路由与处理器复用 `app/api.py` 同一份实现，契约测试跑的就是它 |

已在本机实跑并留证的是**同一份业务逻辑**的纯标准库路径（测试 / 评测 / curl / 变异自证）。
