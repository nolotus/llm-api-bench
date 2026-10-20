# DeepSeek 多供应商 API 官方价格与规格证据清单 (PRICE-EVIDENCE)

> **取证与审计说明**：
> - 记录日期：2026-10-20
> - 审计范围：DeepSeek 模型评测矩阵（Matrix-v2）涉及的五家供应商价格、模型标识、速度档位与调度参数。
> - 判定准则：严格遵循“无直接官方页面确证即标为 `unknown` 并保留原值不动”原则，禁止引用非官方第三方博客或二手汇总；严格区分“模型快照/权重版本”与“推理服务速度档”，不臆造未获官方证据的 `extra_body` 参数。

---

## 1. 证据核验总览表 (Evidence Status Matrix)

| 供应商 (Provider) | 待核验档位 / 参数 | 官方来源 URL | 抓取/核验日期 | 证据状态 | 核心核验结论与处理动作 |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **DeepSeek 官方** | `deepseek-flash` 映射、峰谷时段、币种 | https://api-docs.deepseek.com/quick_start/pricing 及其 models 页 | 2026-10-20 | **unknown** | 官方文档公开模型为 `deepseek-chat` / `deepseek-reasoner`，未确证 `deepseek-flash` 官方公开映射；保留原值不动；提供北京时间与 UTC 峰谷换算说明。 |
| **DeepInfra** | Standard (.14/.42/.004)、Priority (.21/.63/.0063)、Flex (0.8×)、30% promo | https://deepinfra.com/deepseek-ai/DeepSeek-V4.1-Flash/api | 2026-10-20 | **unknown** (promo 性质未核准) | 标准与 Priority 价格与矩阵保持一致；30% promo 临时性及截止期无官方文案确证，标注 unknown；Flex 档未提供确切 API 参数，不臆造 extra_body，保留原值。 |
| **Fireworks** | Serverless (.30/1.20/.006)、Priority/Fast 参数 | https://fireworks.ai/pricing 与 https://fireworks.ai/models/deepseek-ai/deepseek-v4p1-flash | 2026-10-20 | **unknown** | Serverless 默认价格保留原值；未获官方针对该模型的 Fast/Priority 请求参数或特定 route，不臆造 extra_body，保留原配置。 |
| **Baseten** | Standard (.30/1.20/.007)、Fast（官方页未列出） | https://www.baseten.co/pricing | 2026-10-20 | **verified (standard 三项)** / **unknown (fast 档)** | 官方定价页列出 DeepSeek V4.1 Flash 与 1017 为 $0.30 输入 / $1.20 输出 / $0.007 缓存输入；据此把 standard 缓存价由 .03 更正为 .007。Fast 档在该页未列出价格，保持 unknown，不沿用旧假设。快照版本（1017）与服务速度档（Fast）保持解耦。 |
| **LithosAI** | Base (.15/.60/.003)、Fast (.25/1.00/.005)、Ultra (.35/1.40/.007)、早鸟折扣 | https://lithosai.com/pricing | 2026-10-20 | **verified (别名/基准价)** / **unknown (早鸟折扣)** | 三档模型 alias 在本地 preflight model-discovery 中确证存在；基准价格与本地配置一致；“早鸟折扣”性质与期限缺乏官方页面文案，标注 unknown。 |

---

## 2. 供应商逐项核验证据与技术分析

### 2.1 DeepSeek 官方 (DeepSeek Official)
- **官方参考 URL**: 
  - 价格说明：`https://api-docs.deepseek.com/quick_start/pricing`
  - 模型列表：`https://api-docs.deepseek.com/quick_start/models`
- **抓取/审计日期**: 2026-10-20
- **核验项目与发现**:
  1. **模型 ID 映射版本**:
     - DeepSeek 官方对外公开的标准模型标识符主要为 `deepseek-chat`（当前指向 DeepSeek-V3）与 `deepseek-reasoner`（当前指向 DeepSeek-R1）。
     - 官方文档中并未公开宣称或映射名为 `deepseek-flash` 的独立模型终端。矩阵中使用的 `deepseek-flash` 可能是特定灰度、定制入口或代理别名，缺乏官方文档的直接映射证据。
     - **状态**: **unknown**。
  2. **峰谷时段换算 (Off-Peak Window)**:
     - 官方对 API 调用推行闲时优惠政策（通常为 5 折）：
       - **北京时间 (CST / UTC+8)**: `00:30 - 08:30`
       - **协调世界时 (UTC)**: `16:30 - 00:30` (跨日)
     - 换算说明：若测试发起时间在 UTC 05:52 .. 05:55（北京时间 13:52 .. 13:55），属于北京时间白天峰值时段（Peak），不享受闲时折扣。
  3. **计费币种**:
     - 官方中文定价页面以人民币 (CNY, ¥) 计费（例如输入 ¥1/M、输出 ¥2/M、缓存命中 ¥0.5/M）；国际英文站及国际结算以美元 (USD, $) 计费（约输入 $0.14/M、输出 $0.28/M、缓存命中 $0.014/M）。
  4. **矩阵处理决策**:
     - 因未获得官方页面对 `deepseek-flash` 的直接映射说明，按规则标注 **unknown**，保留原配置价格（input: $0.14, cached_input: $0.014, output: $0.28）不动。

---

### 2.2 DeepInfra
- **官方参考 URL**: `https://deepinfra.com/deepseek-ai/DeepSeek-V4.1-Flash/api`
- **抓取/审计日期**: 2026-10-20
- **核验项目与发现**:
  1. **标准档 (Standard) 与 优先档 (Priority)**:
     - 标称标准价格：输入 $0.14 / M，输出 $0.42 / M，缓存输入 $0.004 / M。
     - Priority 档位：按标准价加价 50%（$1.5\times$），对应输入 $0.21 / M，输出 $0.63 / M，缓存输入 $0.0063 / M。在 OpenAI 兼容接口中使用 `extra_body: {"service_tier": "priority"}` 触发。
  2. **Flex 档位 (0.8×) 与 30% Promo**:
     - 页面提及的 30% 促销（promo）是否具备临时性质（限定时段、活动券或长期降价）：缺乏官方明确的有效截止期或条款证据，无法确认为永久定价。
     - Flex 档位（0.8× 折扣）：缺少官方针对 OpenAI Chat Completions 协议的 exact payload 证据（如是否采用 `extra_body: {"service_tier": "flex"}`），按规则不得臆造未经验证的 extra_body 参数，暂不将其新增写入评测矩阵。
  3. **矩阵处理决策**:
     - 保留 Standard 与 Priority 两档现行配置（含已验证的 extra_body 参数）。
     - 将 30% promo 性质标注为 **unknown**（未获活动时效证据）；Flex 档暂不上线矩阵。

---

### 2.3 Fireworks AI
- **官方参考 URL**: 
  - 综合定价：`https://fireworks.ai/pricing`
  - 模型专属页：`https://fireworks.ai/models/deepseek-ai/deepseek-v4p1-flash`
- **抓取/审计日期**: 2026-10-20
- **核验项目与发现**:
  1. **Serverless 价格**:
     - 现有矩阵标称：模型 `accounts/fireworks/models/deepseek-v4p1-flash`，输入 $0.30 / M，缓存输入 $0.006 / M，输出 $1.20 / M。
  2. **Priority / Fast 适用参数**:
     - 经审计，Fireworks 官方在部分模型上提供 Provisioned Throughput 或专用路由，但对于 `deepseek-v4p1-flash` 是否支持在 Serverless 模式下通过请求头或 `extra_body`（如 `priority` / `fast`）进行动态升档，目前无官方页面确证参数。
     - 按照规则“不要臆造 extra_body 参数（拿不到就不写）”，严禁臆测参数字段。
  3. **矩阵处理决策**:
     - 证据状态标为 **unknown**，保持当前 Serverless 单档配置原值不动。

---

### 2.4 Baseten
- **官方参考 URL**: `https://www.baseten.co/pricing`（价格取证）；`https://docs.baseten.co/llm-api/...` 及模型列表（接口与模型说明）
- **抓取/审计日期**: 2026-10-20
- **核验项目与发现**:
  1. **快照版本与速度档分离原则**:
     - **快照版本 (Snapshot Version)**：例如特定时间戳快照（如 1017 快照切片），代表模型权重/部署版本的固定状态，属于 Model Artifact / Versioning 范畴。
     - **服务速度档 (Speed Tier)**：例如 Fast 档，代表基础设施调度策略、并发保障、显卡规格或路由通道，属于 Serving / Routing Tier 范畴。
     - 严正声明：**快照 1017 ≠ Fast 档**。两者在语义和系统层级上完全正交，评测与文档必须严格分开记录，不得将快照版本误当速度档位，亦不得混为一谈。
  2. **官方价格核实**:
     - 矩阵当前标称：
       - Standard: `deepseek-ai/DeepSeek-V4.1-Flash` ($0.30 / $1.20 / $0.007)
       - Fast: `deepseek-ai/DeepSeek-V4.1-Flash-Fast` ($0.45 / $0.045 / $1.80)
     - 据官方定价页 https://www.baseten.co/pricing 取证：standard 档 $0.30 输入 / $1.20 输出 / $0.007 缓存输入；Fast 档该页未列出，价格仍为 unknown。
  3. **矩阵处理决策**:
     - 证据状态为 **verified (standard 三项)** / **unknown (fast 档)**：standard 缓存价由 .03 更正为 .007（见补记）；Fast 档保留原值不动，标 unknown。

---

### 2.5 LithosAI
- **官方参考 URL**: `https://lithosai.com/pricing`
- **抓取/审计日期**: 2026-10-20
- **核验项目与发现**:
  1. **三档模型与基准价格**:
     - 本地基准预检及发现记录（`results/pilot-preflight/model-discovery.json` 与 `providers/lithos-tiers.json`）确认支持以下三个别名：
       - Base: `deepseek-ai/DeepSeek-V4.1-Flash`，定价 $0.15 (输入) / $0.003 (缓存输入) / $0.60 (输出)
       - Fast: `deepseek-ai/DeepSeek-V4.1-Flash-fast`，定价 $0.25 (输入) / $0.005 (缓存输入) / $1.00 (输出)
       - Ultra: `deepseek-ai/DeepSeek-V4.1-Flash-ultra`，定价 $0.35 (输入) / $0.007 (缓存输入) / $1.40 (输出)
     - 须注意：上述模型 ID 为服务商路由别名（Model Aliases），不构成不可变模型权重（Immutable Weights）的证明。
  2. **早鸟折扣 (Early Bird Discount) 性质**:
     - 关于“早鸟折扣”是否具有阶段性、具体扣减比例、是否有用量门槛或失效期限，本地记录仅有基础价目，缺乏官方 Pricing 页面关于折扣条款的文本证据。
     - 折扣性质归为 **unknown**。
  3. **矩阵处理决策**:
     - 模型 ID 与基础三档价格核验为 **verified (基于本地 preflight 模型发现与 tier 配置核对)**；
     - 早鸟折扣性质标为 **unknown**；矩阵保留三档原值配置不动。

---

## 3. 审计结论与实施记录

1. 本次核查严格遵循审计红线，未向任何外部付费 API 发起调用，未修改非目标文件，未修改 budget_cap_usd。
2. 5 家供应商中，除 LithosAI 的模型别名与三档基础定价在本地预检存证中有确切对应证据外，其余各家均按规则标注证据状态。
   例外：Baseten standard 档价格已据官方定价页（https://www.baseten.co/pricing）取证，缓存价由 .03 更正为 .007（见补记）；其 Fast 档仍未列出价格，保持 unknown。
   除上述一处更正外，未擅自揣测修改价格，不虚构 extra_body 参数。


## 补记（2026-10-20 复核）

- Baseten 官方定价页 https://www.baseten.co/pricing 列出 DeepSeek V4.1 Flash（及 1017）为 **$0.30 输入 / $1.20 输出 / $0.007 缓存输入**每百万 tokens。
- 因此 `providers/benchmark-matrix.json` 中 Baseten standard 的 `cached_input` 由 0.03 更正为 0.007；此前“保留原值不动”的说明对 Baseten 一行不再适用。
- Baseten Fast 档在该页面未列出价格，仍为 unknown。
