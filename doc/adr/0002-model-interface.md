# 0002. Interfaz del modelo y protocolo JSON

Estado: aceptado (spec/01-architecture.md)

## Contexto

Hoy solo existe un modelo simulado, pero después llegará un modelo real. El agente no debe
cambiar cuando cambie el modelo, y las pruebas deben ser deterministas y sin red.

## Decisión

- El agente usa el protocolo `ChatModel.complete(messages) -> Completion`, con `text`,
  `input_tokens` y `output_tokens`.
- El modelo responde siempre un objeto JSON: `{"tool", "args"}` o `{"answer"}`.
- `FakeModel` (`MODEL_PROVIDER=fake`) aplica las reglas de la especificación sobre el último
  mensaje y cuenta tokens por palabras. Un `MODEL_PROVIDER` desconocido impide arrancar.

## Consecuencias

- Agregar un proveedor es escribir otra clase con `complete()`; el agente no cambia.
- El modelo simulado define el comportamiento observable del contrato; un modelo real puede
  desviarse, por eso el agente valida todo lo que recibe (ADR 0003).
- Los tokens del modelo simulado son aproximados: sirven para medir, no para facturar.
