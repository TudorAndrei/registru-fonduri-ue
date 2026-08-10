// Interogarea registrului, direct în browser.
//
// Fișierele Parquet stau lângă pagină, iar DuckDB-WASM le citește prin cereri
// HTTP cu interval: nu descarcă tot fișierul ca să numere rândurile, ci doar
// grupurile de rânduri și coloanele cerute. De aceea registrul de 5,7 MB se
// poate servi de pe o găzduire statică fără niciun server de baze de date.

const DUCKDB = "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm";

let ready = null;

async function boot() {
  const duckdb = await import(DUCKDB);
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const worker = await duckdb.createWorker(bundle.mainWorker);
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  const conn = await db.connect();

  const base = new URL("data/", document.baseURI).href;
  await conn.query(`CREATE VIEW apeluri AS SELECT * FROM read_parquet('${base}apeluri.parquet')`);
  await conn.query(`CREATE VIEW registru AS SELECT * FROM read_parquet('${base}registru.parquet')`);
  return conn;
}

/** Conexiunea, pornită o singură dată și refolosită. */
export function db() {
  if (!ready) ready = boot();
  return ready;
}

/** Rulează SQL și întoarce rânduri ca obiecte simple. */
export async function query(sql, params = []) {
  const conn = await db();
  let statement = sql;
  // Parametrii se pun prin `prepare`, ca să nu existe interpolare de text.
  if (params.length) {
    const prepared = await conn.prepare(statement);
    const result = await prepared.query(...params);
    return result.toArray().map(normalize);
  }
  const result = await conn.query(statement);
  return result.toArray().map(normalize);
}

/** Un singur rând, sau null. */
export async function queryOne(sql, params = []) {
  const rows = await query(sql, params);
  return rows.length ? rows[0] : null;
}

/** Valorile distincte dintr-o coloană-listă, pentru meniurile de filtrare. */
export async function distinctFromList(view, column) {
  const rows = await query(
    `SELECT DISTINCT unnest(${column}) AS v FROM ${view} WHERE ${column} IS NOT NULL ORDER BY v`,
  );
  return rows.map((r) => r.v).filter(Boolean);
}

// Arrow întoarce obiecte proprii: BigInt pentru întregi, milisecunde pentru
// date, `Vector` pentru liste. Aici devin valori pe care le poate folosi restul
// codului fără să știe de Arrow.
function normalize(row) {
  const out = {};
  for (const [key, value] of Object.entries(row)) out[key] = plain(value);
  return out;
}

function plain(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "bigint") return Number(value);
  if (value?.toArray) return Array.from(value.toArray()).map(plain);
  if (Array.isArray(value)) return value.map(plain);
  return value;
}
