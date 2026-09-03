# Chat flow — user input → LLM → Python → answer

Traces `POST /api/chat` through the real code paths for a high-confidence answer and a
low-confidence clarification (the two possible outcomes for a single-lookup intent). See
[ARCHITECTURE.md](ARCHITECTURE.md) for the full system and [chat.py](../app/api/chat.py) /
[llm.py](../app/services/llm.py) / [confidence.py](../app/router/confidence.py) for the actual
code. Voice isn't shown here — it's a live bidirectional session, not a single request/response,
so it doesn't fit this diagram shape (see ARCHITECTURE.md's voice section instead).

```mermaid
sequenceDiagram
    actor U as Browser
    participant C as chat.py
    participant L as llm.py (Azure OpenAI)
    participant Cf as confidence.py
    participant R as registry.py + telecom_client.py
    participant T as Telecom API
    participant Rs as response.py

    Note over U: Prepaid vs Postpaid is a UI-only label<br/>(subscriberType field, e.g. on a demo number picker).<br/>NOT a backend branch - every account, either<br/>subtype, flows through the identical path below.<br/>No subtype-specific logic exists in the code today.

    U->>C: POST /api/chat<br/>{"message":"what is my balence","mobile_number":"+919999900003"}
    C->>C: _mentions_different_account()<br/>no number in text -> pass through
    C->>L: classify_intent(message)
    Note right of L: ONE call, JSON-mode.<br/>Sees ONLY the message text -<br/>never the phone number, never calls anything.
    L-->>C: {"intent":"BALANCE","confidence":0.95,<br/>"possible_intents":[],"scope":"full"}
    C->>Cf: build_router_result(raw, threshold=0.80)
    Note right of Cf: Pure Python. Checks intent is on<br/>the allow-list AND confidence >= threshold.

    alt confidence >= threshold  (0.95 >= 0.80)
        Cf-->>C: RouterResult(intent="BALANCE",<br/>needs_clarification=False, scope="full")
        C->>C: customer = get_customer_context(request.mobile_number)<br/>from the REQUEST, never the LLM
        C->>R: execute_tool("BALANCE", customer)
        R->>T: GET /api/balance?mobileNumber=+919999900003
        T-->>R: {"data":{"mainWallet":{"balance":102.5,...},<br/>"subscriberType":"Prepaid",...}}
        R-->>C: ToolResult(success=True, data={...})
        C->>Rs: render_answer_message("BALANCE", data)
        Note right of Rs: Pure Python template.<br/>No second LLM call on this fast path.<br/>subscriberType is just a field it can read -<br/>not a routing decision anywhere above.
        Rs-->>C: "Main balance: Rs.102.5 (expires 2026-11-15)..."
        C-->>U: {"type":"answer","intent":"BALANCE",<br/>"message":"Main balance: Rs.102.5..."}
    else confidence < threshold  (e.g. "check my plan")
        Cf-->>C: RouterResult(intent=null,<br/>needs_clarification=true,<br/>possible_intents=["PROFILE","OFFERS"])
        C->>C: session_store.set_pending(session_id, candidates)
        Note right of C: NO tool call. NO telecom API call.
        C-->>U: {"type":"clarification",<br/>"message":"Do you mean your current<br/>plan or available plans?"}
    end
```
