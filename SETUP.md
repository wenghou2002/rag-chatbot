# MinaAI RAG Chatbot Setup Guide

Follow these steps to get the chatbot running locally.

## 1) Install prerequisites

- Python 3.11 or 3.12 recommended
- PostgreSQL 14+ with `pgvector` extension
- OpenAI API key

Windows notes:
- If you’re on Python 3.13 and encounter build errors, prefer Python 3.12 or ensure packages have prebuilt wheels.
- Avoid compiling native wheels by keeping `pydantic>=2.6.0` and a recent `asyncpg`.

## 2) Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## 3) Configure environment
Create `.env` at project root with:
```
OPENAI_API_KEY=sk-...
DB_HOST=localhost
DB_PORT=5432
DB_NAME=minaai_chatbot
DB_USER=postgres
DB_PASSWORD=password

# Optional separate CRM DB (defaults to primary DB if omitted)
CRM_DB_HOST=
CRM_DB_PORT=
CRM_DB_NAME=
CRM_DB_USER=
CRM_DB_PASSWORD=
```

## 4) Initialize database
Ensure `pgvector` is available, then:
```bash
createdb minaai_chatbot
psql -d minaai_chatbot -f database_setup.sql
```

## 5) Run the API
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 4022 --reload
# or
python run.py
```

## 6) Test in Postman
- Method: POST
- URL: http://localhost:4022/api/chat
- Headers: `Content-Type: application/json`

Without phone number (no memory or persistence):
```json
{
  "input": "Hello, what are your delivery options?",
  "id": "4b7f0a2e-8f9c-4c9a-bd2e-9a2c8a2b6b11"
}
```

With phone number (enables memory + persistence):
```json
{
  "input": "Hello, what are your delivery options?",
  "id": "4b7f0a2e-8f9c-4c9a-bd2e-9a2c8a2b6b11",
  "phone_number": "60123456789"
}
```

## Database tables (created by database_setup.sql)

- `products(id, name, summary, embedding, metadata, created_at, updated_at)`
- `company_info(id, title, summary, embedding, category, created_at, updated_at)`
- `chat_history(id, customer_phone, session_id, user_question, llm_answer, response_time_ms, created_at)`
- `customer_memory(id, customer_phone, summary, total_conversations, first_interaction, last_interaction, customer_type, interaction_frequency, updated_at)`

## Troubleshooting

- Ensure `CREATE EXTENSION IF NOT EXISTS vector;` runs successfully in your DB.
- OpenAI: confirm `OPENAI_API_KEY` is set and reachable in the app environment.
- Windows build errors: prefer Python 3.12; otherwise install MSVC Build Tools if a package needs compilation.
