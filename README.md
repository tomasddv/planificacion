# Tablero de Venta Diaria HL

App local en Streamlit para analizar venta diaria en HL desde archivos TXT/CSV tabulados exportados del sistema.

## Como usar

1. Reemplace o copie el archivo `.txt` o `.csv` en:

   `N:\Tomas\DASHBOARDS\planificacion\`

2. La app toma automaticamente el archivo mas reciente de esa carpeta.
3. Ejecute:

   ```powershell
   pip install -r requirements.txt
   streamlit run app.py
   ```

4. En el tablero, pulse **Actualizar datos** cada vez que reemplace el archivo.

Si la carpeta no existe o no hay archivos validos, use la carga manual desde la barra lateral.

## Que calcula

- Base normalizada con fecha, calibre, negocio, ruta, vendedor, promotor, supervisor y HL.
- Dias habiles de lunes a sabado.
- HL por dia, calibre, negocio, supervisor, promotor y total distribuidora.
- Promedio, mediana, minimo, maximo, percentil 25 y percentil 75 para ventanas de 7, 14, 21 y 28 dias habiles.
- Comparacion contra el mismo dia habil del mes anterior.
- Comparacion contra archivo `venta anual` para columna AA, acumulado vs mismo periodo del año anterior, tendencia vs AA y curva diaria actual vs AA.
- KPIs y visualizaciones interactivas con filtros.

## Columnas usadas

La app combina nombres y posiciones para tolerar encabezados repetidos:

- Fecha: `Descripcion Periodo` o `Cod. Periodo`, con fallback a `Periodos`.
- Calibre: columna X, descripcion de calibre.
- HL vendidos: columna AO, `Cantidades Totales`.
- Negocio: columnas de unidad de negocio y su descripcion.
- Supervisor, vendedor y promotor: columnas de vendedor y descripcion vendedor.
- Ruta: codigo y descripcion de ruta.

## Notas

- Los numeros con coma decimal argentina se convierten automaticamente.
- Los domingos se excluyen del analisis.
- El boton **Actualizar datos** limpia cache y vuelve a leer el archivo mas reciente.
- Si existe un archivo con `anual` en el nombre dentro de la carpeta, se usa como base historica AA. Si no existe, la app deja AA en blanco y muestra el aviso correspondiente.
