"""
Memory Service - Optimized conversation history and customer memory management
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
        self.summarization_threshold = 6
        self.hybrid_memory_threshold = 6
        self.session_timeout_hours = 24
        self.summary_cycle_length = 5
    
    def _get_malaysia_time(self) -> datetime:
        """Get current time in Malaysia timezone (UTC+8)"""
        utc_time = datetime.now(timezone.utc)
        malaysia_time = utc_time + timedelta(hours=8)
        return malaysia_time.replace(tzinfo=None)
    
    async def get_conversation_context_optimized(self, customer_phone: str) -> Tuple[List[Dict[str, str]], str, Optional[str], bool]:
        """
        Get all memory context in a single optimized database call
        
        Returns: (conversation_history, session_id, customer_summary, use_hybrid)
        """
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchrow("""
                    WITH latest_chat AS (
                        SELECT session_id, created_at, 
                               COUNT(*) OVER (PARTITION BY session_id) as session_turn_count
                        FROM chat_history 
                        WHERE customer_phone = $1 
                        ORDER BY created_at DESC LIMIT 1
                    ),
                    customer_data AS (
                        SELECT summary, total_conversations, last_summary_turn
                        FROM customer_memory WHERE customer_phone = $1
                    )
                    SELECT lc.session_id, lc.created_at, lc.session_turn_count,
                           cd.summary, cd.total_conversations, cd.last_summary_turn
                    FROM latest_chat lc LEFT JOIN customer_data cd ON true
                """, customer_phone)
                
                if not result or not result['session_id']:
                    return [], self._generate_session_id(), None, False
                
                now_malaysia = self._get_malaysia_time()
                time_since_last = now_malaysia - result['created_at']
                session_expired = time_since_last.total_seconds() > (self.session_timeout_hours * 3600)
                
                if session_expired:
                    return await self._handle_expired_session(conn, customer_phone, result, now_malaysia)
                
                return await self._handle_active_session(conn, customer_phone, result, now_malaysia)
                
        except Exception as e:
            print(f"❌ Memory context error: {e}")
            return [], self._generate_session_id(), None, False
    
    async def _handle_expired_session(self, conn, customer_phone: str, result: dict, now_malaysia: datetime) -> Tuple[List[Dict[str, str]], str, Optional[str], bool]:
        """Handle expired session - return previous turns if <=5, summary if >5"""
        previous_session_id = str(result['session_id'])
        previous_session_turns = result['session_turn_count'] or 0
        new_session_id = self._generate_session_id()
        
        if previous_session_turns <= self.max_conversation_turns:
            conversation_history = await self._fetch_conversation_history(
                conn, customer_phone, previous_session_id, self.max_conversation_turns
            )
            
            asyncio.create_task(
                self._summarize_conversations_background(customer_phone, previous_session_id)
            )
            
            customer_summary = self._format_customer_summary(
                result['summary'], result['total_conversations'], 
                result['created_at'], now_malaysia
            )
            
            return conversation_history, new_session_id, customer_summary, bool(customer_summary)
        
        customer_summary = self._format_customer_summary(
            result['summary'], result['total_conversations'], 
            result['created_at'], now_malaysia
        )
        return [], new_session_id, customer_summary, True
    
    async def _handle_active_session(self, conn, customer_phone: str, result: dict, now_malaysia: datetime) -> Tuple[List[Dict[str, str]], str, Optional[str], bool]:
        """Handle active session using sliding window approach"""
        session_id = str(result['session_id'])
        session_turn_count = result['session_turn_count'] or 0
        last_summary_turn = result.get('last_summary_turn') or 0
        
        use_hybrid = session_turn_count >= self.hybrid_memory_threshold
        customer_summary = None
        
        if use_hybrid:
            customer_summary = self._format_customer_summary(
                result['summary'], result['total_conversations'], 
                result['created_at'], now_malaysia
            )
            
            turns_after_summary = session_turn_count - last_summary_turn
            recent_turns_to_include = min(turns_after_summary, 5)
            
            if recent_turns_to_include > 0:
                conversation_history = await self._fetch_conversation_history(
                    conn, customer_phone, session_id, recent_turns_to_include
                )
            else:
                if session_turn_count == 6:
                    conversation_history = await self._fetch_conversation_history(
                        conn, customer_phone, session_id, 5
                    )
                else:
                    conversation_history = []
        else:
            conversation_history = await self._fetch_conversation_history(
                conn, customer_phone, session_id, self.max_conversation_turns
            )
        
        return conversation_history, session_id, customer_summary, use_hybrid
    
    async def _fetch_conversation_history(self, conn, customer_phone: str, session_id: str, limit: int) -> List[Dict[str, str]]:
        """Fetch conversation history in chronological order"""
        history_results = await conn.fetch("""
            SELECT user_question, llm_answer, created_at
            FROM chat_history 
            WHERE customer_phone = $1 AND session_id = $2
            ORDER BY created_at DESC LIMIT $3
        """, customer_phone, uuid.UUID(session_id), limit)
        
        conversation_history = []
        for h_result in reversed(history_results):
            conversation_history.append({
                "user_message": h_result['user_question'],
                "ai_response": h_result['llm_answer'],
                "timestamp": h_result['created_at'].isoformat()
            })
        
        return conversation_history
    
    def _format_customer_summary(self, summary: str, total_conversations: int, last_interaction: datetime, current_time: datetime) -> Optional[str]:
        """Format customer summary with context"""
        if not summary or summary == "New customer":
            return None
            
        time_since_last = current_time - last_interaction
        
        if time_since_last.total_seconds() > 86400:
            days_ago = max(1, int(time_since_last.days))
            context_intro = f"Returning customer (last seen {days_ago} days ago, {total_conversations} total conversations):\n\n"
        else:
            context_intro = f"Active customer ({total_conversations} conversations today):\n\n"
            
        return context_intro + summary
    
    def save_chat_async(self, customer_phone: str, session_id: str, user_question: str, llm_answer: str, response_time_ms: int = None):
        """Save chat history asynchronously"""
        try:
            if isinstance(llm_answer, dict):
                llm_answer = (
                    llm_answer.get("response") or 
                    llm_answer.get("content") or 
                    str(llm_answer)
                )
            
            asyncio.create_task(self._save_chat_to_db(
                customer_phone, session_id, user_question, llm_answer, response_time_ms
            ))
        except Exception as e:
            print(f"❌ Background save task failed: {e}")
    
    async def _save_chat_to_db(self, customer_phone: str, session_id: str, user_question: str, llm_answer: str, response_time_ms: int = None):
        """Save chat and handle summarization"""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("""
                        INSERT INTO chat_history 
                        (customer_phone, session_id, user_question, llm_answer, response_time_ms, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, customer_phone, uuid.UUID(session_id), user_question, llm_answer, 
                    response_time_ms, self._get_malaysia_time())
                    
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
                    """, customer_phone, "New customer", self._get_malaysia_time())
                    
                    session_turn_count = await conn.fetchval("""
                        SELECT COUNT(*) FROM chat_history 
                        WHERE customer_phone = $1 AND session_id = $2
                    """, customer_phone, uuid.UUID(session_id))
                    
                    should_trigger_summary = (
                        session_turn_count == 6 or 
                        (session_turn_count > 6 and (session_turn_count - 6) % 5 == 0)
                    )
                    
                    if should_trigger_summary:
                        asyncio.create_task(
                            self._summarize_conversations_background(customer_phone, session_id, session_turn_count)
                        )
                    
        except Exception as e:
            print(f"❌ Database save error: {e}")
    
    async def _summarize_conversations_background(self, customer_phone: str, session_id: str, current_turn: int = None):
        """Background summarization using sliding window approach"""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                conversations = await conn.fetch("""
                    SELECT user_question, llm_answer, created_at
                    FROM chat_history 
                    WHERE customer_phone = $1 AND session_id = $2
                    ORDER BY created_at ASC
                """, customer_phone, uuid.UUID(session_id))
                
                if len(conversations) < 1:
                    return
                
                conversation_data = [
                    {"user_message": conv['user_question'], "ai_response": conv['llm_answer']}
                    for conv in conversations
                ]
                
                existing_summary = await conn.fetchval("""
                    SELECT summary FROM customer_memory 
                    WHERE customer_phone = $1 AND summary != 'New customer'
                """, customer_phone)
                
                if existing_summary:
                    new_summary = await summarizer_service.update_customer_summary(
                        existing_summary, conversation_data
                    )
                else:
                    new_summary = await summarizer_service.summarize_conversation(
                        conversation_data
                    )
                
                last_summary_turn = (current_turn or len(conversations)) - 1
                await conn.execute("""
                    INSERT INTO customer_memory (customer_phone, summary, total_conversations, first_interaction, last_interaction, customer_type, interaction_frequency, updated_at, last_summary_turn)
                    VALUES ($1, $2, 1, $3, $3, 'new', 'low', $3, $4)
                    ON CONFLICT (customer_phone)
                    DO UPDATE SET 
                        summary = EXCLUDED.summary, 
                        updated_at = EXCLUDED.updated_at,
                        last_summary_turn = EXCLUDED.last_summary_turn
                """, customer_phone, new_summary, self._get_malaysia_time(), last_summary_turn)
                        
        except Exception as e:
            print(f"❌ Summarization error: {e}")
    
    def _generate_session_id(self) -> str:
        """Generate a new session ID"""
        return str(uuid.uuid4())


# Global service instance
memory_service = MemoryService()