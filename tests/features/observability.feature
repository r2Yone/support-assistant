Feature: What happened with a request
  An employee gives support the folio of a request, and support finds with data
  what happened with it. The help desk also measures how many problems the first
  level solves without a person.

  Scenario Outline: Every answer says how it ended
    Given the observed support assistant is running
    When an employee asks "<question>"
    Then the outcome is "<outcome>"
    And the logged article is "<article>"

    Examples:
      | question                                    | outcome      | article |
      | No me puedo conectar a la VPN desde mi casa | solved       | KB-0001 |
      | Mi teclado tiene teclas que no funcionan    | escalated    | none    |
      | Hola                                        | needs_detail | none    |

  Scenario: The step cap is reported as incomplete
    Given the observed support assistant is limited to 1 step
    When an employee asks "No me puedo conectar a la VPN desde mi casa"
    Then the outcome is "incomplete"
    And the agent run is logged as stopped

  Scenario: A safe request id from the client is kept
    Given the observed support assistant is running
    When an employee with the request id "folio-123" asks "Mi laptop no enciende"
    Then the request id in the header and in the body is "folio-123"

  Scenario Outline: An unsafe request id from the client is replaced
    Given the observed support assistant is running
    When an employee sends a request id that is <kind>
    Then the request id in the header and in the body is the generated one

    Examples:
      | kind         |
      | too long     |
      | with a slash |

  Scenario: The log of a solved question tells its whole story under one folio
    Given the observed support assistant is running
    When an employee with the request id "folio-vpn" asks "No me puedo conectar a la VPN desde mi casa"
    Then the log events of "folio-vpn" are "audit, agent_run, request" in that order
    And the audit shows the search found "KB-0001" in category "Red"
    And the request event shows "POST /ask" with status 200 and its latency

  Scenario: The conversation text can be left out of the log
    Given the observed support assistant is running with "LOG_CONVERSATION_TEXT" set to "false"
    When an employee asks "No me puedo conectar a la VPN desde mi casa"
    Then the agent run has no question and no answer
    And the question "No me puedo conectar a la VPN desde mi casa" appears nowhere in the log

  Scenario: A failing model returns an internal error with its folio
    Given the observed support assistant runs with a model that fails
    When an employee asks "No me puedo conectar a la VPN desde mi casa"
    Then the response is an internal error with the generated request id
    And the log has an error event of type "RuntimeError" without its message
    And the metrics report an error rate above 0

  Scenario: Metrics measure how much the first level solves
    Given the observed support assistant is running
    When an employee asks "No me puedo conectar a la VPN desde mi casa"
    And an employee asks "Mi teclado tiene teclas que no funcionan"
    Then the metrics count the outcomes "solved=1, escalated=1, needs_detail=0, incomplete=0"
    And the self service rate is 0.5
    And the metrics report the tokens used
