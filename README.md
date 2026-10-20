# Dashboard Promotores

## Seguimiento de usabilidad de combos

En `planificador_promotores.py`, elegir **Usabilidad combos** en la barra lateral.
En `app.py`, abrir la pestaña **Usabilidad combos**. El seguimiento usa la venta
original `ventadiaria` y `REPORTE DE CLIENTES.xlsx`; no depende del Sheet de planificación.
Usar **Actualizar Drive y Sheet** (o **Actualizar datos** en ventas) después de actualizar
la fuente. El planificador renueva su caché de Drive a los 15 minutos al volver a consultar.
El tablero muestra la última fecha de venta y permite elegir el corte mensual y rutas.

El catálogo incluye los 11 combos del reporte de octubre de 2026. Los SKU 900445 y
900460 comparten una clave y cuentan cada cliente una sola vez. Las unidades se
calculan por importe neto / precio neto, incluyendo devoluciones y domingos;
CCC cuenta clientes con saldo neto positivo en el mes. El objetivo se recalcula
como grupo asignado intersectado con clientes del maestro con ruta válida
(excluye vacía, 0, 999 y 9999). Los clientes que compran fuera del objetivo quedan
en un control separado. Las cifras pueden cambiar respecto del Excel estático
si cambia la venta o el maestro; no se usa el Excel como acumulado inicial.

`combos_catalogo.csv` contiene SKU, clave comercial, categoría, descripción y grupo.
`combos_grupos.csv` contiene únicamente grupo y código de cliente, sin nombres ni
datos de contacto, con el padrón inicial recibido para octubre de 2026. Actualizar
ese padrón si cambian las membresías. Para administrarlo desde Drive, configurar
`COMBOS_GRUPOS_DRIVE_ID` con el ID del CSV (columnas `grupo,cliente`); se descarga
con el resto de las fuentes del planificador. Si no existe un CSV en la carpeta de
datos, se usa el incluido en el repositorio. No se deducen membresías a partir de ventas.
Los objetivos por combo se superponen: el tablero informa clientes únicos globales,
sin sumar porcentajes ni objetivos como si fueran clientes distintos.

Validación del motor: `python -m unittest discover -s tests -v`.

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
