// Pagina proiectelor finanțate.

import { distinctFromList, query, queryOne } from "./db.js";
import { count, escape, list, money, shorten } from "./format.js";

const PE_PAGINA = 25;
const TOATE = "toate";

const stare = {
  cauta: "",
  program: TOATE,
  regiune: TOATE,
  judet: TOATE,
  clasificare: TOATE,
  stadiu: TOATE,
  minim: "",
  ordonare: "total_eligible_amount",
  software: false,
  pagina: 0,
};

const el = (id) => document.getElementById(id);

function unde() {
  const parti = [];
  const valori = [];
  const egal = (coloana, valoare) => {
    if (valoare === TOATE) return;
    parti.push(`${coloana} = ?`);
    valori.push(valoare);
  };
  egal("program", stare.program);
  egal("software_label", stare.clasificare);
  egal("status", stare.stadiu);
  if (stare.regiune !== TOATE) {
    parti.push("list_contains(regions, ?)");
    valori.push(stare.regiune);
  }
  if (stare.judet !== TOATE) {
    // Un proiect multi-județean apare sub fiecare județ al lui.
    parti.push("list_contains(counties, ?)");
    valori.push(stare.judet);
  }
  if (stare.software) parti.push("is_software");
  if (stare.minim) {
    parti.push("coalesce(total_eligible_amount, 0) >= ?");
    valori.push(Number(stare.minim));
  }
  if (stare.cauta.trim()) {
    const cuvant = `%${stare.cauta.trim().toLowerCase()}%`;
    parti.push(
      "(lower(beneficiary_name) LIKE ? OR lower(coalesce(project_title,'')) LIKE ?" +
        " OR coalesce(beneficiary_cui,'') LIKE ?)",
    );
    valori.push(cuvant, cuvant, `%${stare.cauta.trim()}%`);
  }
  return { sql: parti.length ? `WHERE ${parti.join(" AND ")}` : "", valori };
}

async function deseneaza() {
  const { sql, valori } = unde();

  const sinteza = await queryOne(
    `SELECT count(*) AS n,
            count(DISTINCT beneficiary_key) AS beneficiari,
            sum(total_eligible_amount) AS eligibil,
            sum(payments_amount) AS platit,
            avg(CASE WHEN is_software THEN 1.0 ELSE 0.0 END) AS cota
       FROM registru ${sql}`,
    valori,
  );

  el("k-total").textContent = count(sinteza.n);
  el("k-beneficiari").textContent = count(sinteza.beneficiari);
  el("k-eligibil").textContent = money(sinteza.eligibil);
  el("k-plati").textContent = money(sinteza.platit);
  el("k-software").textContent = sinteza.cota === null ? "—" : `${Math.round(sinteza.cota * 100)}%`;

  const total = Math.max(1, Math.ceil(Number(sinteza.n) / PE_PAGINA));
  if (stare.pagina >= total) stare.pagina = total - 1;
  el("pagina").textContent = `${stare.pagina + 1} / ${total}`;
  el("inapoi").disabled = stare.pagina === 0;
  el("inainte").disabled = stare.pagina >= total - 1;

  const randuri = await query(
    `SELECT record_id, program, beneficiary_name, beneficiary_cui, project_title, counties,
            total_eligible_amount, payments_amount, status, software_label, software_score,
            is_software
       FROM registru ${sql}
      ORDER BY ${stare.ordonare} DESC NULLS LAST
      LIMIT ${PE_PAGINA} OFFSET ${stare.pagina * PE_PAGINA}`,
    valori,
  );

  el("randuri").innerHTML = randuri.length
    ? randuri.map(rand).join("")
    : `<tr><td colspan="9" class="stare">Niciun proiect nu se potrivește filtrelor.</td></tr>`;
}

const CULORI = {
  Finalizat: "verde",
  "În implementare": "",
  Reziliat: "rosu",
  "În reziliere": "rosu",
  Nefuncțional: "rosu",
  Suspendat: "rosu",
};

function rand(p) {
  return `<tr>
    <td><span class="eticheta gri">${escape(p.program ?? "—")}</span></td>
    <td>${escape(shorten(p.beneficiary_name, 60))}<small>${escape(p.beneficiary_cui ?? "—")}</small></td>
    <td>${escape(shorten(p.project_title, 90))}</td>
    <td><small>${escape(list(p.counties, 34))}</small></td>
    <td class="num">${escape(money(p.total_eligible_amount))}</td>
    <td class="num">${escape(money(p.payments_amount))}</td>
    <td><span class="eticheta ${CULORI[p.status] ?? "gri"}">${escape(p.status ?? "—")}</span></td>
    <td>
      <span class="eticheta ${p.is_software ? "" : "gri"}">${escape(p.software_label ?? "—")}</span>
      <small>${Number(p.software_score ?? 0).toFixed(2)}</small>
    </td>
    <td><a href="proiect.html?id=${encodeURIComponent(p.record_id)}">Deschide</a></td>
  </tr>`;
}

async function umpleMeniuri() {
  const distinct = async (coloana) => {
    const rows = await query(
      `SELECT DISTINCT ${coloana} AS v FROM registru WHERE ${coloana} IS NOT NULL ORDER BY v`,
    );
    return rows.map((r) => r.v).filter(Boolean);
  };
  optiuni(el("program"), [TOATE, ...(await distinct("program"))]);
  optiuni(el("regiune"), [TOATE, ...(await distinctFromList("registru", "regions"))]);
  optiuni(el("judet"), [TOATE, ...(await distinctFromList("registru", "counties"))]);
  optiuni(el("clasificare"), [TOATE, ...(await distinct("software_label"))]);
  optiuni(el("stadiu"), [TOATE, ...(await distinct("status"))]);
}

function optiuni(select, valori) {
  select.innerHTML = valori.map((v) => `<option value="${escape(v)}">${escape(v)}</option>`).join("");
}

function leaga() {
  const schimba = (camp, cum = (t) => t.value) => (e) => {
    stare[camp] = cum(e.target);
    stare.pagina = 0;
    deseneaza();
  };
  el("cauta").addEventListener("input", debounce(schimba("cauta"), 300));
  for (const camp of ["program", "regiune", "judet", "clasificare", "stadiu", "ordonare"]) {
    el(camp).addEventListener("change", schimba(camp));
  }
  el("minim").addEventListener("input", debounce(schimba("minim"), 350));
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
    Object.assign(stare, {
      cauta: "", program: TOATE, regiune: TOATE, judet: TOATE, clasificare: TOATE,
      stadiu: TOATE, minim: "", ordonare: "total_eligible_amount", software: false, pagina: 0,
    });
    el("filtre").reset();
    deseneaza();
  });
}

function debounce(fn, ms) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

try {
  await umpleMeniuri();
  leaga();
  await deseneaza();
} catch (eroare) {
  el("randuri").innerHTML =
    `<tr><td colspan="9" class="stare">Registrul nu a putut fi încărcat: ${escape(eroare)}</td></tr>`;
}
