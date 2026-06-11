# Publicar dashboard de Planificacion

## Archivos a subir a GitHub

- `app.py`
- `planificador_promotores.py`
- `crear_sheet_planificacion.gs`
- `requirements.txt`
- `README.md`
- `.gitignore`
- `PUBLICAR_STREAMLIT_CLOUD.md`
- `.streamlit/config.toml`
- `.streamlit/secrets.example.toml`

No subir:

- `.streamlit/secrets.toml`
- `.cloud_data/`
- `.venv/`
- `__pycache__/`
- logs o PDFs generados.

## Streamlit Cloud

Crear una app nueva desde GitHub y usar:

- Main file path: `app.py`
- Branch: `main`

Para publicar el planificador separado de promotores, crear una segunda app en Streamlit Cloud apuntando al mismo repositorio y usar:

- Main file path: `planificador_promotores.py`
- Branch: `main`

En Secrets pegar:

```toml
GOOGLE_DRIVE_PLANIFICACION_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot?usp=drive_link"
FORCE_GDRIVE_REFRESH = "false"
PLANNER_GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/15ITRhsY5mvK3NSHeOKV2MymC078pT9TPAwKUdZDfjnI/edit?usp=sharing"
PLANNER_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbwDlxEbBN2kmy5oVtb4LJiPFN0KtAZw-nI9TolDtfOIVuMxQqIZprMB1pquTesPGYHe/exec"
```

Para forzar actualizacion de datos, cambiar temporalmente `FORCE_GDRIVE_REFRESH` a `"true"`, reiniciar la app y luego volverlo a `"false"`.

## Planificacion diaria

La carga del planificado se hace en el dashboard. El dashboard guarda en un Google Sheet simple para que cualquier PC que abra el dashboard vuelva a ver el planificado.

Formato recomendado:

- Un archivo de Google Sheets con una hoja por supervisor.
- En cada hoja, cuatro cuadros con los titulos `TOTAL CERVEZAS`, `VOLUMEN ABOVE CORE`, `Total UNG` y `Aguas`.
- Cada cuadro debe tener las columnas `Promotor`, `Objetivo` y `Planificacion`.
- Compartir el Sheet como `Anyone with the link`.
- Pegar la URL del Sheet en `PLANNER_GOOGLE_SHEET_URL`.
- Pegar el contenido de `crear_sheet_planificacion.gs` en Apps Script del Sheet.
- Publicar Apps Script como Web App y pegar la URL en `PLANNER_WEBAPP_URL`.
- En el dashboard, cargar el planificado y presionar `Guardar planificado del dia`.
- Al abrir el dashboard en otra PC, el planificado se lee desde el Sheet.

### Publicar Apps Script como Web App

En el Google Sheet:

1. Ir a `Extensiones` > `Apps Script`.
2. Pegar/actualizar el codigo de `crear_sheet_planificacion.gs`.
3. Ejecutar una vez `crearPlanificadorDiario` y aceptar permisos.
4. Ir a `Deploy` > `New deployment`.
5. Elegir tipo `Web app`.
6. Configurar:
   - `Execute as`: `Me`
   - `Who has access`: `Anyone`
7. Copiar la URL que termina en `/exec`.
8. Pegar esa URL en Streamlit Secrets como `PLANNER_WEBAPP_URL`.

Con esto, el usuario carga en el dashboard, el dashboard guarda en el Sheet, y cualquier PC que abra el dashboard vuelve a leer ese planificado.

La solapa `Planificador diario` tambien conserva el metodo manual:

- A la manana cargar los valores y presionar `Guardar planificado del dia`.
- Para conservarlo o usarlo en otra PC, presionar `Descargar planificado guardado`.
- En otra PC o sesion nueva, usar `Restaurar planificado guardado` y subir ese CSV.
- A la tarde, al actualizar `ventadiaria`, el dashboard coteja el planificado contra la venta real.

Este metodo no usa Google Cloud ni service account.
