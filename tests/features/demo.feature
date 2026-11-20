Feature: Anyone with the URL can try the assistant, within a limit per IP and a daily budget
  In demo mode the page asks questions without a key as the client "public". Those
  questions are limited per IP address and by a daily spending budget. Integrations
  still use their own key, and the IP address is never written anywhere.

  Scenario: A question without a key is answered as the public client
    Given the demo support assistant is running
    When a visitor asks "No me puedo conectar a la VPN desde mi casa"
    Then the answer has status 200 and the outcome "solved"
    And the request, agent run and audit events carry the client "public"

  Scenario Outline: A key that is sent is still validated in demo mode
    Given the demo support assistant is running
    When a caller asks with the key "<key>"
    Then the response is 401 "invalid or missing API key" with the generated request id

    Examples:
      | key                        |
      | wrong-key-sent-by-a-caller |
      |                            |

  Scenario: A client with a valid key does not use the demo limits
    Given the demo support assistant allows 1 question per minute and a tiny budget
    When a visitor asks "No me puedo conectar a la VPN desde mi casa"
    And the client with a key asks 2 questions
    Then every keyed answer has status 200 and carries the client name
    And the visitor is still the only one counted in the public spending

  Scenario: Metrics still need a key and report the daily budget
    Given the demo support assistant is running
    When a visitor asks "No me puedo conectar a la VPN desde mi casa"
    Then GET /metrics without a key answers 401
    And GET /metrics with a key reports the public cost of the visitor and a budget of 0.5

  Scenario: Too many public questions from one IP are rejected until the window passes
    Given the demo support assistant allows 2 public questions per minute
    When the visitor asks 3 questions
    Then the last response is 429 "rate limit exceeded" with a Retry-After of at least 1
    And a visitor from another IP can still ask
    And after 60 seconds the visitor can ask again

  Scenario: Behind a trusted proxy the last forwarded address is the one limited
    Given the demo support assistant behind a trusted proxy allows 1 public question per minute
    When the visitor asks through the proxy as "198.51.100.23"
    And the visitor asks again through the proxy with a forged first entry
    Then the second response is 429
    And a visitor forwarded as "198.51.100.24" can still ask

  Scenario: Without a trusted proxy the forwarded addresses are ignored
    Given the demo support assistant allows 1 public question per minute
    When the visitor asks through the proxy as "198.51.100.23"
    And the visitor asks through the proxy as "198.51.100.24"
    Then the second response is 429

  Scenario: The IP address is never written in the log
    Given the demo support assistant behind a trusted proxy allows 5 public questions per minute
    When the visitor asks through the proxy as "198.51.100.23"
    Then neither "198.51.100.23" nor the connection address appear in the log

  Scenario: The daily budget stops public questions until the next UTC day
    Given the demo support assistant has a tiny daily budget and a spy model
    When the visitor asks 3 questions
    Then the first answer costs money and the next two are 503 "daily budget exhausted"
    And the model was called only for the first question
    And the log has the request statuses 200, 503 and 503
    And the log has one budget_exhausted event with the spent amount and the budget
    And the client with a key can still ask
    And on the next UTC day the visitor can ask again
