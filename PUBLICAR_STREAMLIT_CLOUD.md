# Publicar dashboard de Planificacion

## Archivos a subir a GitHub

- `app.py`
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

En Secrets pegar:

```toml
GOOGLE_DRIVE_PLANIFICACION_URL = "https://drive.google.com/drive/folders/1cukgXLUaPsEDK_yD7tSwgaBFZAbiDUot?usp=drive_link"
FORCE_GDRIVE_REFRESH = "false"
PLANNER_GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/PEGAR_ID_DEL_SHEET/edit?usp=sharing"
```

Para forzar actualizacion de datos, cambiar temporalmente `FORCE_GDRIVE_REFRESH` a `"true"`, reiniciar la app y luego volverlo a `"false"`.

## Planificacion diaria

La carga del planificado puede venir desde un Google Sheet simple, sin Google Cloud ni service account.

Formato recomendado:

- Un archivo de Google Sheets con una hoja por supervisor.
- En cada hoja, cuatro cuadros con los titulos `TOTAL CERVEZAS`, `VOLUMEN ABOVE CORE`, `Total UNG` y `Aguas`.
- Cada cuadro debe tener las columnas `Promotor`, `Objetivo` y `Planificacion`.
- Compartir el Sheet como `Anyone with the link` con permiso de editor para que los supervisores carguen.
- Pegar la URL del Sheet en `PLANNER_GOOGLE_SHEET_URL`.
- En el dashboard, presionar `Actualizar datos` para releer la planificacion.

La solapa `Planificador diario` tambien conserva el metodo manual:

- A la manana cargar los valores y presionar `Guardar planificado del dia`.
- Para conservarlo o usarlo en otra PC, presionar `Descargar planificado guardado`.
- En otra PC o sesion nueva, usar `Restaurar planificado guardado` y subir ese CSV.
- A la tarde, al actualizar `ventadiaria`, el dashboard coteja el planificado contra la venta real.

Este metodo no usa Google Cloud ni service account.
