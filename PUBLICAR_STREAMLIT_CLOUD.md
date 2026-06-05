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
```

Para forzar actualizacion de datos, cambiar temporalmente `FORCE_GDRIVE_REFRESH` a `"true"`, reiniciar la app y luego volverlo a `"false"`.
