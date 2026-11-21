# 0019. Página en un solo archivo, sin recursos de otros sitios

Estado: aceptado (spec/07-page.md)

## Contexto

La página se rediseña como un chat moderno, con modo oscuro y buen aspecto en celular.
Un framework, una fuente web o una biblioteca de íconos lo harían más fácil, pero
agregan un paso de compilación, dependencias y peticiones a terceros que revelan quién
visita la página. La demo debe cargar rápido y funcionar sin internet.

## Decisión

- Todo vive en `app/static/index.html`: HTML, CSS y JavaScript en el mismo archivo, sin
  `<link>`, `<script src>`, `@import` ni `url(http...)`.
- Tipografía `system-ui`; el ícono es un SVG en línea sin `xmlns` ni `href`.
- El diseño sale de variables CSS (`--color-...`, `--radius`, `--shadow`, `--space-...`)
  con un solo color de acento; `prefers-color-scheme: dark` solo redefine las variables y
  `prefers-reduced-motion: reduce` quita transiciones.
- La API, el agente y la configuración no cambian; `main.py` sirve el archivo como hoy.

## Consecuencias

- Sin librerías nuevas ni paso de compilación; la imagen de Docker no cambia.
- Un cambio de paleta es un cambio de variables, en un solo lugar y en ambos modos.
- El archivo crece; si algún día pasa a varios archivos, habrá que servirlos como
  estáticos y revisar este ADR.
- `test_contract_07.py` y `tests/test_api.py` rechazan cualquier `src` o `href` externo.
