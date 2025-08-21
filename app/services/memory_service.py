"""
Memory Service
Handles conversation history and customer memory using PostgreSQL
Implements the correct memory strategy:
- Turns 1-5: Use only recent turns (1-5)
- Turns 6-10: Use last 5 turns + summary (hybrid mode)
- Turns 11+: Use last 5 turns + summary (hybrid mode)
- 24h+: Use last 5 turns + summary (regardless of time)
"""

import asyncio
import uuid
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta, timezone
from app.database.postgres import get_pool
from app.services.summarizer import summarizer_service


class MemoryService:
    def __init__(self):
        self.max_conversation_turns = 5
        self.summarization_threshold = 6  # Start summarization at 6 turns
        self.hybrid_memory_threshold = 6  # Use hybrid mode at 6+ turns
        self.session_timeout_hours = 24
    
    def get_malaysia_time(self) -> datetime:
        """Get current time in Malaysia timezone (UTC+8) as naive datetime"""
        utc_time = datetime.now(timezone.utc)
        malaysia_time = utc_time + timedelta(hours=8)
        return malaysia_time.replace(tzinfo=None)
    
    async def get_conversation_context_optimized(self, customer_phone: str) -> Tuple[List[Dict[str, str]], str, Optional[str], bool]:
        """
        MAIN METHOD: Get all memory context in ONE optimized database call
        
        Memory Strategy:
        - Turns 1-5: Recent context only
        - Turns 6-10: Last 5 turns + summary (hybrid)
        - Turns 11+: Last 5 turns + summary (hybrid)
        - 24h+: Last 5 turns + summary (hybrid)
        
        Returns: (conversation_history, session_id, customer_summary, use_hybrid)
        """
        try:
            print(f"🔍 Retrieving memory context for phone: {customer_phone}")
            pool = get_pool()
            
            async with pool.acquire() as conn:
                # Single optimized query to get all required data
                result = await conn.fetchrow("""
                    WITH latest_chat AS (
                        SELECT 
                            session_id,
                            created_at,
                            COUNT(*) OVER (PARTITION BY session_id) as session_turn_count
                        FROM chat_history 
                        WHERE customer_phone = $1 
                        ORDER BY created_at DESC 
                        LIMIT 1
                    ),
                    customer_data AS (
                        SELECT summary, total_conversations
                        FROM customer_memory 
                        WHERE customer_phone = $1
                    )
                    SELECT 
                        lc.session_id,
                        lc.created_at,
                        lc.session_turn_count,
                        cd.summary,
                        cd.total_conversations
                    FROM latest_chat lc
                    LEFT JOIN customer_data cd ON true
                """, customer_phone)
                
                # No previous conversations - return empty state
                if not result or not result['session_id']:
                    print("🆕 No previous conversations found")
                    return [], self.generate_session_id(), None, False
                
                # Check session timeout (24 hours)
                now_malaysia = self.get_malaysia_time()
                time_since_last = now_malaysia - result['created_at']
                session_expired = time_since_last.total_seconds() > (self.session_timeout_hours * 3600)
                
                if session_expired:
                    print(f"⏰ Session expired ({time_since_last.days} days ago), starting new session")
                    # Return long-term memory only for expired sessions
                    customer_summary = self._format_customer_summary(
                        result['summary'], 
                        result['total_conversations'], 
                        result['created_at'],
                        now_malaysia
                    )
                    return [], self.generate_session_id(), customer_summary, True
                
                # Get recent conversation history for active session
                session_id = str(result['session_id'])
                session_turn_count = result['session_turn_count'] or 0
                
                # Fetch recent conversation history (last 5 turns)
                history_results = await conn.fetch("""
                    SELECT user_question, llm_answer, created_at
                    FROM chat_history 
                    WHERE customer_phone = $1 AND session_id = $2
                    ORDER BY created_at DESC 
                    LIMIT $3
                """, customer_phone, uuid.UUID(session_id), self.max_conversation_turns)
                
                # Build conversation history in chronological order
                conversation_history = []
                for h_result in reversed(history_results):
                    conversation_history.append({
                        "user_message": h_result['user_question'],
                        "ai_response": h_result['llm_answer'],
                        "timestamp": h_result['created_at'].isoformat()
                    })
                
                print(f"📝 History length: {len(conversation_history)}, Session ID: {session_id}")
                
                # Determine memory strategy based on turn count
                use_hybrid = session_turn_count >= self.hybrid_memory_threshold
                customer_summary = None
                
                if use_hybrid:
                    # Use hybrid mode: recent turns + long-term summary
                    customer_summary = self._format_customer_summary(
                        result['summary'], 
                        result['total_conversations'], 
                        result['created_at'],
                        now_malaysia
                    )
                    print(f"🔄 Using HYBRID memory: {len(conversation_history)} recent turns + long-term summary")
                elif conversation_history:
                    print(f"📋 Using recent memory only: {len(conversation_history)} turns")
                else:
                    print(f"🆕 New customer - no memory available")
                
                return conversation_history, session_id, customer_summary, use_hybrid
                
        except Exception as e:
            print(f"❌ Error in optimized memory context: {e}")
            # Return safe defaults on error
            return [], self.generate_session_id(), None, False
    
    def _format_customer_summary(self, summary: str, total_conversations: int, last_interaction: datetime, current_time: datetime) -> Optional[str]:
        """Format customer summary with context"""
        if not summary or summary == "New customer":
            return None
            
        time_since_last = current_time - last_interaction
        
        if time_since_last.total_seconds() > 86400:  # More than 24 hours
            days_ago = max(1, int(time_since_last.days))
            context_intro = f"Returning customer (last seen {days_ago} days ago, {total_conversations} total conversations):\n\n"
        else:
            context_intro = f"Active customer ({total_conversations} conversations today):\n\n"
            
        return context_intro + summary
    
    def save_chat_async(
        self,
        customer_phone: str,
        session_id: str,
        user_question: str,
        llm_answer: str,
        response_time_ms: int = None
    ):
        """Save chat history asynchronously for better performance"""
        try:
            asyncio.create_task(self._save_chat_to_db(
                customer_phone, session_id, user_question, llm_answer, response_time_ms
            ))
            print("💾 Background save task created successfully")
        except Exception as e:
            print(f"❌ Failed to create background save task: {e}")
    
    async def _save_chat_to_db(
        self,
        customer_phone: str,
        session_id: str,
        user_question: str,
        llm_answer: str,
        response_time_ms: int = None
    ):
        """Internal method to save chat and handle summarization"""
        try:
            print(f"💾 Starting save to DB: phone={customer_phone}, session={session_id}")
            pool = get_pool()
            
            async with pool.acquire() as conn:
                # Use database transaction for consistency
                async with conn.transaction():
                    # Save chat history
                    await conn.execute("""
                        INSERT INTO chat_history 
                        (customer_phone, session_id, user_question, llm_answer, response_time_ms, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, customer_phone, uuid.UUID(session_id), user_question, llm_answer, 
                    response_time_ms, self.get_malaysia_time())
                    
                    # Update customer memory statistics
                    await conn.execute("""
                        INSERT INTO customer_memory (customer_phone, summary, total_conversations, first_interaction, last_interaction, customer_type, interaction_frequency, updated_at)
                        VALUES ($1, $2, 1, $3, $3, 'new', 'low', $3)
                        ON CONFLICT (customer_phone) 
                        DO UPDATE SET 
                            total_conversations = customer_memory.total_conversations + 1,
                            last_interaction = $3,
                            customer_type = CASE 
                                WHEN customer_memory.total_conversations >= 10 THEN 'loyal'
                                WHEN customer_memory.total_conversations >= 3 THEN 'returning'
                                ELSE 'new'
                            END,
                            interaction_frequency = CASE 
                                WHEN EXTRACT(EPOCH FROM ($3 - customer_memory.last_interaction)) / 3600 < 24 THEN 'high'
                                WHEN EXTRACT(EPOCH FROM ($3 - customer_memory.last_interaction)) / 3600 < 168 THEN 'medium'
                                ELSE 'low'
                            END,
                            updated_at = $3
                    """, customer_phone, "New customer", self.get_malaysia_time())
                    
                    # Get current session turn count for summarization decision
                    session_turn_count = await conn.fetchval("""
                        SELECT COUNT(*) FROM chat_history 
                        WHERE customer_phone = $1 AND session_id = $2
                    """, customer_phone, uuid.UUID(session_id))
                    
                    print(f"✅ Chat saved successfully to DB")
                    print(f"💾 Customer memory updated successfully")
                    
                    # Trigger summarization at the correct threshold
                    if session_turn_count >= self.summarization_threshold:
                        print(f"🧠 Triggering summarization at {session_turn_count} turns for better memory coverage")
                        asyncio.create_task(
                            self._summarize_conversations_background(customer_phone, session_id)
                        )
                    
        except Exception as e:
            print(f"❌ Error saving chat to DB: {e}")
            import traceback
            traceback.print_exc()
    
    async def _summarize_conversations_background(self, customer_phone: str, session_id: str):
        """Background task to summarize conversations when threshold is reached"""
        try:
            print(f"🧠 Starting background summarization for {customer_phone}")
            pool = get_pool()
            
            async with pool.acquire() as conn:
                # Get all conversations from current session for summarization
                conversations = await conn.fetch("""
                    SELECT user_question, llm_answer, created_at
                    FROM chat_history 
                    WHERE customer_phone = $1 AND session_id = $2
                    ORDER BY created_at ASC
                """, customer_phone, uuid.UUID(session_id))
                
                if len(conversations) < self.summarization_threshold:
                    print(f"⏭️ Not enough conversations to summarize ({len(conversations)} < {self.summarization_threshold})")
                    return
                
                # Convert to format expected by summarizer
                conversation_data = []
                for conv in conversations:
                    conversation_data.append({
                        "user_message": conv['user_question'],
                        "ai_response": conv['llm_answer']
                    })
                
                # Get existing summary efficiently (already fetched in main query if exists)
                existing_summary = await conn.fetchval("""
                    SELECT summary FROM customer_memory 
                    WHERE customer_phone = $1 AND summary != 'New customer'
                """, customer_phone)
                
                # Generate new summary
                if existing_summary:
                    print("🔄 Updating existing customer summary...")
                    new_summary = await summarizer_service.update_customer_summary(
                        existing_summary, conversation_data
                    )
                else:
                    print("✨ Creating new customer summary...")
                    new_summary = await summarizer_service.summarize_conversation(
                        conversation_data
                    )
                
                # Summary generated successfully
                
                # Save the updated summary
                await conn.execute("""
                    UPDATE customer_memory 
                    SET summary = $2, updated_at = $3
                    WHERE customer_phone = $1
                """, customer_phone, new_summary, self.get_malaysia_time())
                
                print(f"✅ Customer summary updated successfully (length: {len(new_summary)} chars)")
                
                # Keep all conversation history stored - no cleanup/deletion
                print(f"💾 All conversation history preserved for future reference")
                        
        except Exception as e:
            print(f"❌ Background summarization failed: {e}")
            import traceback
            traceback.print_exc()
    
    def generate_session_id(self) -> str:
        """Generate a new session ID"""
        return str(uuid.uuid4())
    
# Global service instance
memory_service = MemoryService()