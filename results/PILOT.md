# Pilot 阶段事实核对与运行审计报告（修订版）

## 1. 运行边界与样本说明

- **定位与性质**：本报告仅对 Pilot 阶段既有数据进行事实核验（Fact Check），**严禁将 Pilot 结论等同于正式评测（Formal Benchmark）**。
- **母样本总数（Mother Sample）**：共计 **23** 条请求记录。
  - **修正有序请求（Ordered）**：**22** 条（`pilot-ordered-1522e75-...`）。
  - **旧乱序探测请求（Legacy Disordered）**：**1** 条（`pilot-preflight-fixed-20260603-4000-g00000-long-r01`）。
- **独立 Prefix Group 精确计数**：
  - **识别规则**：必须按完整 `group_id` 计数，相同的 `g00000` 后缀绝非相同 group_id，不同前缀代表不同独立组。
  - **Ordered 集合包含 6 个独立 prefix group**：
    - Long 请求：每 target size 各 1 个独立 prefix group，共 **4** 个（`pilot-ordered-1522e75-1000-g00000`、`...-4000-...`、`...-16000-...`、`...-32000-...`）。
    - Throughput 请求：**2** 个独立 prefix group（`pilot-ordered-1522e75-throughput-00000`、`pilot-ordered-1522e75-throughput-00001`）。
  - **全局母样本包含 7 个独立 prefix group**（Ordered 的 6 个 + Legacy preflight 的 1 个 `pilot-preflight-fixed-20260603-4000-g00000`）。
- **样本稳健性与普遍性边界**：
  - 尽管存在 4 个 long prefix groups，但每个 target size 仅有 1 个独立组（`groups_per_size = 1`），且组内仅 5 次重复（throughput 仅 1 次）。
  - **样本量严重受限，不具备跨组统计稳健性，绝不能声称或推断为普遍/稳定规律**。

## 2. 计划排序机制与证据留存

- **排序机制澄清**：系统规范设计为“**随机组间排列，组内 repeat_index 严格递增**”。修正计划（`pilot-ordered-1522e75`）中所见到的 target size 递增（1000 -> 4000 -> 16000 -> 32000）**仅为该 seed（1522e75）随机 shuffle 的碰巧结果**，不属于规范要求的目标递增。
- **旧计划乱序缺陷留存**：`results/pilot-preflight/plan/manifest.json` 与 `tasks.jsonl` 在生成时把组内 repeat 打乱（例如 4000-r01 早于 4000-r04 早于 1000-r04）。该文件完整留存作为比对证据，未做任何删除。
- **修正计划执行**：`results/pilot-ordered/plan/manifest.json` 保证了组内 repeat_index 严格单调递增（`r00` -> `r04`）。

## 3. 四档实际 Prompt 亲查（Raw 证据对账与纠偏）

穿透底层原始 records 与 final_usage 进行逐条亲查，纠正此前摘要或口述偏差：

| 目标档位 | 类型 | 请求数 | 独立 Group 数 | 实际 Prompt Tokens | Completion Tokens | 组内 Repeat 顺序 | 事实对账说明 |
|---|---|---|---|---|---|---|---|
| 1000 | long | 5 | 1 | 1044（均为 1044） | 32 | r00, r01, r02, r03, r04 | 修正有序组（prefix: `...-1000-g00000`） |
| 1000 | throughput | 2 | 2 | 1041, 1055 | 512 | r00, r00 | 2 个独立 prefix throughput 组 |
| 4000 | long (旧) | 1 | 1 | **2481** | 32 | r01 | 历史误报纠偏：实际仅 2481（非 4000） |
| 4000 | long (新) | 5 | 1 | **4027**（均为 4027） | 32 | r00, r01, r02, r03, r04 | **纠偏：实查 raw 为 4027（非父此前口述 4029）** |
| 16000 | long | 5 | 1 | 16030（均为 16030） | 32 | r00, r01, r02, r03, r04 | 修正有序组（prefix: `...-16000-g00000`） |
| 32000 | long | 5 | 1 | 31966（均为 31966） | 32 | r00, r01, r02, r03, r04 | 修正有序组（prefix: `...-32000-g00000`） |

> **Raw 事实核准**：4000 档 ordered 请求底层 raw 记录均为 **4027** tokens，以此事实为唯一准绳，明确纠正口述 4029。

## 4. 缓存观测与字段缺失分析

- **字段核验口径**：
  - 响应包含 `usage.prompt_tokens_details.cached_tokens` 且非空者，视为“**观测到返回 cached_tokens**”。
  - 响应中该字段为 `null` 或缺失者，**严格标注为 unknown（未知）**。**严禁断言为“未命中缓存”，更严禁声称“缓存未知=0”**。
- **统计指标**：
  - **缺失 Cache 字段（Unknown）**：8 / 23（**34.78%**）。包含 throughput 2 次探测、ordered 组内各档首次（1000-r00/r01、4000-r00、16000-r00、32000-r00）及旧乱序请求。
  - **观测到返回 cached_tokens**：15 / 23（**65.22%**）。
- **组内观测表现（不可称稳定）**：
  - 1000 long (`...-1000-g00000`): r00, r01 为 unknown；r02~r04 观测到返回 768 tokens。
  - 4000 long (`...-4000-g00000`): r00 为 unknown；r01~r04 观测到返回 3840 tokens。
  - 16000 long (`...-16000-g00000`): r00 为 unknown；r01~r04 观测到返回 15872 tokens。
  - 32000 long (`...-32000-g00000`): r00 为 unknown；r01~r04 观测到返回 31744 tokens。
  - throughput: 2 条均为 unknown。
  - **严正声明**：仅凭组内 4 次重复绝不能推断为“稳定命中”，仅能表述为“该组在此 4 次重复中观测到返回对应数值”。

## 5. 输出 Cap 与 Reasoning 计量

- **输出截断**：所有 23 条请求的 `finish_reason` 均为 `"length"`。
  - Long 模式 21 条请求均达到预设上限 32 tokens。
  - Throughput 模式 2 条请求均达到预设上限 512 tokens。
- **Reasoning 计量状态**：
  - 响应 usage 中的 `reasoning_tokens` 均为 0（或 null）。
  - SSE 事件流中未发现 `reasoning_content` 内容块（均为 null）。
  - **未决事实保留**：当前阶段**无法实测验证** reasoning tokens 是否占用 `max_tokens` cap。

## 6. 首正文延迟分布（First Content Latency）

客户端接收到首个有效正文字块耗时（`first_content_ms`）：

- **样本量 $n$**：23
- **最小值 (Min)**：888.18 ms
- **最大值 (Max)**：2550.15 ms
- **均值 (Mean)**：1518.47 ms
- **中位数 (Median)**：1426.22 ms
- **分位数规范**：**因母样本仅 $n=23$（ordered 仅 22），样本过小明确不报告 p95 分位数**。

## 7. 费用与记账核算（本地保守核算结算额）

- **本地保守核算结算额（Local Conservative Journal Settled）**：`$0.010909584`（基于 Decimal 无损累加）。
- **Unknown Holds / 未结算保留**：**0**（23 条记录全部对应完成结算）。
- **预留上界总额（Reserved Upper Bound）**：`$0.27846885`。
- **计费口径严正提示**：
  - 此项支出为**本地账面保守核算结算额**，而非供应商出具的实际扣费账单。
  - **当 Cache 字段缺失（unknown）时，系统本地保守按全额输入价格上界核算，不可声称“缓存未知=0”，亦不能代表供应商实际计费**。

## 8. Transport 与回调审计

- **Audit Callback 开销**：`transport.audit_callback_ms` 记录本地事件同步持久化耗时，Min: 10.39 ms, Max: 157.46 ms, Mean: 26.15 ms。
- **同 Chunk 时间限制**：网络读取与事件回调共用 `cooperative_network_and_callback` 截止时间，本地回调阻塞会挤占同 chunk 的网络时间窗口。
- **连接机制**：每请求独立握手全新的 TCP/TLS 连接（Fresh Connection），无 Keepalive 连接复用。
- **公网物理区域**：针对目标 `api.lithosai.cloud` 未做公网路由和机房位置验证，地理区域严格标为 **unknown**。

## 9. 母样本 23 条全量明细对账表

| # | Request ID | 完整 Group ID | 目标 | 类型 | Rep | Prompt | Compl | Cached | 记账金额 (USD) | 首正文 (ms) | Callback (ms) | Finish |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `pilot-preflight-fixed-20260603-4000-g00000-long-r01` | `pilot-preflight-fixed-20260603-4000-g00000` | 4000 | long | 1 | 2481 | 32 | unknown | 0.00039135 | 1327.942 | 10.89 | length |
| 1 | `pilot-ordered-1522e75-1000-g00000-long-r00` | `pilot-ordered-1522e75-1000-g00000` | 1000 | long | 0 | 1044 | 32 | unknown | 0.0001758 | 1426.225 | 12.877 | length |
| 2 | `pilot-ordered-1522e75-1000-g00000-long-r01` | `pilot-ordered-1522e75-1000-g00000` | 1000 | long | 1 | 1044 | 32 | unknown | 0.0001758 | 1088.675 | 11.089 | length |
| 3 | `pilot-ordered-1522e75-1000-g00000-long-r02` | `pilot-ordered-1522e75-1000-g00000` | 1000 | long | 2 | 1044 | 32 | 768 | 0.000062904 | 1403.572 | 10.389 | length |
| 4 | `pilot-ordered-1522e75-1000-g00000-long-r03` | `pilot-ordered-1522e75-1000-g00000` | 1000 | long | 3 | 1044 | 32 | 768 | 0.000062904 | 888.179 | 13.133 | length |
| 5 | `pilot-ordered-1522e75-1000-g00000-long-r04` | `pilot-ordered-1522e75-1000-g00000` | 1000 | long | 4 | 1044 | 32 | 768 | 0.000062904 | 974.196 | 18.765 | length |
| 6 | `pilot-ordered-1522e75-4000-g00000-long-r00` | `pilot-ordered-1522e75-4000-g00000` | 4000 | long | 0 | 4027 | 32 | unknown | 0.00062325 | 1489.821 | 13.81 | length |
| 7 | `pilot-ordered-1522e75-4000-g00000-long-r01` | `pilot-ordered-1522e75-4000-g00000` | 4000 | long | 1 | 4027 | 32 | 3840 | 0.00005877 | 1212.082 | 14.077 | length |
| 8 | `pilot-ordered-1522e75-4000-g00000-long-r02` | `pilot-ordered-1522e75-4000-g00000` | 4000 | long | 2 | 4027 | 32 | 3840 | 0.00005877 | 1045.466 | 13.439 | length |
| 9 | `pilot-ordered-1522e75-4000-g00000-long-r03` | `pilot-ordered-1522e75-4000-g00000` | 4000 | long | 3 | 4027 | 32 | 3840 | 0.00005877 | 1321.779 | 12.243 | length |
| 10 | `pilot-ordered-1522e75-4000-g00000-long-r04` | `pilot-ordered-1522e75-4000-g00000` | 4000 | long | 4 | 4027 | 32 | 3840 | 0.00005877 | 1615.538 | 12.822 | length |
| 11 | `pilot-ordered-1522e75-throughput-00001-throughput-r00` | `pilot-ordered-1522e75-throughput-00001` | 1000 | throughput | 0 | 1041 | 512 | unknown | 0.00046335 | 1144.144 | 156.406 | length |
| 12 | `pilot-ordered-1522e75-16000-g00000-long-r00` | `pilot-ordered-1522e75-16000-g00000` | 16000 | long | 0 | 16030 | 32 | unknown | 0.0024237 | 2540.367 | 12.337 | length |
| 13 | `pilot-ordered-1522e75-16000-g00000-long-r01` | `pilot-ordered-1522e75-16000-g00000` | 16000 | long | 1 | 16030 | 32 | 15872 | 0.000090516 | 1712.703 | 17.321 | length |
| 14 | `pilot-ordered-1522e75-16000-g00000-long-r02` | `pilot-ordered-1522e75-16000-g00000` | 16000 | long | 2 | 16030 | 32 | 15872 | 0.000090516 | 1270.531 | 14.01 | length |
| 15 | `pilot-ordered-1522e75-16000-g00000-long-r03` | `pilot-ordered-1522e75-16000-g00000` | 16000 | long | 3 | 16030 | 32 | 15872 | 0.000090516 | 1671.057 | 15.316 | length |
| 16 | `pilot-ordered-1522e75-16000-g00000-long-r04` | `pilot-ordered-1522e75-16000-g00000` | 16000 | long | 4 | 16030 | 32 | 15872 | 0.000090516 | 1999.513 | 14.609 | length |
| 17 | `pilot-ordered-1522e75-throughput-00000-throughput-r00` | `pilot-ordered-1522e75-throughput-00000` | 1000 | throughput | 0 | 1055 | 512 | unknown | 0.00046545 | 1199.183 | 157.465 | length |
| 18 | `pilot-ordered-1522e75-32000-g00000-long-r00` | `pilot-ordered-1522e75-32000-g00000` | 32000 | long | 0 | 31966 | 32 | unknown | 0.0048141 | 2550.153 | 11.725 | length |
| 19 | `pilot-ordered-1522e75-32000-g00000-long-r01` | `pilot-ordered-1522e75-32000-g00000` | 32000 | long | 1 | 31966 | 32 | 31744 | 0.000147732 | 1587.237 | 16.131 | length |
| 20 | `pilot-ordered-1522e75-32000-g00000-long-r02` | `pilot-ordered-1522e75-32000-g00000` | 32000 | long | 2 | 31966 | 32 | 31744 | 0.000147732 | 1696.325 | 16.629 | length |
| 21 | `pilot-ordered-1522e75-32000-g00000-long-r03` | `pilot-ordered-1522e75-32000-g00000` | 32000 | long | 3 | 31966 | 32 | 31744 | 0.000147732 | 1916.514 | 12.491 | length |
| 22 | `pilot-ordered-1522e75-32000-g00000-long-r04` | `pilot-ordered-1522e75-32000-g00000` | 32000 | long | 4 | 31966 | 32 | 31744 | 0.000147732 | 1843.69 | 13.502 | length |

---
*审计报告核验完成，无密钥敏感数据，供父验收。*