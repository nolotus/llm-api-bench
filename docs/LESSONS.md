# 多供应商 LLM 实测：经验与操作手册

> 本文记录 2026-10-20 对 DeepSeek V4.1 Flash 五家供应商、七个档位实测中踩到的坑、
> 定下的口径和留下的工具。目的是让下一个人不必重走弯路，也让已有数据的解读不越界。

---

## 0. 一页速查：踩过的坑与正确做法

| 现象 | 根因 | 正确做法 |
|---|---|---|
| 实际输入只有目标的 30–40% | 把 UTF-8 **字节数**当 token 规划 | 按实测字节/token 组装，并用返回的 usage 回校 |
| 缓存命中恒为 0 | 请求没带**会话标识**，被路由到不同副本 | 同一对话带同一个 `x-session-affinity` |
| 冷热对比全 0 | 冷热请求**同批并发**，暖请求抢跑 | 冷请求完成后才发暖请求（串行或显式依赖） |
| 短上下文命中 93%、长上下文 99% | 缓存按块对齐，末尾 150–250 token 不命中 | 报命中率必须同时报上下文长度 |
| 换一个档位测，"冷"请求却有命中 | 前缀被同 run 的其他档位预热 | 前缀按 (provider, tier, run) 隔离 |
| 首字很快，但正文为空 | 输出预算被思考链吃满 | 输出预算 ≥ 512（Fireworks 需 1024+） |
| 排序上午和下午相反 | 单时段快照 + 服务端负载波动 | 至少两个时段各测一轮，报两个值 |
| 并发到 5 就下结论 | 样本不足、客户端先瓶颈 | 阶梯 1/2/4/8/16/32；C≥16 注明本机限制 |
| 一个请求花了超过预留上限，整批停 | 预留下界估太紧 | 预留上界留 10% 余量 |
| usage 里 cached = 输入−1 | 上报字段异常，非真实缓存 | 恒定偏移判为上报假象，单列 |

---

## 1. 测量口径（不可妥协）

1. **长度**：目标用 token 表示；组装时按实测字节/token（本语料 5.6–6.2），跑完用 `prompt_tokens` 回校，记录偏差。
2. **缓存**：同一段对话必须带同一个会话标识（`x-session-affinity`），否则命中归零。冷请求必须先完成。
3. **冷热**：`cold` = 该前缀首次出现，同一 (provider, tier, run) 内唯一。
4. **输出预算**：512 起；思考链长的供应商（Fireworks、Baseten Fast）用 1024+，否则只测到思考时间。
5. **可比性**：只有同 context、同 cache_state、同并发、同输出预算的数字才能并列。
6. **样本量**：P50 要 n≥20，P95 要 n≥60，P99 要 n≥200；不足时注明"P99 等同 max"。
7. **分位数优先于均值**：报告必须含 `n / min / P50 / P90 / P95 / P99 / max / mean`，离群值保留不剔除。
8. **费用**：一律写"按配置单价 × 上报 usage 的**估算**，非平台账单"。
9. **缺失值**：`null` / `unknown` 单独统计，**不得填 0**。
10. **并发**：C 是客户端在途数，不是服务端容量；C≥16 时本机可能先饱和。

---

## 2. 工具链

| 文件 | 作用 | 关键约束 |
|---|---|---|
| `budget.py` | 追加式预算账本，reserve/settle，fsync，flock | 单实例单进程；`overrun` 后拒绝后续预留 |
| `stage_bench.py` | 批次执行器：先整批预留 → 并发发送 → 顺序结算 | 预算不足**零发送**；缺输出上界直接报错；预留带 10% 余量 |
| `stage1.py` | 冷热对照批量测试（多上下文、多次暖重复） | 串行（`max_workers=1`）保证冷热顺序 |
| `stage2.py` | 增长曲线 / 停顿存活 / 并发阶梯 | 同 stage_bench，各模式共用账本 |
| `sustained.py` | 持续压测：固定速率跑 N 分钟，出分位数与分桶 | 带会话标识；每请求独立结算 |
| `corpus.py` | 语料生成：按 token 目标、冷热同前缀、增长链 | 确定性；前缀逐字节一致 |
| `live_transport.py` | `transport.stream_chat` → stage_bench 契约的适配器 | 可注入 `extra_headers`；不打印 key |
| `session_sim.py` | 蒙特卡洛会话模拟（bootstrap 实测样本） | 输出会话级 P50/P90/P99，不用平均值 |
| `coding_model.py` | coding 会话成本模型 | 参数全部来自实测；推算项标注 |
| `make_cards.py` | 生成社交图卡（1080×1440） | 数据写死前先核对 |

---

## 3. 预算与安全

- 每家一个独立账本与上限；新供应商每家 ≤ $2（风险预算，含未知历史支出）。
- **批次预预留**：发送前一次性预留整批；余额不足则一条都不发。
- **预留上界**：`upper = 成本(输入上界, 全部输出上限) × 1.10`。少 10% 余量会导致单次超支判 overrun 并停机。
- **未知用量**：`settle(None)` 保留上界，不释放；重启时 `EXISTING_HOLD` 阻止新批次，需点名对账。
- **禁止自动重试**：一次失败即记账，用新 request_id 才允许重发。
- **压测脚本必须走同一账本**：早期 `stress`/`concurrency` 探针绕过账本，导致真实支出无法确证。

---

## 4. 已知未解问题

| 问题 | 现状 | 影响 |
|---|---|---|
| Baseten 缓存 | 带会话标识后 Standard 5/8 命中；Fast 档数据异常，已从结论中排除 | 需换账户或换端点复核 |
| `cached = 输入−1` 的上报 | 在 Fast 档观察到恒定偏移，判为上报假象 | 该档数据已排除，不用于结论 |
| Lithos 大上下文冷启动 | 128K 6.7–14.2s、256K 10.8s，明显高于其他家 32K 的 0.8–2.3s | 需四家 128K 冷启动对比才能归因 |
| DeepSeek 官方单价 | 官方定价页动态渲染，未逐项复核 | 价格表标"配置值"，峰谷机制已确证 |
| Fireworks 无正文率 | 1024 输出预算下仍有约半数请求无正文 | 需更高预算或关闭思考 |
| 800K 上下文 | 未实测 | 全部为推算，不得当实测引用 |

---

## 5. 数据文件索引

```
results/
  stage1/            冷热对照与档位测试（每目录一份 summary.json + 原始 records）
  stage2/            增长 / 停顿 / 并发（stage_records.jsonl 全局记录）
  sustained/         持续压测（同上）
  cards/             生成的图卡
  matrix-v1/         早期矩阵测试与勘误（方法有误，仅存档）
  formal-v1/         早期 Base 数据与停止说明（归档）
providers/
  benchmark-matrix.json   价格、模型 ID、extra_body、cap
docs/
  RESULTS-STANDARD.md     测量与报告标准
  LESSONS.md              本文件
```

---

## 6. 复现一次完整测量

```bash
# 1) 单档冷热对照（4K，冷 1 + 暖 5）
nolo secret run --with <secret> -- python3 stage1.py \
  --provider lithos --tier base --sizes 4000 --out-cap 512 \
  --warm-repeats 5 --key-env LITHOSAI_API_KEY \
  --ledger results/stage1/x.jsonl --tag x

# 2) 持续压测（4K，6 分钟，5 次/分钟）
nolo secret run --with <secret> -- python3 sustained.py \
  --provider lithos --tier base --size 4000 --minutes 6 --per-minute 5 --tag r1

# 3) 缓存增长曲线
nolo secret run --with <secret> -- python3 stage2.py \
  --mode growth --provider lithos --tier base --tag g1

# 4) 汇总
python3 session_sim.py
python3 coding_model.py
```

**注意**：`nolo secret run` 注入密钥；不要把密钥写进命令行或代码。

---

## 7. 结论的边界

- 所有数据来自 2026-10-20 单日、单地区，未覆盖跨天与多地域。
- 费用为估算值，与平台账单可能存在差异（促销、阶梯、最小计费单位）。
- 延迟是客户端接收时间，包含网络；不是服务端 token 时间。
- 数据用于自身选型参考；**不构成供应商排名或采购建议**。