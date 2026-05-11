# AGENTS.md

## Proyecto

Esta carpeta contiene una app local para detectar imagenes duplicadas, similares, memes y miniaturas de baja calidad.

Archivos principales:

- `duplicate_image_app.py`: entrada CLI.
- `package.json`: scripts npm para ejecutar la app rapido.
- `scripts/start.js`: busca Python y lanza `duplicate_image_app.py`.
- `server.py`: servidor HTTP y endpoints API.
- `image_tools.py`: escaneo, hashing, calidad, memes y miniaturas.
- `file_actions.py`: movimiento seguro de descartes.
- `models.py`: dataclasses y estado base.
- `state.py`: estado global del escaneo activo.
- `constants.py`: constantes compartidas.
- `web/index.html`: UI, CSS y JavaScript.

## Como ejecutar

```powershell
python duplicate_image_app.py
```

Atajo recomendado:

```powershell
npm start
```

Opcional:

```powershell
python duplicate_image_app.py --port 8765 --no-open
```

Requiere Pillow para miniaturas, dimensiones, hash visual, baja calidad y deteccion visual de texto:

```powershell
pip install pillow
```

## Reglas de comportamiento

- Los archivos nunca se borran directamente.
- Los descartes se mueven a `_DUPLICADOS_ELIMINADOS` dentro de la carpeta analizada.
- Para duplicados, la sugerencia inicial conserva la imagen de mayor calidad/resolucion; si empata, conserva la mas antigua.
- Cada tarjeta tiene una casilla `Mover`. Lo que este marcado se mueve, incluso si todas las imagenes de un grupo estan marcadas.
- La opcion `Mantener` solo ayuda a elegir rapidamente una imagen para no mover; el usuario puede volver a marcarla para moverla tambien.
- La deteccion de memes es heuristica: combina nombres comunes y senales visuales de texto superpuesto dentro de la imagen.
- La deteccion de miniaturas/baja calidad usa dimensiones pequenas y nombres tipo `thumb`, `thumbnail`, `miniatura`, `preview` o `cache`.

## Notas de desarrollo

- Mantener los modulos pequenos y con responsabilidades claras.
- No cambiar el comportamiento de respaldo por eliminacion permanente.
- Preferir cambios pequenos y verificables.
- Si se toca `web/index.html`, validar al menos la sintaxis del script con Node cuando este disponible.
- Si se toca Python, validar con `python -m py_compile duplicate_image_app.py server.py image_tools.py file_actions.py models.py state.py constants.py` cuando Python este disponible en PATH.
- El texto visible esta en espanol y debe mantenerse consistente.
- Live Server de VS Code solo sirve para ver el HTML estatico; la app funcional requiere el servidor Python porque usa endpoints `/api/*`.

## Limitaciones conocidas

- La deteccion de memes no usa OCR real; reconoce patrones visuales de texto y puede tener falsos positivos o negativos.
- HEIC/HEIF/AVIF dependen de si la instalacion local de Pillow puede abrir esos formatos.
