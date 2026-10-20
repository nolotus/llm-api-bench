import os, sys, time, json, urllib.request, concurrent.futures
from pathlib import Path
from decimal import Decimal

# 读取通用长 prompt (4K 长度)
prompt_text = "Analyze the engineering trade-offs of microservices vs monoliths. " * 300

PROVIDERS = {
    "deepseek_official": {
        "url": "https://api.deepseek.com/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-flash",
        "auth_prefix": "Bearer "
    },
    "deepinfra": {
        "url": "https://api.deepinfra.com/v1/openai/chat/completions",
        "key_env": "DEEPINFRA_API_KEY",
        "model": "deepseek-ai/DeepSeek-V4.1-Flash",
        "auth_prefix": "Bearer "
    },
    "fireworks": {
        "url": "https://api.fireworks.ai/inference/v1/chat/completions",
        "key_env": "FIREWORKS_API_KEY",
        "model": "accounts/fireworks/models/deepseek-v4p1-flash",
        "auth_prefix": "Bearer "
    },
    "baseten": {
        "url": "https://inference.baseten.co/v1/chat/completions",
        "key_env": "BASETEN_API_KEY",
        "model": "deepseek-ai/DeepSeek-V4.1-Flash",
        "auth_prefix": "Bearer "
    }
}

def single_request(provider, concurrency_level, req_idx):
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        return {"error": "no_key"}
    
    payload = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "user", "content": f"Req {req_idx}: " + prompt_text}],
        "max_tokens": 16,
        "stream": False
    }).encode()
    
    req = urllib.request.Request(cfg["url"], data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": cfg["auth_prefix"] + key,
        "User-Agent": "Mozilla/5.0"
    })
    
    t0 = time.monotonic()
    status = 0
    err = None
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            resp.read()
    except Exception as e:
        err = type(e).__name__
    t1 = time.monotonic()
    
    return {
        "provider": provider,
        "concurrency": concurrency_level,
        "idx": req_idx,
        "status": status,
        "latency_ms": round((t1 - t0) * 1000, 1),
        "error": err
    }

def run_concurrency_test(provider, levels=(1, 3, 5)):
    results = []
    print(f"=== Testing Concurrency for {provider} ===")
    for c in levels:
        with concurrent.futures.ThreadPoolExecutor(max_workers=c) as executor:
            futs = [executor.submit(single_request, provider, c, i) for i in range(c)]
            level_res = [f.result() for f in futs]
            results.extend(level_res)
            latencies = [r["latency_ms"] for r in level_res if r["status"] == 200]
            errs = [r for r in level_res if r["status"] != 200]
            avg_l = sum(latencies)/len(latencies) if latencies else 0
            print(f" - C={c}: 成功={len(latencies)}/{c}, 平均延迟={avg_l:.1f}ms, 报错={len(errs)}")
        time.sleep(2)
    return results

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "deepseek_official"
    res = run_concurrency_test(target)
    out_p = Path("/home/nolotus/llm-api-bench/.worktrees/implementation/results") / f"concurrency_{target}.json"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(res, indent=2))
