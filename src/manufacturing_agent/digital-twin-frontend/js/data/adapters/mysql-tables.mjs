export function normalizeTables(tables) {
  if (!Array.isArray(tables)) {
    return [];
  }

  return tables.map((table, index) => ({
    name: String(table?.name || `table_${index + 1}`),
    columns: Array.isArray(table?.columns) ? table.columns.map(String) : [],
    rows: Array.isArray(table?.rows) ? table.rows.filter((row) => row && typeof row === "object") : [],
  }));
}

export function flattenRows(tables) {
  return normalizeTables(tables).flatMap((table) =>
    table.rows.map((row) => ({
      ...row,
      __table: table.name,
    }))
  );
}
