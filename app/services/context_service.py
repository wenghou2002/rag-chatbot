"""
Context Service
Builds KB sections from configured sources based on detected intent and query.
Extensible: add new sections (e.g., FAQ_KB) without changing routers or LLM code.
"""

from typing import Dict, List
import uuid
import os

from app.database.postgres import get_pool
from app.services.embeddings import embedding_service


class ContextService:
    def __init__(self):
        self.similarity_threshold = 0.25  # Lower threshold for broader supplement queries
        self.default_top_k = 5
        self.company_uuid = os.getenv("COMPANY_UUID", "fc7e5ef0-2362-4619-8e60-b3ebe867ade2")

    async def build_sections(self, intents: List[str], query: str, analysis: dict = None) -> Dict[str, List[str]]:
        sections: Dict[str, List[str]] = {}

        # Extract analysis data for intelligent context selection
        company_topics = analysis.get("company_topics", []) if analysis else []
        
        # Handle multiple intents from understanding service
        has_product_intent = "product" in intents
        has_company_intent = "company" in intents or bool(company_topics)
        has_general_intent = "general" in intents
        
        # Smart context selection based on analyzed intents
        if has_product_intent:
            sections["PRODUCT_DATA"] = await self._build_product_data(query)
            
        if has_company_intent:
            sections["COMPANY_DATA"] = await self._build_company_data()
            
        ## CHANGE HERE IF NEEDED
        # If general query with no specific intents, provide both contexts to be helpful
        # if has_general_intent and not has_product_intent and not has_company_intent:
        #     sections["COMPANY_DATA"] = await self._build_company_data()
            # Optional: could also add product data for general queries
            # sections["PRODUCT_DATA"] = await self._build_product_data(query)

        return sections

    async def _build_product_data(self, query: str) -> List[str]:
        return await self.get_product_context(query, limit=5)

    async def _build_company_data(self) -> List[str]:
        return await self.get_company_context()
    
    async def get_product_context(self, query: str, limit: int = 5) -> List[str]:
        """Get relevant context from products table only using vector search"""
        try:
            # Generate query embedding
            query_embedding = await embedding_service.generate_embedding(query)
            
            pool = get_pool("crm")
            async with pool.acquire() as conn:
                # Convert embedding list to PostgreSQL vector string format
                embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
                
                # Get products above threshold
                product_results = await conn.fetch("""
                    SELECT summary as content, 1 - (embeddings <=> $1::vector) as similarity
                    FROM products 
                    WHERE embeddings IS NOT NULL 
                    AND 1 - (embeddings <=> $1::vector) > $2
                    ORDER BY similarity DESC 
                    LIMIT $3
                """, embedding_str, self.similarity_threshold, limit)
                
                # Extract and compact content
                raw = [result['content'] for result in product_results]
                return self._compact_snippets(raw)
                
        except Exception as e:
            print(f"Product context retrieval failed: {e}")
            return []
    
    async def get_company_context(self) -> List[str]:
        """Get all company information directly (no vector search needed)"""
        try:
            pool = get_pool("crm")
            async with pool.acquire() as conn:
                # Get all company info directly (no created_at in our local setup)
                company_results = await conn.fetch("""
                    SELECT company_info as content 
                    FROM company_info
                    WHERE user_uuid = $1
                """, self.company_uuid)

                
                # Extract and compact a few most recent items
                raw = [result['content'] for result in company_results]
                return self._compact_snippets(raw)
                
        except Exception as e:
            print(f"Company context retrieval failed: {e}")
            return []

    def _compact_snippets(self, snippets: List[str]) -> List[str]:
        """Format snippets as numbered list for LLM consumption with full product data."""
        if not snippets:
            return []
        
        # Limit to max 5 products for token efficiency
        top_k = min(len(snippets), self.default_top_k)
        compact = []
        
        for i, s in enumerate(snippets[:top_k], 1):
            if s is None:
                continue
            
            # Send full product data for maximum accuracy - no truncation
            content = s.strip()
            
            # Format as numbered list for better LLM parsing
            formatted_product = f"{i}. {content}"
            compact.append(formatted_product)
        
        return compact

context_service = ContextService()


