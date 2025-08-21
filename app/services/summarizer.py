"""
Summarizer Service
Handles conversation summarization for long-term memory
"""

from openai import AsyncOpenAI
from typing import List, Dict
import os

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class SummarizerService:
    def __init__(self):
        self.model = "gpt-3.5-turbo"
        self.max_tokens = 800  # Increased for complete summaries
    
    async def summarize_conversation(self, conversation_history: List[Dict[str, str]]) -> str:
        """
        Create detailed customer service summary for long-term memory
        Like notes a customer service representative would keep about a customer
        """
        try:
            # Prepare conversation text
            conversation_text = ""
            for turn in conversation_history:
                conversation_text += f"Customer: {turn['user_message']}\n"
                conversation_text += f"Assistant: {turn['ai_response']}\n\n"
            
            # Create comprehensive customer service summary prompt
            prompt = f"""You are a customer service representative creating detailed notes about this customer based on their conversation history. Create a comprehensive summary that would help any customer service agent understand this customer's profile, interests, and needs.

Focus on:
📊 CUSTOMER PROFILE:
- What type of customer they are (new, returning, interested, skeptical, etc.)
- Their communication style and preferences
- Their knowledge level about products/services

🎯 INTERESTS & PREFERENCES:
- Specific products they've shown interest in
- Features or benefits they care about most
- Price sensitivity or budget concerns
- Health goals or lifestyle preferences

❓ QUESTIONS & CONCERNS:
- Main questions they've asked
- Concerns or objections raised
- Information they're seeking
- Any hesitations or doubts

🛒 PURCHASE BEHAVIOR:
- Products they've inquired about
- Stage in the buying journey (browsing, comparing, ready to buy)
- Specific requirements or criteria mentioned

📝 IMPORTANT NOTES:
- Any personal details shared (allergies, conditions, goals)
- Follow-up actions needed
- Special circumstances or requests

Create a summary that would help me serve this customer better in future interactions.

Conversation History:
{conversation_text}

Customer Service Summary:"""
            
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=0.3
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            raise Exception(f"Summarization failed: {str(e)}")
    
    async def update_customer_summary(
        self, 
        existing_summary: str, 
        new_conversation: List[Dict[str, str]]
    ) -> str:
        """Update existing customer summary with new conversation data"""
        try:
            # Summarize new conversation
            new_insights = await self.summarize_conversation(new_conversation)
            
            # Merge summaries intelligently
            prompt = f"""You are updating customer service notes. Merge the existing customer summary with new insights from recent conversations. Keep all valuable information and update any outdated details.

INSTRUCTIONS:
- Preserve all important historical information
- Add new insights and update preferences 
- Note any changes in customer behavior or interests
- Maintain the comprehensive customer service format
- Remove outdated or contradictory information

EXISTING CUSTOMER SUMMARY:
{existing_summary}

NEW CONVERSATION INSIGHTS:
{new_insights}

UPDATED CUSTOMER SUMMARY:"""
            
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,  # More tokens for comprehensive updates
                temperature=0.3
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            raise Exception(f"Summary update failed: {str(e)}")


# Global service instance
summarizer_service = SummarizerService()
