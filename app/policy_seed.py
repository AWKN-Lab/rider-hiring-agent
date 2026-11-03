"""合成政策语料（真实政策中标后由发单方提供脱敏样例）。

每条都有出处（文档名 + 版本 + 城市），检索不到时**必须转人工，不许编造**。
"""
from __future__ import annotations

from .core import PolicyDoc


def seed_policies() -> list[PolicyDoc]:
    return [
        PolicyDoc(id="doc-bj-guarantee", city="BJ", version="v1", title="骑手配送保障政策（合成样例）",
                  text="骑手每月享有配送保障补贴，具体标准以站点公示为准，"
                       "遇到极端天气按公司通知执行。",
                  keywords=["保障", "补贴", "极端天气"]),
        PolicyDoc(id="doc-bj-settle", city="BJ", version="v1", title="骑手结算与报酬口径（合成样例）",
                  text="骑手报酬由配送单单价与阶梯奖励构成，结算周期为每月，"
                       "具体金额以当月公示的阶梯表为准。",
                  keywords=["结算", "报酬", "单价", "阶梯"]),
        PolicyDoc(id="doc-bj-rest", city="BJ", version="v1", title="骑手休息与申诉流程（合成样例）",
                  text="骑手可在线申请休息时段，申诉由站点主管在三个工作日内处理。",
                  keywords=["休息", "申诉", "主管"]),
        PolicyDoc(id="doc-bj-onboard", city="BJ", version="v2", title="骑手入职材料清单（合成样例）",
                  text="入职需要本人到场签署告知书并完成健康证登记，"
                       "身份证信息由平台在服务端保管，不需要在对话中提供。",
                  keywords=["入职", "材料", "身份证", "健康证", "到场"]),
        PolicyDoc(id="doc-bj-insurance", city="BJ", version="v1", title="骑手意外保险说明（合成样例）",
                  text="平台为在岗骑手提供意外保险，承保范围以保单条款为准。",
                  keywords=["保险", "意外", "保单"]),
        PolicyDoc(id="doc-all-privacy", city="ALL", version="v1", title="个人信息最小必要原则（合成样例）",
                  text="我们只收集完成报名所必需的信息；手机号在进入模型前会被替换成占位符，"
                       "身份证与银行卡信息不需要也不接受在对话中提供。",
                  keywords=["个人信息", "隐私", "手机号", "身份证", "银行卡", "占位符"]),
    ]
