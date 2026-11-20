Feature: First level of the help desk
  An employee describes a problem in their own words. The assistant offers the
  solution of a current knowledge base article or transfers the employee to the
  human team that handles the problem.

  Scenario: A known problem gets the solution from the knowledge base
    Given the support assistant is running
    When an employee asks "No me puedo conectar a la VPN desde mi casa"
    Then the answer contains "KB-0001"
    And the answer contains "Conectarse a la VPN corporativa"
    And the tools used are "search_knowledge_base"
    And the conversation is not escalated
    And the reported step count is 2

  Scenario: The problem is matched without accents or capitals
    Given the support assistant is running
    When an employee asks "SE ATORO EL PAPEL EN LA IMPRESORA"
    Then the answer contains "Atasco de papel"
    And the conversation is not escalated

  Scenario: A classified problem without a current article is escalated to its team
    Given the support assistant is running
    When an employee asks "Mi teclado tiene teclas que no funcionan"
    Then the conversation is escalated to "Soporte en sitio"
    And the tools used are "search_knowledge_base, escalate_to_human"
    And the reported step count is 2

  Scenario: An obsolete article is never offered
    Given the support assistant is running
    When an employee asks "Necesito instalar un programa nuevo"
    Then the answer does not contain "KB-0008"
    And the conversation is escalated to "Mesa de Software"

  Scenario: Asking for a person goes straight to the general desk
    Given the support assistant is running
    When an employee asks "Quiero hablar con una persona"
    Then the conversation is escalated to "Mesa de Servicio General"
    And the tools used are "escalate_to_human"

  Scenario: An unrecognized problem asks for more detail
    Given the support assistant is running
    When an employee asks "¿Qué clima hace hoy en Monterrey?"
    Then the answer contains "Describe tu problema"
    And the answer contains "persona"
    And the tools used are "search_knowledge_base"
    And the conversation is not escalated

  Scenario: A greeting gets guidance without tools
    Given the support assistant is running
    When an employee asks "Hola"
    Then the answer contains "Describe tu problema"
    And no tools are used

  Scenario Outline: An invalid question is rejected
    Given the support assistant is running
    When an employee sends a <kind> question
    Then the request is rejected as invalid

    Examples:
      | kind     |
      | empty    |
      | blank    |
      | too long |

  Scenario: The step cap stops the loop with a fixed answer
    Given the support assistant is limited to 1 step
    When an employee asks "No me puedo conectar a la VPN desde mi casa"
    Then the answer is the fixed step cap message
    And the reported step count is 1
