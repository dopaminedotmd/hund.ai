"""delegate_task tool — spawna subagents for parallella uppgifter."""
from __future__ import annotations
import json

def run_delegation(args: dict) -> str:
    tasks_json = args.get("tasks", "[]")
    if isinstance(tasks_json, str):
        try:
            tasks = json.loads(tasks_json)
        except json.JSONDecodeError:
            return "[error] 'tasks' maste vara giltig JSON"
    else:
        tasks = tasks_json
    if not tasks:
        return "[error] 'tasks' ar tom"
    if len(tasks) > 3:
        return "[error] max 3 tasks per delegation"
    # Client maste injectas — gor det via en global/config
    from ..agent.delegation import delegate_tasks, DelegationResult
    from ..providers.openai_compatible import OpenAICompatibleClient
    from ..config import HundConfig
    from ..secrets import load_api_key
    cfg = HundConfig.load()
    key = load_api_key(cfg.provider.api_key_env)
    if not key:
        return "[error] API-nyckel saknas for delegation"
    client = OpenAICompatibleClient(cfg.provider.base_url, key, cfg.provider.model)
    results = delegate_tasks(tasks, client)
    lines = []
    for r in results:
        status = "OK" if r.success else "FAIL"
        lines.append(f"[task {r.task_id}] {status}: {r.summary[:300]}")
    return "\n".join(lines) if lines else "[error] inga resultat"
