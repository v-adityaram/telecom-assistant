# Telecom AI Assistant --- Final Implementation Plan

## Objective

Build a lightweight telecom customer assistant POC supporting **both
Chat and Realtime Voice**, optimized for low latency and secure
customer/API access.

The application will run on a **1 GB Ubuntu Azure VM**. The VM should
host only the lightweight backend/gateway layer; do not run a local LLM.

------------------------------------------------------------------------

## 1. Final Architecture

``` text
                         USER
                      /        \
                   CHAT        VOICE
                     \          /
                      \        /
                   FastAPI Gateway
                         |
                         v
                 Fast Intent Router
                         |
             +-----------+-----------+
             |           |           |
          HIGH          LOW       COMPLEX
        CONFIDENCE    CONFIDENCE   REQUEST
             |           |           |
             v           v           v
        Direct API   Clarification  LangGraph
             |           |           |
             +-----------+-----------+
                         |
                         v
                  Secure Tool Layer
                         |
                         v
                   Telecom APIs
```

### Core principle

> **Deterministic-first, AI-when-needed, clarification-when-uncertain,
> and one shared secure backend for Chat and Voice.**

### Do not change these architectural decisions

1.  Chat and Voice share the same backend/tool/business logic.
2.  Simple requests use the fast direct path.
3.  Low-confidence or ambiguous requests trigger clarification.
4.  No telecom API call is made when intent is uncertain.
5.  No separate spell-checking service.
6.  LangGraph is a fallback for complex/multi-step requests.
7.  Independent API calls run concurrently where possible.
8.  The backend owns customer identity and authorization.
9.  The LLM must never control or override the authorized
    `mobileNumber`.
10. The model cannot call arbitrary URLs/tools.
11. Telecom API credentials stay server-side.
12. No local LLM on the 1 GB VM.

------------------------------------------------------------------------

# 2. Telecom POC APIs

The POC has five APIs:

1.  Profile
2.  Device Details
3.  Balance
4.  Purchase History
5.  Offers

All use `mobileNumber` as the customer identifier.

**Important:** the supplied Postman collection is the source of truth
for the API contracts. Claude Code must inspect it before implementing
clients and must not invent endpoint URLs, HTTP methods, query
parameters, headers, authentication, or response schemas.

------------------------------------------------------------------------

# 3. Project Structure

Keep the application lightweight.

``` text
telecom-assistant/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── chat.py
│   │   ├── voice.py
│   │   ├── health.py
│   ├── router/
│   │   ├── intent_router.py
│   │   ├── schemas.py
│   │   ├── confidence.py
│   ├── tools/
│   │   ├── profile.py
│   │   ├── device.py
│   │   ├── balance.py
│   │   ├── purchase_history.py
│   │   ├── offers.py
│   ├── services/
│   │   ├── llm.py
│   │   ├── customer_context.py
│   │   ├── response.py
│   ├── security/
│       ├── auth.py
│       ├── authorization.py
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── Dockerfile
├── README.md
```

Do not create unnecessary microservices or infrastructure for this POC.

------------------------------------------------------------------------

# 4. Phase 1 --- FastAPI Foundation

Implement:

-   FastAPI application
-   Configuration
-   Environment-variable loading
-   Pydantic models
-   Structured logging
-   Global exception handling
-   CORS where required
-   Health endpoint

Endpoint:

``` text
GET /health
```

Expected response:

``` json
{
  "status": "ok"
}
```

### Acceptance criteria

-   Application starts successfully.
-   `/health` responds.
-   No secrets are hardcoded.
-   Health endpoint has a test.

------------------------------------------------------------------------

# 5. Phase 2 --- Telecom API Clients

Inspect the Postman collection first.

Create typed asynchronous clients/tools:

``` text
get_profile()
get_device_details()
get_balance()
get_purchase_history()
get_offers()
```

Each tool must:

1.  Accept validated parameters.
2.  Obtain customer context from the backend.
3.  Never trust model-provided customer identity.
4.  Call only configured telecom endpoints.
5.  Use explicit HTTP timeouts.
6.  Handle 4xx/5xx/timeout failures safely.
7.  Return structured data.
8.  Never expose credentials in logs/errors.

Use an async HTTP client.

------------------------------------------------------------------------

# 6. Phase 3 --- Secure Tool Layer

Create an explicit allow-list:

``` text
PROFILE          -> get_profile
DEVICE_DETAILS   -> get_device_details
BALANCE          -> get_balance
PURCHASE_HISTORY -> get_purchase_history
OFFERS           -> get_offers
```

Correct:

``` text
Model
  |
  v
BALANCE
  |
  v
Backend allow-list
  |
  v
get_balance()
```

Incorrect:

``` text
Model
  |
  v
"Call this URL"
  |
  v
Arbitrary HTTP request
```

The model must never be able to execute arbitrary HTTP requests, shell
commands, URLs, or functions.

------------------------------------------------------------------------

# 7. Phase 4 --- Intent Router

Implement a fast intent router.

Supported intents:

``` text
PROFILE
DEVICE_DETAILS
BALANCE
PURCHASE_HISTORY
OFFERS
UNKNOWN
```

Router output:

``` json
{
  "intent": "BALANCE",
  "confidence": 0.98,
  "needs_clarification": false,
  "parameters": {}
}
```

Examples:

``` text
"What's my balance?"
"what is my balence?"
"how much balance do I have?"
```

All should resolve to:

``` text
BALANCE
```

Other examples:

``` text
"show me my phone"       -> DEVICE_DETAILS
"what did I buy?"        -> PURCHASE_HISTORY
"what offers do I have?" -> OFFERS
"show my details"        -> PROFILE
```

Do not build a separate spell-checking service.

------------------------------------------------------------------------

# 8. Phase 5 --- Confidence and Clarification

This is a core architectural component.

Make the threshold configurable, for example:

``` text
INTENT_CONFIDENCE_THRESHOLD=0.80
```

Do not assume 0.80 is the final production value; tune it using tests.

### High confidence

``` text
User
  |
  v
Router
  |
  v
BALANCE / 0.98
  |
  v
Balance API
```

### Low confidence

``` text
User
  |
  v
Router
  |
  v
Low confidence / ambiguous
  |
  v
NO API CALL
  |
  v
Clarification
```

Example:

> "Check my plan."

Possible interpretations may include current profile/plan or available
offers.

Return clarification rather than guessing:

> "Do you want to check your current plan or see available plans?"

Example router result:

``` json
{
  "intent": null,
  "confidence": 0.55,
  "needs_clarification": true,
  "possible_intents": [
    "PROFILE",
    "OFFERS"
  ]
}
```

The backend must enforce `needs_clarification` and prevent the API call.

------------------------------------------------------------------------

# 9. Phase 6 --- Clarification State

Preserve enough conversation/session state to understand the user's
answer.

Example:

``` text
User:
"Check my plan."

Assistant:
"Do you mean your current plan or available plans?"

User:
"Available ones."

        |
        v
Router
        |
        v
OFFERS
        |
        v
Offers API
```

For the POC, lightweight session/in-memory state is acceptable
initially.

Do not add Redis or another infrastructure component unless it becomes
necessary.

------------------------------------------------------------------------

# 10. Phase 7 --- Chat Endpoint

Implement:

``` text
POST /api/chat
```

Input:

``` json
{
  "message": "what is my balence"
}
```

Flow:

``` text
message
   |
   v
Intent Router
   |
   v
BALANCE / high confidence
   |
   v
Secure Tool
   |
   v
Balance API
   |
   v
Structured response
```

Example successful response:

``` json
{
  "type": "answer",
  "intent": "BALANCE",
  "message": "Your current balance is ...",
  "data": {}
}
```

Example clarification:

``` json
{
  "type": "clarification",
  "message": "Do you want to check your current plan or see available plans?"
}
```

Keep the response schema stable and frontend-friendly.

------------------------------------------------------------------------

# 11. Phase 8 --- Latency Optimization

Latency is a primary requirement.

## Simple request

Target:

``` text
User
  |
  v
Fast intent understanding
  |
  v
API
  |
  v
Response
```

Avoid unnecessary chains such as:

``` text
LLM -> LLM -> Agent -> Tool -> API -> LLM -> Response
```

unless the request actually requires that complexity.

## Parallel APIs

For independent APIs:

``` text
             +--> Balance API --+
             |                   |
Router ------+--> Device API ----+--> Response
             |                   |
             +--> Offers API ---+
```

Use asynchronous concurrency.

Do not sequentially call independent APIs.

If a telecom API itself takes approximately 2.5 seconds, that API
latency remains the dominant portion of the request. The architecture
should avoid adding unnecessary latency around it.

------------------------------------------------------------------------

# 12. Phase 9 --- Realtime Voice

Voice must use the same secure tools/business logic as Chat.

Preferred flow:

``` text
             VOICE CLIENT
                  |
                  | realtime audio
                  v
           Realtime model
                  |
                  | tool request
                  v
              FastAPI
                  |
                  v
            Secure Tool
                  |
                  v
            Telecom API
                  |
                  v
             Tool result
                  |
                  v
           Realtime model
                  |
                  v
             Audio reply
```

Do not duplicate the telecom tool implementations for Voice.

Avoid an unnecessary:

``` text
Audio -> STT -> text LLM -> TTS -> Audio
```

pipeline if the selected realtime platform supports direct
speech-to-speech plus secure tool/function calling.

The realtime model should handle conversation/audio while the FastAPI
backend remains the trusted tool gateway.

------------------------------------------------------------------------

# 13. Phase 10 --- LangGraph Fallback

Only implement LangGraph after the fast path is working.

Use LangGraph for genuinely complex/multi-step requests.

Example:

> "Check my balance, tell me which device I use, and recommend an
> offer."

Possible graph:

``` text
START
  |
  v
Determine required operations
  |
  +------> Balance
  |
  +------> Device
  |
  +------> Offers
  |
  v
Combine results
  |
  v
Final response
```

Independent operations should execute concurrently where possible.

Do not route every request through LangGraph.

------------------------------------------------------------------------

# 14. Phase 11 --- Authentication and Authorization

Security boundary:

``` text
Authenticated User
       |
       v
Session / Identity
       |
       v
FastAPI
       |
       v
Authorized Customer Context
       |
       v
Tool
       |
       v
Telecom API
```

Rules:

-   Never trust `mobileNumber` from the model.
-   Never allow the model to override the authorized customer.
-   Validate customer access on the backend.
-   Keep API credentials server-side.
-   Never expose secrets to the frontend.
-   Never log tokens or authorization headers.
-   Never allow arbitrary tools/URLs.
-   Validate all request payloads.
-   Add rate limiting where practical.

------------------------------------------------------------------------

# 15. Phase 12 --- Testing

Create unit, integration, security, and end-to-end tests.

## Router

Test:

``` text
"What is my balance?"
"What is my balence?"
"how much money do I have?"
```

Expected:

``` text
BALANCE
```

Test:

``` text
"show my device"
```

Expected:

``` text
DEVICE_DETAILS
```

Test ambiguous:

``` text
"check my plan"
```

Expected:

``` text
needs_clarification = true
```

## API tests

Mock telecom APIs and test:

-   Successful response
-   Timeout
-   4xx
-   5xx
-   Invalid response
-   Missing customer context

## Security tests

Verify:

-   Model cannot override mobileNumber.
-   Unknown tools cannot be called.
-   Arbitrary URLs cannot be called.
-   Secrets are never returned.
-   Unauthorized customer access is rejected.

## End-to-end

Verify:

``` text
Chat -> Balance -> API -> Response

Chat -> Ambiguous request -> Clarification

Chat -> Clarification answer -> API -> Response

Complex request -> LangGraph -> APIs -> Response
```

------------------------------------------------------------------------

# 16. Phase 13 --- Azure VM Deployment

Target:

``` text
Azure 1 GB Ubuntu VM
        |
        +-- Nginx :443
        |
        +-- FastAPI :8000
        |
        +-- External model/API services
        |
        +-- Telecom APIs
```

Do not run:

-   Local LLM inference
-   Ollama
-   Elasticsearch
-   Heavy vector databases
-   Kubernetes
-   Unnecessary monitoring stacks

on the 1 GB VM.

Start with:

``` text
Nginx
+
1 FastAPI process
```

Do not blindly configure multiple workers because each worker consumes
memory.

Configure swap as protection against memory spikes.

------------------------------------------------------------------------

# 17. Environment Configuration

Use environment variables.

Example `.env.example`:

``` text
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=

TELECOM_API_BASE_URL=
TELECOM_API_KEY=

INTENT_CONFIDENCE_THRESHOLD=0.80

APP_ENV=development
LOG_LEVEL=INFO
```

Never commit real secrets.

Add:

``` text
.env
```

to `.gitignore`.

For Azure, prefer managed identity or a secure secret-management
mechanism where available.

------------------------------------------------------------------------

# 18. Logging and Observability

Keep logging lightweight.

Include:

``` text
request_id
intent
confidence
selected_path
API latency
tool latency
total latency
success/failure
```

Do not log:

``` text
API keys
Authorization headers
tokens
unnecessary customer-sensitive data
```

Measure:

``` text
router_latency_ms
api_latency_ms
tool_latency_ms
total_latency_ms
```

This allows latency bottlenecks to be identified accurately.

------------------------------------------------------------------------

# 19. Implementation Order

Implement in exactly this order:

``` text
PHASE 1
FastAPI foundation
        |
        v
PHASE 2
Telecom API clients
        |
        v
PHASE 3
Secure tool layer
        |
        v
PHASE 4
Intent router
        |
        v
PHASE 5
Confidence + clarification
        |
        v
PHASE 6
Chat endpoint
        |
        v
PHASE 7
Testing + latency optimization
        |
        v
PHASE 8
Realtime Voice
        |
        v
PHASE 9
LangGraph complex fallback
        |
        v
PHASE 10
Azure VM deployment
```

After every phase:

1.  Run tests.
2.  Start the application.
3.  Verify behavior.
4.  Fix failures.
5.  Only then continue.

------------------------------------------------------------------------

# 20. Definition of Done

### Chat

``` text
"What is my balance?"
        |
        v
BALANCE
        |
        v
Balance API
        |
        v
Correct response
```

### Typo tolerance

``` text
"what is my balence?"
        |
        v
BALANCE
```

### Clarification

``` text
"Check my plan"
        |
        v
Ambiguous
        |
        v
Clarification
        |
        v
User answers
        |
        v
Correct API
```

### Voice

``` text
Voice request
    |
    v
Realtime model
    |
    v
Secure backend tool
    |
    v
Telecom API
    |
    v
Natural voice response
```

### Complex request

``` text
Complex request
    |
    v
LangGraph
    |
    v
Parallel APIs where possible
    |
    v
Combined response
```

### Security

``` text
LLM cannot:
- choose arbitrary customer
- override mobileNumber
- call arbitrary URLs
- access API secrets
- invoke arbitrary tools
```

### Deployment

``` text
Azure 1 GB VM
    |
    +-- Nginx
    |
    +-- FastAPI
```

No local LLM.
