"""ResearchAgent — LLM-based knowledge scope estimation."""
from __future__ import annotations

import json
from typing import Any

from ..providers.base import Message


def research_domain(domain: str, client, model: str | None = None) -> dict[str, Any] | None:
    """Use LLM training data to estimate the knowledge landscape for a domain.

    Args:
        domain: Domain name (e.g. 'shopify-liquid').
        client: ProviderClient instance.
        model: Optional model override.

    Returns:
        Dict with domain, total_estimated_units, categories, sources, difficulty.
        None if parsing fails.
    """
    prompt = f"""You are a research agent. Map the knowledge landscape for: {domain}

Based on your training data, estimate:
1. How many distinct concepts/APIs/tags/functions exist in this domain?
2. Categorize them (tags, objects, filters, syntax, best practices, tools, etc.)
3. If all knowledge were in one file — how many "knowledge units" would that be?
   (One unit = one thing Hund needs to know, e.g. "liquid tag syntax", "product object properties")
4. What are the most important sources?

Respond with ONLY valid JSON (no markdown):
{{
  "domain": "{domain}",
  "total_estimated_units": <number>,
  "categories": [
    {{"name": "...", "estimated_units": <number>, "description": "..."}}
  ],
  "sources": ["url1", "url2"],
  "difficulty": "beginner|intermediate|advanced|expert",
  "notes": "short summary"
}}"""

    system_msg = Message(role="system", content="You are a research agent. Respond ONLY with valid JSON.")
    user_msg = Message(role="user", content=prompt)

    try:
        result = client.complete([system_msg, user_msg], model=model)
        text = result.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception:
        return None
