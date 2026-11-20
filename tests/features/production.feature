Feature: Only clients with a key use the assistant, and none of them abuses it
  Each client of the help desk has its own key. The assistant answers only with a
  valid key, limits how many questions a client asks per minute, writes the name of
  the client in its log and never writes the key anywhere.

  Scenario Outline: A protected route without a valid key is rejected
    Given the protected support assistant is running
    When a caller sends <method> <path> <credential>
    Then the response is 401 "invalid or missing API key" with the generated request id
    And the log has a request event with status 401 and no client
    And the key "wrong-key-sent-by-a-caller" appears nowhere in the log

    Examples:
      | method | path     | credential            |
      | POST   | /ask     | without a key         |
      | POST   | /ask     | with a wrong key      |
      | GET    | /metrics | with a wrong key      |

  Scenario: Public pages answer without a key
    Given the protected support assistant is running
    Then "/", "/health" and "/docs" answer 200 without a key

  Scenario: A missing key is rejected before the question is validated
    Given the protected support assistant is running
    When a caller without a key sends an empty question
    Then the response is 401 "invalid or missing API key" with the generated request id

  Scenario: A valid key answers and the log names the client but never the key
    Given the protected support assistant is running
    When the client asks "No me puedo conectar a la VPN desde mi casa"
    Then the answer has status 200 and the outcome "solved"
    And the request, agent run and audit events carry the client name
    And the valid key appears nowhere in the log

  Scenario: Too many questions in a minute are rejected until the window passes
    Given the protected support assistant allows 2 questions per minute for two clients
    When the client asks 3 questions
    Then the last response is 429 "rate limit exceeded" with a Retry-After of at least 1
    And the other client can still ask
    And after 60 seconds the client can ask again

  Scenario: The real model authenticates with the gateway and never leaks its token
    Given the protected support assistant uses a gateway that answers once and then fails
    When the client asks "No me puedo conectar a la VPN desde mi casa"
    And the client asks "Mi laptop no enciende"
    Then every gateway request carries the token in the authenticated gateway header
    And the second response is 502 without the token
    And the token appears nowhere in the log
