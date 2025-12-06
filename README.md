# Shopify Translator API

A FastAPI-based backend for generating localized Shopify product descriptions using OpenAI, with built-in rate limiting, billing quotas, and streaming support.

## Project Structure

The source code is organized into the following modules under `src/main/`:

- **api/**: Contains the API entry points, controllers, and request models.
  - `main.py`: Application entry point and startup.
  - `controller.py`: Route definitions and endpoint logic.
  - `models.py`: Pydantic models for request/response validation.
- **config/**: Application configuration.
  - `configs.py`: Constants and environment variable loading.
- **db/**: Database interaction layer.
  - `database.py`: SQLAlchemy session and engine setup.
  - `db_models.py`: Database schema definitions (User, Plan, APIKey, UsageRecord).
  - `db_transactions.py`: Helper functions for DB read/write operations.
- **service/**: External service integrations and business logic.
  - `services.py`: OpenAI API integration.
  - `streaming_utils.py`: Utilities for handling streaming responses.
- **security/**: Authentication and protection.
  - `security.py`: JWT validation (Shopify) and API Key hashing (Usage).
  - `ratelimiter.py`: In-memory rate limiting implementation.
- **logging/**: Logging configuration.
  - `logger.py`: Centralized logger setup.

## Features

- **Dual Authentication**:
  - **Shopify JWT**: Authenticates the app installation/admin context (`/api/admin/me`).
  - **API Key**: Authenticates and bills requests (`/api/generate-copy`).
- **Usage Tracking**: Atomically tracks token usage per API key against a monthly quota defined in the `Plan`.
- **Streaming Support**: Optional Server-Sent Events (SSE) streaming for generated copy (`stream: true`).
- **Rate Limiting**: In-memory rate limiter to prevent abuse.
- **Dockerized**: Fully containerized with Docker Compose (App + PostgreSQL).

## Getting Started

### Prerequisites
- Docker & Docker Compose
- OpenAI API Key
- Shopify App Credentials

### Setup

1. **Clone the repository**
2. **Create a .env file**
   ```bash
   OPENAI_API_KEY=sk-...
   SHOPIFY_API_KEY=...
   SHOPIFY_API_SECRET=...
   # DATABASE_URL is handled automatically by Docker Compose
   ```
3. **Run with Docker Compose**
   ```bash
   docker-compose up --build
   ```
   The API will be available at `http://localhost:8000`.

### Database Seeding

To populate the database with initial plans and a test user/key:
```bash
docker-compose run --rm web python -m scripts.seed_db
```
This creates a "Basic Agent" plan, a user `dev-shop.myshopify.com`, and a test API Key (raw: `dev-token-123`).

### Testing

**Generate Copy (Streaming)**
```bash
curl -N -X POST "http://localhost:8000/api/generate-copy" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer dev-token-123" \
     -d '{
           "product_name": "Test Product",
           "japanese_description": "Great product.",
           "category": "General",
           "stream": true
         }'
```

**Check Admin Info**
```bash
curl -H "Authorization: Bearer dev-token-123" http://localhost:8000/api/admin/me
```
