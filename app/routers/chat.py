"""
Chat API Router
HTTP entry point for chat endpoints
Handles routing, validation, and HTTP concerns only
Business logic is delegated to chatbot_flow service
"""

from fastapi import APIRouter, HTTPException
from app.models.chat_models import ChatRequest, ChatResponse
from app.main_flow.chatbot_flow import chatbot_flow_service

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_message(request: ChatRequest):
    """
    Chat API endpoint
    
    Handles HTTP concerns and delegates business logic to chatbot_flow service
    
    Args:
        request: ChatRequest with phone_number and message
        
    Returns:
        ChatResponse with AI response and metadata
        
    Raises:
        HTTPException: If chat processing fails
    """
    try:
        # Delegate all business logic to the chatbot flow service
        response = await chatbot_flow_service.process_chat_message(request)
        return response
        
    except Exception as e:
        print(f"❌ Error in chat API: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail=f"Chat processing failed: {str(e)}"
        )

