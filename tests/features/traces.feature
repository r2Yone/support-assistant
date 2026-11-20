Feature: LangSmith traces show what the assistant did and what it cost
  Each answer leaves an agent_run trace that says how it ended, with tags to filter
  it, and one llm trace per model call with its provider, model and tokens. The
  conversation text is hidden by default, no key or IP address is ever sent, and a
  LangSmith failure never breaks an answer. LangSmith is a recording stub: the
  scenarios never use the network.

  Scenario: A solved question is annotated with how it ended
    Given the traced support assistant is running
    When an employee asks "Mi laptop no enciende"
    Then the answer has status 200 and the outcome "solved"
    And the agent run trace has the ten outcome metadata of the answer
    And the agent run trace is tagged with "outcome:solved", its route and its model

  Scenario: An escalated question can be filtered by its outcome tag
    Given the traced support assistant is running
    When an employee asks "Quiero hablar con una persona, por favor"
    Then the answer has status 200 and the outcome "escalated"
    And the agent run trace has the ten outcome metadata of the answer
    And the agent run trace is tagged with "outcome:escalated", its route and its model

  Scenario: Every model call is an llm trace with its provider, model and tokens
    Given the traced support assistant is running
    When an employee asks "Mi laptop no enciende"
    Then every model call is an llm trace from "fake" named after the answering model
    And the token usage of the llm traces adds up to the tokens of the answer

  Scenario: By default only the token usage leaves the process
    Given the traced support assistant is running
    When an employee asks "Mi laptop no enciende"
    Then no trace sends any input
    And the llm traces send only their usage metadata
    And neither the question nor the answer is sent to LangSmith

  Scenario: Neither the IP address nor any key is ever sent
    Given the traced demo assistant shows the conversation text behind a trusted proxy
    When a visitor asks through the proxy as "198.51.100.23"
    And the client with a key asks "Mi laptop no enciende"
    Then both answers have status 200
    And neither "198.51.100.23", the connection address nor any key is sent to LangSmith
    And the agent run traces carry the clients "public" and "qa-tests"

  Scenario Outline: A LangSmith failure never breaks an answer
    Given the traced support assistant is running and LangSmith fails when <failure>
    When an employee asks "Mi laptop no enciende"
    Then the answer has status 200 and the outcome "solved"
    And the log has no error event

    Examples:
      | failure                 |
      | reading the current run |
      | adding metadata         |
      | sending the trace       |

  Scenario: Without a LangSmith key the assistant answers without loading LangSmith
    Given the support assistant asks for traces without a key and LangSmith cannot be loaded
    When an employee asks "Mi laptop no enciende"
    Then the answer has status 200 and the outcome "solved"
    And the metrics report a latency target of 4000 ms
