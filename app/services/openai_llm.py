"""
OpenAI LLM Service
Wrapper for OpenAI API interactions (OpenAI Python SDK v1+)
"""

from typing import List, Dict, Any, Optional
import os
import uuid
from dotenv import load_dotenv
from openai import AsyncOpenAI
from app.database.postgres import get_pool

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class OpenAIService:
    def __init__(self):
        self.model = "gpt-4"
        self.max_tokens = 1000
        self.temperature = 0.7
    
    async def generate_response(
        self,
        message: str,
        conversation_history: List[Dict[str, str]] = None,
        customer_summary: str = None,
        kb_sections: Optional[Dict[str, List[str]]] = None,
        intents: Optional[List[str]] = None,
        uuid: Optional[str] = None, #testing purpose only needed to be remove
    ) -> str:
        """
        Generate AI response using OpenAI with intelligent memory management
        
        Uses either:
        - Recent conversation history (if within 24 hours)
        - Long-term customer memory (if >24 hours since last chat)
        """
        
        # Get custom system prompt from database or use default
        custom_base_prompt = await self._get_system_prompt_from_db(uuid)
        
        # Build system prompt with context and customer memory
        system_prompt = self._build_system_prompt(
            customer_summary=customer_summary,
            kb_sections=kb_sections or {},
            intents=intents or [],
            custom_base_prompt=custom_base_prompt,
        )
        
        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history (already limited to last 5 turns by memory service)
        if conversation_history:
            for turn in conversation_history:  # Memory service already provides max 5 turns
                messages.append({"role": "user", "content": turn["user_message"]})
                messages.append({"role": "assistant", "content": turn["ai_response"]})
        # Note: customer_summary is embedded in system prompt for long-term memory
        
        # Add current message
        messages.append({"role": "user", "content": message})
        
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            return (response.choices[0].message.content or "").strip()

        except Exception as e:
            raise Exception(f"OpenAI API error: {str(e)}")
    
    async def _get_system_prompt_from_db(self, uuid: Optional[str] = None) -> Optional[str]:
        """Get custom system prompt from database, return None if not set"""
        try:
            pool = get_pool("crm")
            async with pool.acquire() as conn:
                # Get custom system prompt from company_info
                result = await conn.fetchval("""
                    SELECT system_prompt 
                    FROM company_info
                    WHERE user_uuid = $1 AND system_prompt IS NOT NULL AND system_prompt != ''
                    LIMIT 1
                """, str(uuid))
                
                if result:
                    print(f"📝 Using custom system prompt from database")
                    return result.strip()
                else:
                    print(f"📝 Using default system prompt")
                    return None
                    
        except Exception as e:
            print(f"❌ Failed to fetch system prompt: {e}")
            return None

    def _build_system_prompt(
        self,
        customer_summary: str = None,
        kb_sections: Optional[Dict[str, List[str]]] = None,
        intents: Optional[List[str]] = None,
        custom_base_prompt: Optional[str] = None,
    ) -> str:
        """Build system prompt that lets the model choose relevant context in one pass"""
        
        # Use custom prompt from database or fallback to default
        if custom_base_prompt:
            base_prompt = custom_base_prompt
        else:
            base_prompt = (
                "You are MinaAI, a helpful customer service chatbot.\n"
                "Use the provided recent turns to resolve references (it/that/this).\n"
                "Answer in ONE pass.\n"
                "- Never invent facts not present in data. If info is insufficient, ask one short clarifying question.\n"
                "- Be concise and friendly."
            )

        # Handle multiple intents intelligently
        if intents:
            has_product = "product" in intents
            has_company = "company" in intents
            has_general = "general" in intents
            
            if has_product and has_company:
                base_prompt += "\n- Use both PRODUCT_DATA and COMPANY_DATA as relevant to answer comprehensively."
            elif has_product:
                base_prompt += "\n- Use PRODUCT_DATA only; ignore COMPANY_DATA."
            elif has_company:
                base_prompt += "\n- Use COMPANY_DATA only; ignore PRODUCT_DATA."
            elif has_general:
                base_prompt += "\n- General query: use available data only if clearly relevant."
        else:
            base_prompt += "\n- General query: use available data only if clearly relevant."

        # Add customer memory if available
        if customer_summary:
            base_prompt += f"\n\n=== CUSTOMER_BACKGROUND ===\n{customer_summary}"

        # Render configured data sections (e.g., PRODUCT_DATA, COMPANY_DATA, FAQ_DATA)
        if kb_sections:
            for section_name, items in kb_sections.items():
                if not items:
                    continue
                bullets = "\n- ".join(items)
                bullets = f"- {bullets}" if bullets else ""
                base_prompt += f"\n\n=== {section_name} ===\n{bullets}"
        
        print(f"Full details that will be send to llm: {base_prompt}")
        return base_prompt


# Global service instance
openai_service = OpenAIService()
