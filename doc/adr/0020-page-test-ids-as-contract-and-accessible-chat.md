# 0020. Los `data-testid` son el contrato de la página; el chat es accesible

Estado: aceptado (spec/07-page.md)

## Contexto

El rediseño cambia todo el marcado y los estilos, pero las pruebas de punta a punta, la
verificación y la prueba de humo dependen de la página. Además el chat debe usarse con
teclado y lector de pantalla, y no debe abrir la puerta a inyección de HTML al resaltar
el id del artículo.

## Decisión

- Contrato estable: un solo `answer` con toda la conversación, una sola tarjeta
  `escalation`, `question`, `send` y tres `example`. Las pruebas buscan por
  `data-testid`, nunca por clases ni estilos.
- Se conservan los textos de error de 401, 429, 503 y pregunta vacía, «request_id:» y
  «Folio:». La página sigue sin clave y sin guardar nada en el navegador (ADR 0013).
- Todo el contenido dinámico se crea con `createElement` y `textContent`; la etiqueta
  `KB-xxxx` es un `span` aparte. Nunca `innerHTML`.
- Accesibilidad: contraste de 4.5:1 o más en ambos modos, `:focus-visible` con el color
  de acento, `aria-label` en los controles sin texto, `aria-live` en la conversación y
  `role="status"` en el indicador de espera y en la tarjeta de transferencia.
- Pulsar un ejemplo solo escribe en el campo; enviar sigue siendo Enter o el botón.

## Consecuencias

- Se puede rediseñar otra vez sin tocar las pruebas mientras se respeten los
  `data-testid`.
- Las pruebas nuevas no envían preguntas: la suite e2e se queda en 5 `POST /ask`, dentro
  del límite por IP.
- El contraste y el aspecto no los comprueba el código: una persona revisa la página
  antes de aprobar la publicación.
