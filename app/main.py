"""
MinaAI RAG Chatbot - FastAPI Application
Simple RAG chatbot for customer service using phone numbers as customer identifiers
"""

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database.postgres import init_database, close_database
from app.routers import chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    await init_database()
    print("🚀 MinaAI RAG Chatbot started successfully")
    yield
    # Shutdown
    await close_database()
    print("🛑 MinaAI RAG Chatbot shutdown complete")


def create_app() -> FastAPI:
    """Create FastAPI application"""
    
    app = FastAPI(
        title="MinaAI RAG Chatbot",
        description="Customer service chatbot with RAG capabilities",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure as needed
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(chat.router, prefix="/api", tags=["Chat"])
    
    return app


# Create app instance - this must be at module level for uvicorn to find it
app = create_app()

# Export the app instance
__all__ = ["app"]


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port="4022",
        reload=True
    )
