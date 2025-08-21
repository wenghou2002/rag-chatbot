# MinaAI RAG Chatbot

> **Advanced Retrieval-Augmented Generation chatbot with hybrid memory system, multi-intent analysis, and intelligent context selection**

A high-performance, production-ready chatbot built specifically for VitaLean Wellness, featuring state-of-the-art RAG architecture with vector search, dynamic system prompts, and sophisticated memory management.

## 🌟 Key Features

### 🧠 **Hybrid Memory System**
- **Turns 1-5**: Recent conversation context only
- **Turns 6+**: Smart hybrid mode (last 5 turns + AI-generated customer summary)
- **24h+ gaps**: Automatic session management with memory preservation
- **Zero data loss**: Complete conversation history permanently stored

### 🎯 **Multi-Intent Analysis** 
- **Smart intent detection**: Handles multiple intents in single queries
- **Examples**: "What does your company do and what products do you sell?" → `["company", "product"]`
- **AI-powered**: No hardcoded keywords, fully contextual understanding
- **Expandable**: Easy to add new intents (e.g., `["support", "billing"]`)

### 🔍 **Vector-Powered Context Retrieval**
- **Semantic search**: PostgreSQL + pgvector for intelligent product matching
- **Configurable similarity**: 0.25 threshold for broad supplement queries
- **Full data delivery**: Complete product information (no truncation) for maximum accuracy
- **Dynamic sections**: `PRODUCT_DATA` and `COMPANY_DATA` based on intent

### 🎛️ **Admin-Configurable System Prompts**
- **Database-driven**: Store custom system prompts in `company_info.system_prompt`
- **Hot-swappable**: Changes take effect immediately without code deployment
- **Fallback safety**: Automatic default prompt if custom prompt is empty
- **Business flexibility**: Marketing team can update chatbot personality

### ⚡ **Performance Optimizations**
- **Single DB query**: All memory context retrieved in one optimized call
- **Async architecture**: Background saves, non-blocking summarization
- **Multi-LLM pipeline**: GPT-4o-mini (understanding) + GPT-4 (responses) + GPT-3.5-turbo (summaries)
- **Malaysia timezone**: Native support for Asia/Kuala_Lumpur business hours

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+** (3.12 recommended for Windows)
- **PostgreSQL 14+** with pgvector extension
- **OpenAI API Key** with GPT-4 access

### 1. Clone & Install
```bash
git clone <repository-url>
cd minaai-rag-chatbot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

Create `.env.dev` for development:
```env
# Environment
ENVIRONMENT=development
DEBUG=true

# OpenAI Configuration
OPENAI_API_KEY=sk-your-openai-api-key-here
UNDERSTANDING_MODEL=gpt-4o-mini

# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=minaai_chatbot_dev
DB_USER=postgres
DB_PASSWORD=dev_password

# CRM Database (for products/company data)
CRM_DB_HOST=localhost
CRM_DB_PORT=5432
CRM_DB_NAME=minaai_crm_dev
CRM_DB_USER=postgres
CRM_DB_PASSWORD=dev_password

# Performance Settings
MAX_CONVERSATION_TURNS=5
SUMMARIZATION_THRESHOLD=6
HYBRID_MEMORY_THRESHOLD=6
```

### 3. Database Setup
```bash
# Start PostgreSQL with pgvector (using Docker)
docker-compose up -d

# Create development database
createdb minaai_chatbot_dev

# Run schema setup
psql -d minaai_chatbot_dev -f database_setup.sql

# Verify pgvector extension
psql -d minaai_chatbot_dev -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 4. Run Development Server
```bash
# Option 1: Direct uvicorn
python -m uvicorn app.main:app --host 0.0.0.0 --port 4022 --reload --env-file .env.dev

# Option 2: Using run script
python run.py
```

### 5. Test the API

**Endpoint**: `POST http://localhost:4022/api/chat`

**Request Example**:
```json
{
  "message": "What metabolism supplements do you sell?",
  "phone_number": "60123456789"
}
```

**Response**:
```json
{
  "response": "We have several metabolism boosters including Vitalean MetaboPro+ (RM210)...",
  "phone_number": "60123456789",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "datatollm": "{\"PRODUCT_DATA\":[\"1. Vitalean MetaboPro+...\"]}"
}
```

## 📁 Project Structure

```
minaai-rag-chatbot/
├── app/
│   ├── main.py                    # FastAPI app with lifespan management
│   ├── routers/
│   │   └── chat.py                # HTTP endpoint (/api/chat)
│   ├── main_flow/
│   │   └── chatbot_flow.py        # 🎯 ORCHESTRATOR: Main business logic flow
│   ├── services/
│   │   ├── memory_service.py      # 🧠 Hybrid memory + session management
│   │   ├── understanding.py      # 🔍 Multi-intent analysis (GPT-4o-mini)
│   │   ├── context_service.py     # 📚 Vector search + KB building
│   │   ├── embeddings.py          # 🔤 OpenAI embeddings generation
│   │   ├── openai_llm.py          # 🤖 Response generation (GPT-4)
│   │   └── summarizer.py          # 📝 Background summarization (GPT-3.5)
│   ├── database/
│   │   └── postgres.py            # 🗄️ Async connection pools (primary + CRM)
│   └── models/
│       └── chat_models.py         # 📋 Pydantic request/response models
├── database_setup.sql             # 🗃️ Database schema + indexes
├── docker-compose.yml             # 🐳 PostgreSQL with pgvector
├── requirements.txt               # 📦 Python dependencies
└── README.md                      # 📖 This documentation
```

## 🔧 Configuration Guide

### Memory Strategy Configuration

| **Conversation Stage** | **Memory Strategy** | **Description** |
|----------------------|-------------------|-----------------|
| **Turns 1-5** | Recent Only | Uses only the last 1-5 conversation turns |
| **Turns 6-10** | Hybrid Mode | Last 5 turns + AI-generated customer summary |
| **Turns 11+** | Advanced Hybrid | Last 5 turns + enriched customer profile |
| **24h+ Gap** | Resume Mode | New session with preserved long-term memory |

### System Prompt Configuration

Admins can customize chatbot behavior through the database:

```sql
-- Set custom system prompt
UPDATE company_info 
SET system_prompt = 'You are VitaLean Assistant, a friendly health expert...'
WHERE user_uuid = 'fc7e5ef0-2362-4619-8e60-b3ebe867ade2';

-- Remove custom prompt (fallback to default)
UPDATE company_info 
SET system_prompt = NULL
WHERE user_uuid = 'fc7e5ef0-2362-4619-8e60-b3ebe867ade2';
```

## 📊 Database Schema

### Core Tables

#### `chat_history` - Conversation Storage
```sql
CREATE TABLE chat_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_phone VARCHAR(20) NOT NULL,
    session_id UUID NOT NULL,
    user_question TEXT NOT NULL,
    llm_answer TEXT NOT NULL,
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `customer_memory` - Long-term Memory
```sql
CREATE TABLE customer_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_phone VARCHAR(20) UNIQUE NOT NULL,
    summary TEXT NOT NULL,
    total_conversations INTEGER DEFAULT 0,
    first_interaction TIMESTAMP,
    last_interaction TIMESTAMP,
    customer_type VARCHAR(50) DEFAULT 'new',
    interaction_frequency VARCHAR(20) DEFAULT 'low',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### CRM Tables

#### `products` - Product Information with Embeddings
```sql
CREATE TABLE products (
    id UUID PRIMARY KEY,
    name VARCHAR(255),
    summary TEXT,              -- Full product description
    embeddings vector(3072),   -- OpenAI text-embedding-3-large
    category VARCHAR(100),
    price DECIMAL(10,2),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

#### `company_info` - Company Data + Admin Configuration
```sql
CREATE TABLE company_info (
    id UUID PRIMARY KEY,
    user_uuid UUID,
    company_info TEXT,         -- Company description
    system_prompt TEXT,        -- 🔧 Admin-configurable chatbot prompt
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

## 🔄 Processing Flow Overview

### Request → Response Journey

1. **HTTP Request** (`chat.py`) → Validates input and routes to orchestrator
2. **Memory Retrieval** (`memory_service.py`) → Single optimized query for all context
3. **Intent Analysis** (`understanding.py`) → Multi-intent detection with GPT-4o-mini
4. **Context Building** (`context_service.py`) → Vector search + full product data
5. **Response Generation** (`openai_llm.py`) → GPT-4 with custom prompts
6. **Async Persistence** → Background saving and summarization

## 🚀 Production Deployment

### Docker Production
```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  app:
    build: .
    ports: ["4022:4022"]
    env_file: .env.prod
    command: python -m uvicorn app.main:app --host 0.0.0.0 --port 4022 --workers 4
    restart: unless-stopped
```

### Environment Variables
```env
# .env.prod
ENVIRONMENT=production
DEBUG=false
OPENAI_API_KEY=sk-prod-key
DB_HOST=your-prod-db
DB_PASSWORD=secure-password
WORKERS=4
```

## 🧪 Testing

### API Testing
```bash
curl -X POST http://localhost:4022/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What supplements help with metabolism?",
    "phone_number": "60123456789"
  }'
```

### Key Test Scenarios
1. **New Customer** → No memory, general responses
2. **Returning Customer** → Memory-aware conversations
3. **Multi-Intent Queries** → Combined product + company responses
4. **Memory Evolution** → Turn 6+ triggers summarization

## 🔍 Monitoring & Troubleshooting

### Key Metrics
- **Response Time**: Target <2000ms
- **Memory Retrieval**: <100ms with optimized queries
- **Vector Search**: Similarity scores >0.25
- **Summarization**: Triggers at turn 6+

### Common Issues
```bash
# Check embeddings exist
psql -c "SELECT COUNT(*) FROM products WHERE embeddings IS NOT NULL;"

# Verify custom prompts
psql -c "SELECT system_prompt FROM company_info;"

# Monitor conversation counts
psql -c "SELECT customer_phone, COUNT(*) FROM chat_history GROUP BY customer_phone;"
```

## 📋 API Reference

### `POST /api/chat`

**Request**:
```json
{
  "message": "string",      // Required: User question
  "phone_number": "string"  // Required: Customer ID
}
```

**Response**:
```json
{
  "response": "string",     // AI answer
  "phone_number": "string", // Customer ID
  "session_id": "string",   // Session UUID
  "datatollm": "string"     // Context data (JSON)
}
```

## 🤝 Contributing

### Development Guidelines
1. **Service Separation**: Business logic in services, not routers
2. **Memory Efficiency**: Optimized database queries
3. **Error Handling**: Graceful fallbacks
4. **Comprehensive Logging**: Emoji-tagged logs for easy scanning
5. **Type Safety**: Pydantic models everywhere

### Adding New Features

**New Intent Types**:
```python
# 1. Update understanding.py with new intent
# 2. Add context builder in context_service.py  
# 3. Update prompt logic in openai_llm.py
```

## 📜 License

**Proprietary** - Internal use for VitaLean Wellness only.

---

**Built with ❤️ for VitaLean Wellness by the MinaAI Team**

For detailed flow documentation, see [FLOW_DOCUMENTATION.md](FLOW_DOCUMENTATION.md)
