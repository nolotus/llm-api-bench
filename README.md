# Lithos API Benchmark（进行中）

**状态：代码进行中；尚未运行真实请求。** 当前没有实测结果，也没有可用 CLI。此仓库描述候选协议与计划，不代表模型身份、质量或性能已验证。正式运行前须冻结准确模型 ID、输入/输出上限与计划，并完成协议预注册；公开协议及输入哈希后 commit/push 才能开始正式 run。

## 候选计划

- 单时段、单地区、并发数 1；每请求新建 TCP/TLS 连接，不使用 SDK；OpenAI-compatible Chat Completions。无自动重试；失败不补跑，崩溃/结果未知的请求不重发。
- 候选提供方：LithosAI（OpenAI-compatible endpoint）；候选模型 ID `deepseek-ai/DeepSeek-V4.1-Flash`（**尚未验证，须在 models 冻结后确认**）。通过 LithosAI endpoint 调用，绝非直连 DeepSeek。价格计划值：输入 $0.15/M、缓存输入 $0.003/M、输出 $0.60/M；来源：[Lithos 官方价格页](https://lithosai.com/pricing)。不记录未核实的抓取时间。
- 目标 5,000 请求：四档输入目标长度 1,000/4,000/16,000/32,000 tokens，各 200 组，每组 5 次（1 次新输入、4 次复用），共 4,000 次；每次短请求输出 cap 为 32 tokens。另有 1,000 次输入目标 1,000 tokens、输出 cap 512 tokens。输入长度是生成目标而非硬上限或实测 tokenizer 数。生成器使用公开 seed，每组自然语言合成文本带唯一前缀。输入 token 数以供应商 usage 为准，绝不以字节数替代。
- 按 K=1,000、上述目标输入与输出 caps、未计缓存折扣计算理论费用：输入 $55M×$0.15/M=$8.25，输出 $0.64M×$0.60/M=$0.384，合计 **$8.634**。这仅按计划 tokens 与列明价格计算，不含额外推理 tokens 或其他费用，也不是账单保证。缓存 usage 缺失/不明记为未知，不记 0；供应商报告的缓存命中不构成服务端可证真事实。
- 总预算上限意图为 $15，包含 pilot 与未知结果的完整预留 hold；先展示计划费用及独立组数，pilot 后冻结请求数量。$1/$5/$15/$100 是价格敏感的预算计划档，不对应固定请求量。客户端无法保证供应商账单不超预算。

## 报告约束

公开请求、事件、usage、错误记录；认证信息、API key 与 secret 永不进入 Git。首生成与首正文分别统计。SSE chunk 不等于 token；tokens/s 是以 completion usage 除以首末非空正文 chunk 间隔的近似值，含首 chunk 时序偏差。延迟为客户端接收时间，不是服务端 token 时间。统计以独立组为 cluster，bootstrap 500 次，seed 固定；p95 至少 100 个有效样本且 100 个独立组，p99 至少 1,000 个独立组才报告，这些门槛不保证估计精度。失败等非成功延迟另报，不静默剔除后冒充成功性能。模型身份/质量不能由速度证明。

## License

代码采用 MIT（见 `LICENSE`）；生成的合成基准文本拟采用 CC0。CC0 仅适用于合成文本，不适用于代码、配置、运行记录、供应商内容或其他数据。

## English summary

Work in progress; no real requests have been run and no usable CLI is available. This is a candidate protocol, not a result. Model ID and plan must be frozen before formal runs. See `PROTOCOL.md` for measurement and safety rules.
