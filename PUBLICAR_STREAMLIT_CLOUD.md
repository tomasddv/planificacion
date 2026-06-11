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
GOOGLE_SHEET_ID = "PEGAR_ID_O_URL_DEL_SHEET_DE_PLANIFICACION"
GOOGLE_SERVICE_ACCOUNT_JSON = """
{
  "type": "service_account",
  "project_id": "...",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n",
  "client_email": "...@....iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "..."
}
"""
```

Para forzar actualizacion de datos, cambiar temporalmente `FORCE_GDRIVE_REFRESH` a `"true"`, reiniciar la app y luego volverlo a `"false"`.

Para que el planificador diario se guarde en Google Sheets, crear/usar un Sheet y compartirlo con el `client_email`
del JSON de cuenta de servicio con permiso de editor. La app crea automaticamente la hoja `planificador_diario`.
