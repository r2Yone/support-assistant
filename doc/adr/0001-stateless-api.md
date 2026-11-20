# 0001. API sin estado con dependencias inyectadas

Estado: aceptado (spec/01-architecture.md)

## Contexto

El Support Assistant debe escalar corriendo más copias del proceso. Las pruebas necesitan
sustituir la configuración, el modelo y la base de conocimiento sin tocar el entorno.

## Decisión

- La API no guarda nada entre peticiones: el historial lo manda el cliente en `history` y
  la página lo conserva en el navegador.
- `create_app(settings, model, knowledge_base)` recibe sus dependencias; `app` a nivel de
  módulo se construye desde el entorno y falla al importar si la configuración o la base
  de conocimiento son inválidas.
- La base de conocimiento se carga una vez al arrancar y solo se lee.

## Consecuencias

- Cualquier copia puede atender cualquier petición; no hace falta sesión ni base de datos.
- El cliente controla el historial: puede enviar uno largo o inventado, así que solo se usa
  como contexto, nunca como fuente de verdad.
- Las especificaciones siguientes agregan dependencias (reloj, log, métricas) como nuevos
  parámetros de `create_app()` con valores por omisión.
