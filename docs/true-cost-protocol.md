# Comprehensive LLM Benchmark: Technical & Economic Evaluation Metric Protocol

## 1. 真实综合成本模型 (True Cost Equation)
对每一次请求与工作负载，严格区分账面标价与实际综合成本：
$$\text{Cost}_{\text{true}} = \frac{(T_{\text{in}} - T_{\text{cached}}) \times P_{\text{in}} + T_{\text{cached}} \times P_{\text{cached}} + T_{\text{out}} \times P_{\text{out}}}{1,000,000}$$

### 衍生经济指标：
- **有效每千字成本 (Effective Cost per 1k Output Tokens)**: $\frac{\text{Total Cost}}{\text{Completion Tokens}} \times 1,000$ （综合衡量输入膨胀与缓存命中后的真实产出性价比）。
- **缓存成本节省比 (Cache Cost Reduction)**: $1 - \frac{\text{Actual Cost}}{\text{Uncached Cost}}$。
- **快速档溢价性价比 (Speed-Cost Tradeoff Ratio)**: $\frac{\Delta \text{TPS}}{\Delta \text{Cost}}$ 及 $\frac{\Delta \text{TTFT}}{\Delta \text{Cost}}$ （快速档加价 50%~100% 后，单位美元换取的延迟降低或速度增益）。

## 2. 关键技术指标体系 (Technical Metrics)
- **TTFT (Time-to-First-Token 首字延迟)**：
  - $\text{TTFT}_{\text{raw}}$: 建立连接至首个 SSE 数据块到达时间（客户端接收感知，包含网络/TLS）。
  - $\text{TTFT}_{\text{content}}$: 首个非空正文到达时间（排除 role 和思维链前置块）。
- **流式输出速率 (Streaming Generation Speed)**：
  - $\text{TPS}_{\text{chunk}} = \frac{T_{\text{out}}}{t_{\text{last\_content}} - t_{\text{first\_content}}}$ （净生成阶段 token/s）。
- **缓存有效性 (Cache Efficacy)**：
  - **请求命中率 (Request Hit Rate)**: 有缓存 token 的请求比例。
  - **Token 覆盖率 (Token Hit Ratio)**: $\frac{\sum T_{\text{cached}}}{\sum T_{\text{in}}}$。
- **稳定性与可靠性 (Reliability)**：
  - 首发成功率 (HTTP 200且 `done=True` 比例)、429 限流率、网络抖动 IQR 与超时率。
