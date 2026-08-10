// Pagina apelurilor. Filtrele se traduc în SQL și se execută în browser.

import { distinctFromList, query, queryOne } from "./db.js";
import { count, day, daysLeft, escape, list, money, shorten } from "./format.js";

const PE_PAGINA = 25;
const TOATE = "toate";

const stare = {
  cauta: "",
  stare: "Activ",
  domeniu: TOATE,
  beneficiar: TOATE,
  buget: "",
  software: false,
  pagina: 0,
};

const el = (id) => document.getElementById(id);

/** Condițiile de filtrare, ca fragment SQL plus parametrii lui. */
function unde() {
  const parti = [];
  const valori = [];
  if (stare.stare !== TOATE) {
    parti.push("status = ?");
    valori.push(stare.stare);
  }
  if (stare.domeniu !== TOATE) {
    parti.push("list_contains(domains, ?)");
    valori.push(stare.domeniu);
  }
  if (stare.beneficiar !== TOATE) {
    parti.push("list_contains(beneficiaries, ?)");
    valori.push(stare.beneficiar);
  }
  if (stare.buget) {
    parti.push("coalesce(budget_amount, 0) >= ?");
    valori.push(Number(stare.buget));
  }
  if (stare.software) parti.push("is_software");
  if (stare.cauta.trim()) {
    parti.push("lower(title) LIKE ?");
    valori.push(`%${stare.cauta.trim().toLowerCase()}%`);
  }
  return { sql: parti.length ? `WHERE ${parti.join(" AND ")}` : "", valori };
}

async function deseneaza() {
  const { sql, valori } = unde();

  const sinteza = await queryOne(
    `SELECT count(*) AS n,
            sum(CASE WHEN budget_currency = 'EUR' THEN budget_amount END) AS eur,
            sum(CASE WHEN is_software THEN 1 ELSE 0 END) AS software,
            min(CASE WHEN closes_at >= current_date THEN closes_at END) AS urmator
       FROM apeluri ${sql}`,
    valori,
  );

  el("k-total").textContent = count(sinteza.n);
  el("k-buget").textContent = sinteza.eur ? money(sinteza.eur, "EUR") : "—";
  el("k-software").textContent = count(sinteza.software);
  const zile = daysLeft(sinteza.urmator);
  el("k-termen").textContent = zile === null ? "—" : `${zile} zile`;

  const total = Math.max(1, Math.ceil(Number(sinteza.n) / PE_PAGINA));
  if (stare.pagina >= total) stare.pagina = total - 1;
  el("pagina").textContent = `${stare.pagina + 1} / ${total}`;
  el("inapoi").disabled = stare.pagina === 0;
  el("inainte").disabled = stare.pagina >= total - 1;

  // Termenul cel mai apropiat primul: dacă se închide luni, contează acum.
  const randuri = await query(
    `SELECT call_id, title, url, status, closes_at, budget_amount, budget_currency,
            domains, beneficiaries, is_software
       FROM apeluri ${sql}
      ORDER BY closes_at IS NULL, closes_at
      LIMIT ${PE_PAGINA} OFFSET ${stare.pagina * PE_PAGINA}`,
    valori,
  );

  el("randuri").innerHTML = randuri.length
    ? randuri.map(rand).join("")
    : `<tr><td colspan="6" class="stare">Niciun apel nu se potrivește filtrelor.</td></tr>`;
}

const CULORI = { Activ: "verde", Urmează: "", Închis: "gri", Necunoscut: "gri" };

function rand(a) {
  const zile = daysLeft(a.closes_at);
  const termen =
    zile === null ? "" : zile >= 0 ? `<small>${zile} zile</small>` : "<small>trecut</small>";
  return `<tr>
    <td><span class="eticheta ${CULORI[a.status] ?? "gri"}">${escape(a.status)}</span></td>
    <td>
      <a href="${escape(a.url)}" target="_blank" rel="noopener">${escape(shorten(a.title, 110))}</a>
      ${a.is_software ? '<small><span class="eticheta">software</span></small>' : ""}
    </td>
    <td><small>${escape(list(a.domains))}</small></td>
    <td><small>${escape(list(a.beneficiaries))}</small></td>
    <td class="num">${escape(money(a.budget_amount, a.budget_currency ?? ""))}</td>
    <td class="num">${escape(day(a.closes_at))}${termen}</td>
  </tr>`;
}

async function umpleMeniuri() {
  const stari = await query("SELECT DISTINCT status FROM apeluri WHERE status IS NOT NULL ORDER BY status");
  optiuni(el("stare"), [TOATE, ...stari.map((r) => r.status)], stare.stare);
  optiuni(el("domeniu"), [TOATE, ...(await distinctFromList("apeluri", "domains"))], TOATE);
  optiuni(el("beneficiar"), [TOATE, ...(await distinctFromList("apeluri", "beneficiaries"))], TOATE);
}

function optiuni(select, valori, selectata) {
  select.innerHTML = valori
    .map((v) => `<option value="${escape(v)}"${v === selectata ? " selected" : ""}>${escape(v)}</option>`)
    .join("");
}

function leaga() {
  const schimba = (camp, transforma = (v) => v) => (event) => {
    stare[camp] = transforma(event.target);
    stare.pagina = 0;
    deseneaza();
  };
  el("cauta").addEventListener("input", debounce(schimba("cauta", (t) => t.value), 250));
  el("stare").addEventListener("change", schimba("stare", (t) => t.value));
  el("domeniu").addEventListener("change", schimba("domeniu", (t) => t.value));
  el("beneficiar").addEventListener("change", schimba("beneficiar", (t) => t.value));
  el("buget").addEventListener("input", debounce(schimba("buget", (t) => t.value), 350));
  el("software").addEventListener("change", schimba("software", (t) => t.checked));
  el("inapoi").addEventListener("click", () => {
    stare.pagina = Math.max(0, stare.pagina - 1);
    deseneaza();
  });
  el("inainte").addEventListener("click", () => {
    stare.pagina += 1;
    deseneaza();
  });
  el("reset").addEventListener("click", () => {
    Object.assign(stare, { cauta: "", stare: "Activ", domeniu: TOATE, beneficiar: TOATE, buget: "", software: false, pagina: 0 });
    el("filtre").reset();
    el("stare").value = "Activ";
    deseneaza();
  });
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function actualizat() {
  try {
    const raspuns = await fetch("data/actualizare.json", { cache: "no-cache" });
    if (!raspuns.ok) return;
    const info = await raspuns.json();
    el("subsol").textContent =
      `Ultima actualizare: ${String(info.started_at).slice(0, 16)} UTC. ` +
      "Registrul rulează în întregime în browser: fișierele sunt citite direct, fără server.";
  } catch {
    /* fără fișier de stare, subsolul rămâne cum e */
  }
}

try {
  await umpleMeniuri();
  leaga();
  await deseneaza();
  actualizat();
} catch (eroare) {
  el("randuri").innerHTML =
    `<tr><td colspan="6" class="stare">Registrul nu a putut fi încărcat: ${escape(eroare)}</td></tr>`;
}
