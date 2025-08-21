"""
Understanding Service
Fast, low-cost LLM pass to classify intent and expand the retrieval query.
"""

import os
from typing import Any, Dict, List

from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class UnderstandingService:
    def __init__(self):
        # Use a lighter model for cost/latency
        self.model = os.getenv("UNDERSTANDING_MODEL", "gpt-4o-mini")

    async def analyze(self, current_message: str, last_turns: List[Dict[str, str]]) -> Dict[str, Any]:
        """Return structured intent + expanded query.

        last_turns: list of {"user_message": str, "ai_response": str}
        """
        # Keep only last 2 turns for reference
        short_ctx = last_turns[-2:] if last_turns else []
        ctx_text = "\n".join(
            [
                f"User: {t['user_message']}\nAssistant: {t['ai_response']}" for t in short_ctx
            ]
        )

        prompt = f"""
You are a fast intent and query-expansion assistant.
Given the current user message and the last turns, do ALL of the following:
1) Resolve references (e.g., "it", "that", flavors) into explicit entities.
2) Classify intents - can be one or multiple from: ["product", "company", "general"].
3) Produce an expanded retrieval query with synonyms and constraints when relevant.
4) If clarification is required, set need_clarification=true and propose a brief follow_up_question.

Examples:
- "What supplements do you sell?" → ["product"]
- "Tell me about your company" → ["company"] 
- "What does your company do and what products do you sell?" → ["product", "company"]
- "Hello" → ["general"]

Return STRICT JSON with these keys only:
{{
  "intents": ["product" | "company" | "general"],
  "expanded_query": string,
  "entities": [string],
  "synonyms": [string],
  "product_constraints": {{"price_range"?: string, "category"?: string, "flavor"?: string, "form"?: string, "brand"?: string}},
  "company_topics": [string],
  "need_clarification": boolean,
  "follow_up_question"?: string
}}

Last turns:
{ctx_text}

Current user message:
{current_message}

JSON only:
"""

        try:
            resp = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250,
                temperature=0.2,
            )
            content = (resp.choices[0].message.content or "").strip()
            # Best-effort JSON parsing; keep minimal validation to avoid heavy deps
            import json

            data = json.loads(content)
            # Minimal guards
            if data.get("intent") not in ("product", "company", "general"):
                data["intent"] = "general"
            data.setdefault("expanded_query", current_message)
            data.setdefault("entities", [])
            data.setdefault("synonyms", [])
            data.setdefault("product_constraints", {})
            data.setdefault("company_topics", [])
            data.setdefault("need_clarification", False)
            return data
        except Exception:
            # Fallback: general, passthrough query
            return {
                "intent": "general",
                "expanded_query": current_message,
                "entities": [],
                "synonyms": [],
                "product_constraints": {},
                "company_topics": [],
                "need_clarification": False,
            }


understanding_service = UnderstandingService()


