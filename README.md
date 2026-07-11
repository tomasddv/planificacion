# Dashboard Promotores

Dashboard Streamlit para KPIs diarios de promotores y planificacion comercial.

- Dos tarjetas de planificacion diaria por KPI.
- Filtros por fecha, grupo de ruta, supervisor y promotor.
- Conteo de clientes ruta, activaciones nuevas, restantes y cumplimiento.
- Vista de acumulado mensual por ruta.
- Listado de clientes no compradores por foco/KPI.
- Cruce de nombre de fantasia desde plantilla de clientes.

## Reglas principales

- `CCC`: clientes unicos con compra/activacion del foco.
- `TBD`: SKUs vendidos por cliente.
- `Value`: solo `CERVEZAS` + marca `QUILMES 1890`.
- Rutas agrupadas como `LUJU`, `MAVI`, `MISA`.
- Para planificacion diaria, la ruta se asigna por el dia trabajado anterior a la fecha de venta. Si la venta cae lunes, toma sabado.

## Uso local

1. Colocar los archivos fuente en `C:\Users\triesgo\Desktop\CCC`:
   - `RUTAS 7-26.xlsx`
   - `AUXILIARES.xlsx`
   - `VENTA DIARIA.txt`
   - `*plantillaClientesAR*.xlsx` (opcional, para nombre de fantasia)

2. Instalar dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

3. Ejecutar:

```powershell
.\.venv\Scripts\streamlit.exe run app.py --server.address 127.0.0.1 --server.port 8503
```

## Deploy en Streamlit Community Cloud

El repo debe apuntar a esta carpeta o tener estos archivos en la raiz de la app:

- `app.py`
- `dashboard_data.py`
- `requirements.txt`
- `.streamlit/config.toml`

Los archivos de datos no se suben al repo. La app permite indicar la carpeta local de datos desde la barra lateral para uso local.
