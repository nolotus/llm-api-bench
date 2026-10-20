# Deep Benchmark Framework: Cache Growth Curvature, Degradation & Reliability

## 1. 缓存曲率增长模型 (Cache Curvature & Scaling Law)
不采用机械愚钝的 1000 次真实往返，而是采用**几何对数步进（Logarithmic / Geometric Stride）**：
- 轮次/上下文检查点：**Turn 1 (冷启动) $\to$ Turn 3 $\to$ Turn 10 $\to$ Turn 25 $\to$ Turn 50 $\to$ Turn 100**。
- 对应上下文跨度：$1\text{K} \to 4\text{K} \to 12\text{K} \to 32\text{K} \to 64\text{K}$ 极限边界。
- 观测核心指标：
  1. **缓存曲率 $\frac{d(\text{CacheRatio})}{d(\text{Tokens})}$**: 是否在特定上下文（如 16K 或 32K）发生拐点？
  2. **首字延迟压制比**: $\text{TTFT}_{\text{cached}} / \text{TTFT}_{\text{cold}}$（上下文膨胀到 64K 时，缓存是否依然能把延迟压在 1s 以内）。
  3. **边际成本陡降曲线**: 每一轮交互的真实边际账单单价。

## 2. 深度缺失指标补充 (Uncovered Frontier Dimensions)

### A. 缓存驱逐与生命期探测 (TTL & Eviction Cliff)
- **间隔敏感度**: 同一 16K 前缀，在空闲停顿 **0s / 10s / 30s / 60s / 180s** 后，缓存是否仍然存在？
- **多会话并发竞争**: 当同时有两个独立会话轮流发送时，服务商是否会发生 KV Cache 互相踩踏与频繁换出？

### B. 并发算力池挤压与降速 (Concurrency Degradation)
- **并发阶梯**: $C=1 \to C=3 \to C=5$。
- **单路吞吐衰减 (Throughput Decay)**: 多路并发时单路 TPS 是否发生腰斩？
- **排队超时与拒载 (Queue & 429)**: 哪家在并发达到 5 时率先出现 429 限流或 503 崩溃？

### C. 流式卡顿与中断 (Jitter & Stream Resilience)
- **最大 chunk 停顿 (Max Gap)**: 识别“平均 TPS 很高但中途憋字停顿 3 秒”的虚假加速。
- **断流 (EOF Without DONE)**: 统计静默掐断率。
- **思考链 (Reasoning) 与正文隔离**: 严密区分前置推理耗时与实际可用正文到达时间。
