const SUPERVISORES = {
  "ISMAEL BRUNO": [
    "GASTON FABRE",
    "MATIAS GARCIA",
    "NICASTRO LUCAS",
    "NICOLAS POCHETINO",
    "SIRI MARTIN",
    "VILLAGRA ENZO",
  ],
  "ANIBAL VITI": [
    "FEDERICO BISS",
  ],
  "CASCO HERNAN": [
    "PABLO ALVAREZ",
    "ALEXANDER ROJAS",
    "FERNANDO FIELG",
    "JUAN MANUEL GIMENEZ",
    "MENDEZ CARLOS",
    "MARIANO HERRERA",
  ],
};

const FOCOS = [
  { titulo: "TOTAL CERVEZAS", fila: 5, columna: 1 },
  { titulo: "VOLUMEN ABOVE CORE", fila: 5, columna: 6 },
  { titulo: "Total UNG", fila: 21, columna: 1 },
  { titulo: "Aguas", fila: 21, columna: 6 },
];

const FOCO_ALIASES = {
  "FOCO 1 TOTAL CERVEZAS 2026": "TOTAL CERVEZAS",
  "TOTAL CERVEZAS": "TOTAL CERVEZAS",
  "TOTAL CZA": "TOTAL CERVEZAS",
  "TOTAL CVZA": "TOTAL CERVEZAS",
  "FOCO 2 ABOVE CORE 2026": "VOLUMEN ABOVE CORE",
  "ABOVE CORE": "VOLUMEN ABOVE CORE",
  "VOLUMEN ABOVE CORE": "VOLUMEN ABOVE CORE",
  "FOCO 3 TOTAL UNG 2026": "Total UNG",
  "TOTAL UNG": "Total UNG",
  "UNG": "Total UNG",
  "FOCO 4 TOTAL AGUAS 2026": "Aguas",
  "TOTAL AGUAS": "Aguas",
  "AGUAS": "Aguas",
};

const PROMOTOR_ALIASES = {
  "ENZO VILLAGRA": "VILLAGRA ENZO",
};

function crearPlanificadorDiario() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  Object.entries(SUPERVISORES).forEach(([supervisor, promotores]) => {
    let sheet = ss.getSheetByName(supervisor);
    if (!sheet) {
      sheet = ss.insertSheet(supervisor);
    }
    sheet.clear();
    sheet.setHiddenGridlines(false);
    sheet.setFrozenRows(0);

    sheet.getRange("A1:B3").setValues([
      ["Dias Laborales", ""],
      ["Dias Trabajados", ""],
      ["Restan", ""],
    ]);
    sheet.getRange("A1:A3").setFontWeight("bold").setHorizontalAlignment("right");
    sheet.getRange("B1:B3").setBackground("#fff2cc").setHorizontalAlignment("center");

    FOCOS.forEach((foco) => crearCuadro(sheet, foco, promotores));

    sheet.setColumnWidths(1, 1, 200);
    sheet.setColumnWidths(2, 1, 90);
    sheet.setColumnWidths(3, 1, 125);
    sheet.setColumnWidths(6, 1, 200);
    sheet.setColumnWidths(7, 1, 90);
    sheet.setColumnWidths(8, 1, 125);
  });

  const defaultSheet = ss.getSheetByName("Hoja 1") || ss.getSheetByName("Sheet1");
  if (defaultSheet && Object.keys(SUPERVISORES).indexOf(defaultSheet.getName()) === -1) {
    ss.deleteSheet(defaultSheet);
  }
}

function crearCuadro(sheet, foco, promotores) {
  const row = foco.fila;
  const col = foco.columna;
  const totalRow = row + 2 + promotores.length;

  sheet.getRange(row, col, 1, 3)
    .merge()
    .setValue(foco.titulo)
    .setFontWeight("bold")
    .setFontLine("underline")
    .setHorizontalAlignment("center")
    .setBackground("#ffffff");

  sheet.getRange(row + 1, col, 1, 3)
    .setValues([["Promotor", "Objetivo", "Planificación"]])
    .setFontWeight("bold")
    .setFontSize(12)
    .setHorizontalAlignment("center")
    .setBackground("#ffffff");

  const rows = promotores.map((promotor) => [promotor, "", ""]);
  sheet.getRange(row + 2, col, promotores.length, 3).setValues(rows);
  sheet.getRange(row + 2, col, promotores.length, 1).setHorizontalAlignment("left");
  sheet.getRange(row + 2, col + 1, promotores.length, 2).setHorizontalAlignment("center");
  sheet.getRange(row + 2, col + 2, promotores.length, 1).setBackground("#ffc000");

  sheet.getRange(totalRow, col, 1, 3)
    .setValues([["Totales", `=SUM(${colLetra(col + 1)}${row + 2}:${colLetra(col + 1)}${totalRow - 1})`, `=SUM(${colLetra(col + 2)}${row + 2}:${colLetra(col + 2)}${totalRow - 1})`]])
    .setFontWeight("bold")
    .setHorizontalAlignment("center")
    .setBackground("#ffff00");
  sheet.getRange(totalRow, col + 2).setBackground("#ffc000");

  sheet.getRange(row + 1, col, promotores.length + 2, 3)
    .setBorder(true, true, true, true, true, true, "#000000", SpreadsheetApp.BorderStyle.SOLID);

  sheet.getRange(row + 2, col + 1, promotores.length + 1, 2).setNumberFormat("#,##0.0");
}

function colLetra(col) {
  let letra = "";
  while (col > 0) {
    const mod = (col - 1) % 26;
    letra = String.fromCharCode(65 + mod) + letra;
    col = Math.floor((col - mod) / 26);
  }
  return letra;
}

function doPost(e) {
  try {
    const rawPayload = (e.parameter && e.parameter.payload)
      ? e.parameter.payload
      : (e.postData && e.postData.contents ? e.postData.contents : "{}");
    const payload = JSON.parse(rawPayload || "{}");
    const result = guardarPlanificacionDesdeDash(payload);
    return ContentService
      .createTextOutput(JSON.stringify({ ok: true, ...result }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(error && error.message ? error.message : error) }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function guardarPlanificacionDesdeDash(payload) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  const updatedAt = new Date();
  let escritos = 0;
  const errores = [];

  rows.forEach((row) => {
    const focoTitulo = normalizarFoco(row.foco);
    const promotor = normalizarPromotor(row.promotor);
    if (!focoTitulo || !promotor) {
      return;
    }
    const baseRow = {
      fecha: payload.fecha || row.fecha || "",
      foco: focoTitulo,
      promotor: promotor,
      planificado: row.planificado === "" ? "" : Number(row.planificado),
      supervisor: "",
      celda: "",
      actualizado: updatedAt,
    };
    const ubicacion = buscarCeldaPlanificacion(ss, focoTitulo, promotor);
    if (!ubicacion) {
      errores.push(`${row.foco} / ${row.promotor}`);
      upsertBDPlanificacion(ss, baseRow);
      escritos += 1;
      return;
    }
    ubicacion.sheet.getRange(ubicacion.row, ubicacion.col).setValue(row.planificado === "" ? "" : Number(row.planificado));
    upsertBDPlanificacion(ss, {
      fecha: baseRow.fecha,
      foco: focoTitulo,
      promotor: promotor,
      planificado: baseRow.planificado,
      supervisor: ubicacion.sheet.getName(),
      celda: `${ubicacion.sheet.getName()}!${colLetra(ubicacion.col)}${ubicacion.row}`,
      actualizado: updatedAt,
    });
    escritos += 1;
  });

  return { escritos, errores };
}

function buscarCeldaPlanificacion(ss, focoTitulo, promotorBuscado) {
  const sheets = ss.getSheets().filter((sheet) => sheet.getName() !== "BD_PLANIFICACION");
  for (const sheet of sheets) {
    const values = sheet.getDataRange().getValues();
    for (let r = 0; r < values.length; r++) {
      for (let c = 0; c < values[r].length; c++) {
        if (normalizarFoco(values[r][c]) !== focoTitulo) {
          continue;
        }
        const header = buscarHeader(values, r);
        if (!header) {
          continue;
        }
        for (let rr = header.row + 1; rr < values.length; rr++) {
          const promotor = normalizarPromotor(values[rr][header.promotorCol]);
          if (!promotor || promotor.indexOf("TOTALES") >= 0 || promotor.indexOf("TOTAL") >= 0) {
            break;
          }
          if (promotor === promotorBuscado) {
            return { sheet, row: rr + 1, col: header.planCol + 1 };
          }
        }
      }
    }
  }
  return null;
}

function buscarHeader(values, titleRow) {
  for (let r = titleRow; r < Math.min(titleRow + 8, values.length); r++) {
    const row = values[r].map((value) => normalizarTexto(value));
    const promotorCol = row.findIndex((value) => value.indexOf("PROMOTOR") >= 0);
    const planCol = row.findIndex((value) => value.indexOf("PLANIFIC") >= 0);
    if (promotorCol >= 0 && planCol >= 0) {
      return { row: r, promotorCol, planCol };
    }
  }
  return null;
}

function upsertBDPlanificacion(ss, row) {
  let sheet = ss.getSheetByName("BD_PLANIFICACION");
  if (!sheet) {
    sheet = ss.insertSheet("BD_PLANIFICACION");
    sheet.getRange(1, 1, 1, 7).setValues([["fecha", "foco", "promotor", "planificado", "supervisor", "celda", "actualizado"]]);
    sheet.getRange(1, 1, 1, 7).setFontWeight("bold").setBackground("#d9eaf7");
  }
  const values = sheet.getDataRange().getValues();
  const key = `${row.fecha}|${row.foco}|${row.promotor}`;
  for (let r = 1; r < values.length; r++) {
    const existingKey = `${values[r][0]}|${values[r][1]}|${normalizarPromotor(values[r][2])}`;
    if (existingKey === key) {
      sheet.getRange(r + 1, 1, 1, 7).setValues([[row.fecha, row.foco, row.promotor, row.planificado, row.supervisor, row.celda, row.actualizado]]);
      return;
    }
  }
  sheet.appendRow([row.fecha, row.foco, row.promotor, row.planificado, row.supervisor, row.celda, row.actualizado]);
}

function normalizarFoco(value) {
  const text = normalizarTexto(value);
  return FOCO_ALIASES[text] || "";
}

function normalizarTexto(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Z0-9]+/g, " ")
    .trim()
    .toUpperCase();
}

function normalizarPromotor(value) {
  const text = normalizarTexto(value);
  return PROMOTOR_ALIASES[text] || text;
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Planificador")
    .addItem("Crear / resetear formato", "crearPlanificadorDiario")
    .addToUi();
}
