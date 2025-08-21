"""
Chatbot Flow Service
Orchestrates the complete chat flow by calling existing services
Acts as a coordinator between router and business logic services
"""

import time
import json
from typing import Dict, Any
from app.models.chat_models import ChatRequest, ChatResponse
from app.services.openai_llm import openai_service
from app.services.memory_service import memory_service
from app.services.understanding import understanding_service
from app.services.context_service import context_service


class ChatbotFlowService:
    """
    Orchestrates the complete chatbot flow using existing services
    """
    
    async def process_chat_message(self, request: ChatRequest) -> ChatResponse:
        """
        Orchestrate the complete chat processing flow
        
        Args:
            request: ChatRequest containing phone_number and message
            
        Returns:
            ChatResponse with AI response and metadata
        """
        start_time = time.time()
        
        print(f"📞 Processing chat for phone: {request.phone_number}")
        print(f"💬 Message: {request.message}")
        
        # Performance monitoring
        memory_start = time.time()
        
        # Step 1: Get ALL memory context in ONE optimized call
        conversation_history, session_id, customer_summary, use_hybrid = await memory_service.get_conversation_context_optimized(
            request.phone_number
        )

        # Step 2: Log memory strategy and performance (will be remove later)
        memory_time = int((time.time() - memory_start) * 1000)
        print(f"📝 Memory: {len(conversation_history)} turns, {memory_time}ms, Session: {session_id}")
        
        if use_hybrid and conversation_history:
            print(f"🔄 Using HYBRID memory: {len(conversation_history)} recent turns + long-term summary")
        elif customer_summary:
            print(f"🧠 Using long-term memory only")
        else:
            print(f"🆕 New customer - no memory available")
        
        # Step 3: Analyze message intent and query augmentation (expanded_query)
        print("🔎 Analyzing message intent...")
        analysis = await understanding_service.analyze(
            current_message=request.message,
            last_turns=conversation_history,
        )
        print(f"🎯 Analysis result: {analysis}")
        
        # Step 4: Build knowledge base sections
        intents = analysis.get("intents", [analysis.get("intent")]) if analysis.get("intent") else analysis.get("intents", [])
        expanded_query = analysis.get("expanded_query") or request.message
        print(f"📚 Building KB sections for intents: {intents}, query: {expanded_query}")
        kb_sections = await context_service.build_sections(
            intents=intents, 
            query=expanded_query, 
            analysis=analysis,
            uuid=request.uuid #testing purpose only needed to be remove
        )
        
        # Step 5: Generate AI response
        print("🤖 Generating OpenAI response...")
        ai_response = await openai_service.generate_response(
            message=request.message,
            conversation_history=conversation_history,
            customer_summary=customer_summary,
            kb_sections=kb_sections,
            intents=intents,
            uuid=request.uuid #testing purpose only needed to be remove
        )
        print(f"✅ AI Response generated: {len(ai_response)} chars")
        
        # Step 6: Calculate metrics and prepare response
        response_time_ms = int((time.time() - start_time) * 1000)
        print(f"⏱️ Total response time: {response_time_ms}ms")
        
        print("📤 Preparing response...")
        response = ChatResponse(
            datatollm=json.dumps(kb_sections) if kb_sections else None,
            response=ai_response,
            phone_number=request.phone_number,
            session_id=session_id
        )
        print("✅ Response prepared successfully")
        
        # Step 7: Save conversation asynchronously
        print("💾 Saving chat asynchronously...")
        memory_service.save_chat_async(
            customer_phone=request.phone_number,
            session_id=session_id,
            user_question=request.message,
            llm_answer=ai_response,
            response_time_ms=response_time_ms,
        )
        print("✅ Chat saved to background task")
        
        print("✅ Chat processing completed successfully")
        return response


# Create a singleton instance to be used by the router
chatbot_flow_service = ChatbotFlowService()
