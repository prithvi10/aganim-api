# Shopify Translator API

A robust FastAPI-based backend designed to generate localized, high-quality English product descriptions from Japanese inputs for Shopify stores. This service leverages OpenAI for content generation and includes enterprise-grade features like rate limiting, usage-based billing quotas, and response streaming.

## 🚀 Overview

This application serves as the backend for a Shopify App. It provides two main interfaces:
1.  **Public API**: Used by the store's frontend or background workers to generate content, authenticated via API Keys.
2.  **Admin API**: Used for app configuration and setup, authenticated via Shopify Session Tokens (JWT).

## ✨ Key Features

*   **AI-Powered Translation**: Context-aware translation using OpenAI's GPT models.
*   **Dual Authentication Strategy**:
    *   **Shopify JWT** for secure admin access.
    *   **Hashed API Keys** for secure, quota-tracked API usage.
*   **Granular Quota Management**:
    *   Plans define monthly token limits and feature access (e.g., Streaming).
    *   Real-time tracking of token usage per billing cycle.
    *   Automatic blocking when quotas are exceeded.
*   **Rate Limiting**: In-memory sliding window rate limiter to prevent abuse.
*   **Streaming Support**: Server-Sent Events (SSE) for real-time content generation feedback.
*   **Dockerized**: Production-ready Docker Compose setup with PostgreSQL.

## 📡 API Contracts

### 1. Generate Copy (Public/Client)
Generates marketing copy. Supports both standard JSON responses and Streaming (SSE).

*   **Endpoint**: `POST /api/generate-copy`
*   **Authentication**: `Authorization: Bearer <YOUR_API_KEY>`
*   **Request Body** (`application/json`):
    ```json
    {
      "product_name": "Premium Ceramic Mug",
      "japanese_description": "このマグカップは高品質なセラミックで作られています。",
      "category": "Kitchenware",
      "stream": false
    }
    ```
    *   `stream` (bool): Set to `true` to receive a Server-Sent Events stream.

*   **Response (Standard)**:
    ```json
    {
      "status": "success",
      "english_copy": "Crafted from high-quality ceramic, this premium mug..."
    }
    ```

*   **Response (Streaming)**: Returns a stream of chunks.

### 2. Admin Info (Admin)
Verifies the Shopify session and returns context.

*   **Endpoint**: `GET /api/admin/me`
*   **Authentication**: `Authorization: Bearer <SHOPIFY_SESSION_TOKEN>`
*   **Response**:
    ```json
    {
      "status": "authenticated",
      "shop": "my-store.myshopify.com",
      "message": "Welcome to the Admin API"
    }
    ```

## 🗄️ Database Models

The application uses **SQLAlchemy** with **PostgreSQL**.

*   **User**: Represents a Shopify Merchant. Links to a `Plan` and holds multiple `APIKey`s.
*   **Plan**: Defines the service tier.
    *   `monthly_token_quota`: Max tokens allowed per month.
    *   `max_request_rate`: Rate limit threshold.
    *   `can_stream_responses`: Feature flag for streaming.
*   **APIKey**: Credentials for the Public API.
    *   `key_hash`: SHA-256 hash of the raw key (raw keys are never stored).
*   **UsageRecord**: Tracks usage.
    *   Composite Key: `api_key_id` + `billing_cycle_start`.
    *   `token_count`: Atomically incremented counter.

## 🔒 Security Features

1.  **API Key Hashing**: Raw API keys are hashed using SHA-256 before storage. The database only contains hashes, ensuring keys cannot be leaked if the DB is compromised.
2.  **Shopify JWT Verification**: Admin endpoints verify the signature, expiration, and audience of Shopify Session Tokens using `pyjwt`.
3.  **Rate Limiting**: An `InMemoryRateLimiter` protects endpoints. Configuration is flexible (e.g., `{"limit": 10, "window": 60}` allows 10 requests per minute).
4.  **Quota Enforcement**: Every request to `/api/generate-copy` verifies the user's monthly token usage against their plan's quota in real-time.

## 🐳 Docker & Setup

The project is fully containerized.

### Prerequisites
*   Docker & Docker Compose
*   OpenAI API Key
*   Shopify App Credentials

### Configuration (.env)
Create a `.env` file in the root:
```bash
OPENAI_API_KEY=sk-...
SHOPIFY_API_KEY=your_shopify_client_id
SHOPIFY_API_SECRET=your_shopify_client_secret
# DATABASE_URL is set in docker-compose.yml
```

### Running the App
```bash
docker-compose up --build
```
*   **API**: http://localhost:8000
*   **Database**: Postgres on port 5432

## 🧪 Testing

The project maintains a high standard of testing using `pytest`.

### Running Tests
```bash
# Install dependencies locally or run inside container
pip install -r requirements.txt
pytest
```

### Current Test Coverage
*   **Integration Tests**: Verify the full flow from API call -> DB Quota Check -> (Mock) OpenAI -> DB Usage Update.
*   **DB Transaction Tests**: Verify ACID properties of quota updates and concurrency safety.
*   **Security Tests**: Verify JWT validation and API Key hashing.
*   **Status**: ✅ All Tests Passing
*   **Coverage**: 93% overall

### Sample Test Result
```text
src/test/test_db_transactions.py::test_verify_api_key_valid PASSED
src/test/test_db_transactions.py::test_verify_quota_exceeded PASSED
src/test/test_integration.py::test_integration_generate_copy_flow PASSED
```
### CICD
A. The CI Job (test)
This job runs on a fresh virtual machine hosted by GitHub (the Runner).

* `actions/checkout@v4`: Downloads your code from the repository.

* `actions/setup-python@v5`: Configures the Python environment.

* `pip install -r requirements.txt`: Installs your dependencies (FastAPI, SQLAlchemy, etc.).

* `pytest`: Executes all your unit tests (e.g., test_rate_limiter.py). If any test fails, the workflow stops immediately.

B. The CD Job (deploy)
This job is very simple because Render handles the heavy lifting.

* `needs: test`: Ensures this job only starts if the test job passed successfully.

* `if: github.ref == 'refs/heads/main'`: Prevents deployment when someone just opens a Pull Request; deployment only happens when the final code is merged into main.

* `curl`: Sends a POST request to your secret RENDER_DEPLOY_HOOK_URL. This signal tells Render: "A new version of the code is ready, please pull the latest changes, build, and deploy."