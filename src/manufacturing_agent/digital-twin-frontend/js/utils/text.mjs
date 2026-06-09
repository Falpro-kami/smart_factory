export function normalizeText(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[\s_-]+/g, "")
    .trim();
}

export function firstField(row, keys, fallback = "-") {
  const normalizedMap = new Map(Object.keys(row || {}).map((key) => [normalizeText(key), key]));
  for (const key of keys) {
    const actualKey = normalizedMap.get(normalizeText(key));
    if (actualKey && row[actualKey] !== undefined && row[actualKey] !== null && row[actualKey] !== "") {
      return row[actualKey];
    }
  }
  return fallback;
}

export function rowText(row) {
  return Object.entries(row || {})
    .filter(([key]) => key !== "__table")
    .map(([key, value]) => `${key} ${value}`)
    .join(" ");
}
