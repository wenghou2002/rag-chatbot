"""
Memory Service
Handles conversation history and customer memory using PostgreSQL
Implements your memory strategy:
- Turns 1-5: Use only recent turns (1-5)
- Turn 6: Creates summary of turns 1-5, uses turns 1-5
- Turn 7: Summary + 1 turn (turn 6)
- Turn 8: Summary + 2 turns (turns 6-7)
- Turn 9: Summary + 3 turns (turns 6-8)
- Turn 10: Summary + 4 turns (turns 6-9)
- Turn 11: Summary + 5 turns (turns 6-10) + GENERATE NEW SUMMARY
- Turn 12: New summary + 1 turn (turn 11)
- And so on...
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
        self.summary_cycle_length = 5  # Create new summary every 5 turns after the first one
    
    def get_malaysia_time(self) -> datetime:
        """Get current time in Malaysia timezone (UTC+8) as naive datetime"""
        utc_time = datetime.now(timezone.utc)
        malaysia_time = utc_time + timedelta(hours=8)
        return malaysia_time.replace(tzinfo=None)
    
    async def get_conversation_context_optimized(self, customer_phone: str) -> Tuple[List[Dict[str, str]], str, Optional[str], bool]:
        """
        MAIN METHOD: Get all memory context in ONE optimized database call
        
        Memory Strategy (Your Pattern):
        - Turns 1-5: Recent context only
        - Turn 6: Creates summary of turns 1-5, uses turns 1-5
        - Turn 7: Summary + 1 turn (turn 6)
        - Turn 8: Summary + 2 turns (turns 6-7)
        - Turn 9: Summary + 3 turns (turns 6-8)
        - Turn 10: Summary + 4 turns (turns 6-9)
        - Turn 11: Summary + 5 turns (turns 6-10) + GENERATE NEW SUMMARY
        - Turn 12: New summary + 1 turn (turn 11)
        - And so on...
        - 24h+ & <=5 turns: Last 1-5 turns from previous session + trigger summary
        - 24h+ & >5 turns: Summary only (hybrid long-term)
        
        Note: last_summary_turn represents the last turn INCLUDED in the summary
        Example: Turn 6 generates summary of turns 1-5, last_summary_turn = 5
        For turn 7: turns_since_summary = 7-5 = 2, include 1 recent turn (turn 6)
        For turn 8: turns_since_summary = 8-5 = 3, include 2 recent turns (turns 6-7)
        
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
                        SELECT summary, total_conversations, last_summary_turn
                        FROM customer_memory 
                        WHERE customer_phone = $1
                    )
                    SELECT 
                        lc.session_id,
                        lc.created_at,
                        lc.session_turn_count,
                        cd.summary,
                        cd.total_conversations,
                        cd.last_summary_turn
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
                    return await self._handle_expired_session(
                        conn, customer_phone, result, now_malaysia
                    )
                
                # Active session - get recent conversation history
                return await self._handle_active_session(
                    conn, customer_phone, result, now_malaysia
                )
                
        except Exception as e:
            print(f"❌ Error in optimized memory context: {e}")
            # Return safe defaults on error
            return [], self.generate_session_id(), None, False
    
    async def _handle_expired_session(
        self, 
        conn, 
        customer_phone: str, 
        result: dict, 
        now_malaysia: datetime
    ) -> Tuple[List[Dict[str, str]], str, Optional[str], bool]:
        """Handle expired session logic - return previous turns if <=5, summary if >5"""
        print(f"⏰ Session expired, starting new session")
        
        previous_session_id = str(result['session_id'])
        previous_session_turns = result['session_turn_count'] or 0
        new_session_id = self.generate_session_id()
        
        # If <=5 turns, return those turns for continuity and trigger summary
        if previous_session_turns <= self.max_conversation_turns:
            print(f"📦 Restoring last {min(previous_session_turns, self.max_conversation_turns)} turn(s) from previous session")
            
            conversation_history = await self._fetch_conversation_history(
                conn, customer_phone, previous_session_id, self.max_conversation_turns
            )
            
            # Trigger background summary generation for future chats
            asyncio.create_task(
                self._summarize_conversations_background(customer_phone, previous_session_id)
            )
            
            # Include existing summary if available
            customer_summary = self._format_customer_summary(
                result['summary'], 
                result['total_conversations'], 
                result['created_at'],
                now_malaysia
            )
            
            use_hybrid = bool(customer_summary)
            return conversation_history, new_session_id, customer_summary, use_hybrid
        
        # >5 turns already summarized: return long-term memory only
        customer_summary = self._format_customer_summary(
            result['summary'], 
            result['total_conversations'], 
            result['created_at'],
            now_malaysia
        )
        return [], new_session_id, customer_summary, True
    
    async def _handle_active_session(
        self, 
        conn, 
        customer_phone: str, 
        result: dict, 
        now_malaysia: datetime
    ) -> Tuple[List[Dict[str, str]], str, Optional[str], bool]:
        """Handle active session logic - use sliding window approach for efficiency"""
        session_id = str(result['session_id'])
        session_turn_count = result['session_turn_count'] or 0
        last_summary_turn = result.get('last_summary_turn') or 0
        
        # Determine memory strategy based on turn count
        use_hybrid = session_turn_count >= self.hybrid_memory_threshold
        customer_summary = None
        
        if use_hybrid:
            # Use hybrid mode: summary + recent turns since last summary
            customer_summary = self._format_customer_summary(
                result['summary'], 
                result['total_conversations'], 
                result['created_at'],
                now_malaysia
            )
            
            # Simple logic: get turns after the summary
            # last_summary_turn = 5 means turns 1-5 are summarized
            # Turn 7: get turns from turn 6 onwards (1 turn)
            # Turn 8: get turns from turn 6 onwards (2 turns)
            # Turn 9: get turns from turn 6 onwards (3 turns)
            turns_after_summary = session_turn_count - last_summary_turn
            recent_turns_to_include = min(turns_after_summary, 5)  # Max 5 turns
            
            print(f"🔍 Your pattern calculation:")
            print(f"   → Current turn: {session_turn_count}")
            print(f"   → Last summary turn: {last_summary_turn} (last turn INCLUDED in summary)")
            print(f"   → Turns after summary: {turns_after_summary}")
            print(f"   → Recent turns to include: {recent_turns_to_include}")
            
            if recent_turns_to_include > 0:
                print(f"🔍 Fetching {recent_turns_to_include} recent turns after summary...")
                conversation_history = await self._fetch_conversation_history(
                    conn, customer_phone, session_id, recent_turns_to_include
                )
                print(f"🔄 Using HYBRID memory: summary + {len(conversation_history)} recent turns (sliding window)")
                if conversation_history:
                    print(f"   → Recent turns: {[f'turn {i+1}' for i in range(len(conversation_history))]}")
            else:
                # Turn 6: Show turns 1-5 conversation history (before summary)
                if session_turn_count == 6:
                    print(f"🔍 Turn 6: Fetching turns 1-5 conversation history...")
                    conversation_history = await self._fetch_conversation_history(
                        conn, customer_phone, session_id, 5
                    )
                    print(f"🔄 Turn 6: Summary + {len(conversation_history)} turns (1-5)")
                else:
                    conversation_history = []
                    print(f"🔄 Using HYBRID memory: summary only (no recent turns needed)")
        else:
            # Recent memory only: fetch last 5 turns
            conversation_history = await self._fetch_conversation_history(
                conn, customer_phone, session_id, self.max_conversation_turns
            )
            print(f"📋 Using recent memory only: {len(conversation_history)} turns")
        
        print(f"📝 History length: {len(conversation_history)}, Session ID: {session_id}")
        
        return conversation_history, session_id, customer_summary, use_hybrid
    
    async def _fetch_conversation_history(
        self, 
        conn, 
        customer_phone: str, 
        session_id: str, 
        limit: int
    ) -> List[Dict[str, str]]:
        """Fetch conversation history and format it consistently"""
        # Simple logic: get the most recent turns
        # For turn 7: get 1 turn (turn 6)
        # For turn 8: get 2 turns (turns 6-7)
        # For turn 9: get 3 turns (turns 6-8)
        
        print(f"🔍 Fetching {limit} most recent turns...")
        
        history_results = await conn.fetch("""
            SELECT user_question, llm_answer, created_at
            FROM chat_history 
            WHERE customer_phone = $1 AND session_id = $2
            ORDER BY created_at DESC 
            LIMIT $3
        """, customer_phone, uuid.UUID(session_id), limit)
        
        print(f"🔍 Got {len(history_results)} turns")
        
        # Build conversation history in chronological order (oldest first)
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
            # Defensive: ensure llm_answer is a string if a dict was passed accidentally
            if isinstance(llm_answer, dict):
                llm_answer = (
                    llm_answer.get("response")
                    or llm_answer.get("content")
                    or str(llm_answer)
                )
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
                    
                    # Trigger summarization at the correct threshold (your pattern)
                    # Turn 6: First summary, then every 5 turns after that (11, 16, 21, etc.)
                    should_trigger_summary = (
                        session_turn_count == 6 or  # First summary at turn 6
                        (session_turn_count > 6 and (session_turn_count - 6) % 5 == 0)  # Every 5 turns after 6
                    )
                    
                    print(f"🔍 Summarization check: turn {session_turn_count}, should trigger: {should_trigger_summary}")
                    if session_turn_count == 6:
                        print(f"   → First summary trigger at turn 6")
                    elif session_turn_count > 6:
                        cycles_since_first = (session_turn_count - 6) // 5
                        next_trigger = 6 + (cycles_since_first + 1) * 5
                        print(f"   → {cycles_since_first} cycles since first summary, next trigger at turn {next_trigger}")
                    
                    if should_trigger_summary:
                        print(f"🧠 Triggering summarization at {session_turn_count} turns (your pattern cycle)")
                        asyncio.create_task(
                            self._summarize_conversations_background(customer_phone, session_id, session_turn_count)
                        )
                    else:
                        print(f"⏭️ No summarization needed at turn {session_turn_count}")
                    
        except Exception as e:
            print(f"❌ Error saving chat to DB: {e}")
            import traceback
            traceback.print_exc()
    
    async def _summarize_conversations_background(self, customer_phone: str, session_id: str, current_turn: int = None):
        """Background task to summarize conversations using sliding window approach"""
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
                
                if len(conversations) < 1:  # Allow summarization of any length
                    print(f"⏭️ No conversations found to summarize")
                    return
                
                # Convert to format expected by summarizer
                conversation_data = []
                for conv in conversations:
                    conversation_data.append({
                        "user_message": conv['user_question'],
                        "ai_response": conv['llm_answer']
                    })
                
                # Get existing summary efficiently
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
                
                # Save the updated summary with the current turn number
                # last_summary_turn should represent the last turn INCLUDED in the summary
                # For your pattern: Turn 6 creates summary of turns 1-5, so last_summary_turn = 5
                # Turn 7: Summary + 1 turn (turn 6) = 1 turn since summary (7-5 = 2, include 1 turn)
                # Turn 8: Summary + 2 turns (turns 6-7) = 2 turns since summary (8-5 = 3, include 2 turns)
                # Turn 11: Summary + 5 turns (turns 6-10) + generate new summary
                last_summary_turn = (current_turn or len(conversations)) - 1  # The last turn INCLUDED in summary
                await conn.execute("""
                    INSERT INTO customer_memory (customer_phone, summary, total_conversations, first_interaction, last_interaction, customer_type, interaction_frequency, updated_at, last_summary_turn)
                    VALUES ($1, $2, 1, $3, $3, 'new', 'low', $3, $4)
                    ON CONFLICT (customer_phone)
                    DO UPDATE SET 
                        summary = EXCLUDED.summary, 
                        updated_at = EXCLUDED.updated_at,
                        last_summary_turn = EXCLUDED.last_summary_turn
                """, customer_phone, new_summary, self.get_malaysia_time(), last_summary_turn)
                
                print(f"✅ Customer summary updated successfully (length: {len(new_summary)} chars)")
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