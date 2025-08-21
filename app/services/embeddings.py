"""
Embeddings Service
Handles text embeddings and vector search using pgvector
"""

import uuid
from openai import AsyncOpenAI
from typing import List, Dict, Any
import os
from app.database.postgres import get_pool

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class EmbeddingService:
    def __init__(self):
        self.embedding_model = "text-embedding-3-large"
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text"""
        try:
            response = await client.embeddings.create(
                model=self.embedding_model,
                input=text,
            )
            return response.data[0].embedding  # type: ignore[attr-defined]
        except Exception as e:
            raise Exception(f"Embedding generation failed: {str(e)}")
    
# Global service instance
embedding_service = EmbeddingService()

