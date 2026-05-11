# Detector de Imagenes Duplicadas

App local para revisar fotos duplicadas o visualmente parecidas, encontrar posibles memes y detectar miniaturas o imagenes de baja calidad. Todo corre en tu maquina y los archivos descartados se mueven a una carpeta de respaldo.

## Caracteristicas

- Duplicados exactos por SHA-256.
- Imagenes visualmente similares con hash perceptual.
- La similitud visual combina `dHash` para bordes y `aHash` para composicion general, de modo que puede unir la misma foto aunque cambie tamano o compresion.
- Prioridad automatica para conservar la imagen de mayor calidad/resolucion y luego la mas antigua.
- Tema oscuro.
- Vista en 2 columnas, o 3 columnas en pantallas anchas.
- Barra fija para mover todos los descartes seleccionados mientras haces scroll.
- Boton `Seleccionar todas` por grupo, para descartar incluso todas las imagenes duplicadas.
- En revisiones de memes/miniaturas, casilla `Mover` en cada tarjeta para decidir candidato por candidato.
- Revision opcional de memes por texto dentro de la imagen.
- Revision opcional de miniaturas o imagenes de baja calidad.
- Los descartes se mueven a `_DUPLICADOS_ELIMINADOS`; no se eliminan permanentemente.

## Instalacion

Instala Pillow para que funcionen miniaturas, dimensiones, deteccion visual y revision de memes:

```powershell
pip install pillow
```

## Uso

Forma rapida con Node/npm:

```powershell
npm start
```

Tambien puedes pasar argumentos:

```powershell
npm start -- --no-open
npm start -- --port 9000
```

O ejecuta Python directamente:

```powershell
python duplicate_image_app.py
```

La app abre una pagina local en el navegador. Tambien puedes abrir manualmente la URL que aparece en la consola, por ejemplo:

```text
http://127.0.0.1:8765
```

## Live Server de VS Code

Live Server puede abrir `web/index.html`, pero solo como interfaz estatica. Para analizar carpetas, generar miniaturas y mover descartes necesitas ejecutar el backend:

```powershell
python duplicate_image_app.py
```

La razon es que el HTML llama rutas como `/api/scan`, `/api/image` y `/api/move-selected`, y esas rutas las atiende el servidor Python. Live Server no sabe leer tus carpetas ni mover archivos.

## Estructura

```text
duplicate_image_app.py  Entrada principal
package.json            Scripts npm para iniciar rapido
scripts/start.js        Busca Python y ejecuta la app
server.py               Servidor HTTP y rutas API
image_tools.py          Escaneo, hash, calidad, memes y miniaturas
file_actions.py         Movimiento seguro a respaldo
models.py               Modelos de datos
state.py                Estado del escaneo activo
constants.py            Constantes compartidas
web/index.html          Interfaz web
```

## Flujo recomendado

1. Selecciona o escribe la carpeta de imagenes.
2. Deja activado `Detectar similares visuales` si quieres encontrar imagenes parecidas, no solo duplicados exactos.
3. Activa `Encontrar memes` para revisar imagenes con posible texto superpuesto.
4. Activa `Encontrar miniaturas/baja calidad` para revisar archivos pequenos o thumbnails.
5. En duplicados, usa `Mantener` para elegir la imagen que quieres salvar.
6. Si no quieres ninguna imagen de un grupo duplicado, usa `Seleccionar todas`.
7. Usa `Mover descartados` en un grupo o `Mover descartados seleccionados` en la barra fija.

## Opciones

- `Parecido permitido`: controla que tan flexibles son los grupos visuales. `0` exige imagenes casi identicas, `6` es el valor recomendado y valores mas altos encuentran fotos menos parecidas, con mas riesgo de falsos positivos.
- `Max. imagenes`: cantidad maxima de imagenes a analizar. `0` analiza toda la carpeta.
- `Encontrar memes`: usa nombres comunes y una heuristica visual de texto dentro de la imagen.
- `Encontrar miniaturas/baja calidad`: detecta resoluciones pequenas y nombres tipicos de miniaturas/cache.

## Seguridad

La app no borra archivos directamente. Los mueve a:

```text
_DUPLICADOS_ELIMINADOS
```

Si revisas y confirmas que todo esta bien, puedes borrar esa carpeta manualmente cuando quieras.
