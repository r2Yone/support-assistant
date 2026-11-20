Feature: What each answer costs
  Every answer says which model it used, why, and how much it cost. A rule in the
  code sends simple problems to the cheap model, only the last messages of the
  history reach the model, and the metrics show what it costs to solve a problem
  without a person.

  Scenario: A simple problem is answered by the small model at a cost
    Given the costed support assistant is running
    When an employee asks "Mi laptop no enciende"
    Then the answer used the small model with route "default"
    And the answer cost more than 0 without cached calls
    And the agent run logs the model, route, cached calls and cost of the answer

  Scenario Outline: A question that needs reasoning goes to the large model
    Given the costed support assistant is running with routing "<routing>"
    When an employee asks "<question>"
    Then the answer used the large model with route "<route>"

    Examples:
      | routing | question                                                                                      | route            |
      | true    | ¿Por qué se me desconecta la VPN?                                                             | keyword:por qué  |
      | true    | Otra vez no me conecta la VPN                                                                 | keyword:otra vez |
      | true    | Desde esta mañana no me puedo conectar a la VPN desde mi casa y ya reinicié el equipo dos veces | long_question    |
      | false   | Mi laptop no enciende                                                                         | routing_disabled |

  Scenario: The same problem costs more with the large model
    Given the costed support assistant is running
    When an employee asks "Mi laptop no enciende"
    And an employee asks "Otra vez mi laptop no enciende"
    Then the second answer cost more than the first

  Scenario: Only the last messages of the history reach the model
    Given the costed support assistant is running with a model that records its messages
    When an employee with 10 previous messages asks "Mi laptop no enciende"
    Then the model received only the last 6 previous messages and the question

  Scenario Outline: A forgotten password finds its article in the employee's words
    Given the costed support assistant is running
    When an employee asks "<question>"
    Then the answer contains "KB-0003"
    And the conversation is not escalated

    Examples:
      | question                     |
      | Se me olvidó la contraseña   |
      | Quiero recuperar mi password |

  Scenario: Metrics add up what it costs to solve a problem
    Given the costed support assistant is running
    When an employee asks "Mi laptop no enciende"
    Then the outcome is "solved"
    And the metrics report a cost above 0 and a cost per solved problem up to it

  Scenario: An escalation ends with the fixed message and solves nothing
    Given the costed support assistant is running
    When an employee asks "Mi teclado tiene teclas que no funcionan"
    Then the answer is exactly "Te comunico con Soporte en sitio."
    And the reported step count is 2
    And the metrics report a cost above 0 and a cost per solved problem of 0

  Scenario: A failing gateway returns a 502 without leaking its secrets
    Given the costed support assistant uses a gateway that fails
    When an employee asks "Mi laptop no enciende"
    Then the response is "model unavailable" with the generated request id
    And the log has one error event with its type and no gateway secret
    And the metrics report an error rate above 0
