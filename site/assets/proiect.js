// Fișa unui proiect.
//
// Pentru listele naționale 2014-2020 nu există o pagină publică per proiect —
// autoritățile publică doar fișiere. Aceasta este pagina care lipsește, și de
// aici pleacă legăturile către ce se poate verifica.

import { queryOne } from "./db.js";
import { day, escape, money } from "./format.js";

const KOHESIO_FISA = "https://kohesio.ec.europa.eu/en/projects/";
const KOHESIO_CAUTARE = "https://kohesio.ec.europa.eu/en/projects?keywords=";
const ANAF = "https://mfinante.gov.ro/ro/web/site/info-fiscale?cui=";

const id = new URLSearchParams(location.search).get("id");
const gazda = document.getElementById("fisa");

if (!id) {
  gazda.innerHTML = '<p class="stare">Lipsește identificatorul proiectului.</p>';
} else {
  try {
    const p = await queryOne("SELECT * FROM registru WHERE record_id = ?", [id]);
    gazda.innerHTML = p ? deseneaza(p) : '<p class="stare">Proiectul nu există în registru.</p>';
    if (p) document.title = `${p.project_title ?? "Proiect"} — Registru fonduri UE`;
  } catch (eroare) {
    gazda.innerHTML = `<p class="stare">Proiectul nu a putut fi încărcat: ${escape(eroare)}</p>`;
  }
}

function deseneaza(p) {
  const judete = (p.counties ?? []).join(", ") || "—";
  const regiuni = (p.regions ?? []).join(", ") || "—";
  const fisaOficiala =
    p.source === "kohesio" && p.project_code ? KOHESIO_FISA + encodeURIComponent(p.project_code) : null;
  const cautare =
    KOHESIO_CAUTARE +
    encodeURIComponent(`${p.project_title ?? ""} ${p.beneficiary_name ?? ""}`.slice(0, 120));

  return `
  <header class="sus">
    <div>
      <h1>${escape(p.project_title ?? "Proiect fără titlu")}</h1>
      <p>${escape(p.beneficiary_name ?? "—")}</p>
    </div>
  </header>

  ${p.project_summary ? `<section><p>${escape(p.project_summary)}</p></section>` : ""}

  <section>
    <h2>Legături</h2>
    <p>
      ${fisaOficiala ? `<a href="${escape(fisaOficiala)}" target="_blank" rel="noopener">Fișa oficială Kohesio</a> · ` : ""}
      <a href="${escape(cautare)}" target="_blank" rel="noopener">Caută în Kohesio</a>
      ${p.beneficiary_cui ? ` · <a href="${escape(ANAF + encodeURIComponent(p.beneficiary_cui))}" target="_blank" rel="noopener">Date fiscale beneficiar</a>` : ""}
      ${p.source_url ? ` · <a href="${escape(p.source_url)}" target="_blank" rel="noopener">Fișierul-sursă</a>` : ""}
    </p>
    <p style="color:var(--sters);font-size:.82rem">
      Pentru listele naționale 2014-2020 nu există o pagină publică per proiect: autoritățile
      publică doar fișiere. Căutarea Kohesio este o încercare de a găsi proiectul, nu un link garantat.
    </p>
  </section>

  <section>
    <h2>Date</h2>
    <dl>
      ${rand("Program", p.program)}
      ${rand("Perioadă de programare", p.programming_period)}
      ${rand("Cod proiect", p.project_code)}
      ${rand("Beneficiar", p.beneficiary_name)}
      ${rand("CUI beneficiar", p.beneficiary_cui)}
      ${rand("Tip beneficiar", p.beneficiary_type)}
      ${rand("Județe", judete)}
      ${rand("Regiuni", regiuni)}
      ${rand("Localitate", p.locality)}
      ${rand("Dată de început", day(p.start_date))}
      ${rand("Dată de sfârșit", day(p.end_date))}
      ${rand("Stadiu", p.status)}
      ${rand("Valoare eligibilă", money(p.total_eligible_amount, p.currency ?? ""))}
      ${rand("Valoare totală", money(p.total_project_amount, p.currency ?? ""))}
      ${rand("Contribuția UE", money(p.eu_amount, p.currency ?? ""))}
      ${rand("Plăți efectuate", money(p.payments_amount, p.currency ?? ""))}
      ${rand("Obiectiv specific", p.specific_objective)}
      ${rand("Cod de intervenție", p.intervention_code)}
    </dl>
  </section>

  <section>
    <h2>Clasificare software</h2>
    <dl>
      ${rand("Etichetă", p.software_label)}
      ${rand("Scor", Number(p.software_score ?? 0).toFixed(2))}
      ${rand("Motivul scorului", p.software_evidence)}
    </dl>
  </section>

  <section>
    <h2>Proveniență</h2>
    <dl>
      ${rand("Sursă", p.source)}
      ${rand("Set de date", p.source_dataset)}
      ${rand("Fișier", p.source_file)}
      ${rand("Rând în fișier", p.source_row)}
      ${rand("Amprentă SHA-256", p.source_sha256)}
      ${rand("Descărcat la", p.fetched_at)}
    </dl>
  </section>`;
}

function rand(eticheta, valoare) {
  const text = valoare === null || valoare === undefined || valoare === "" ? "—" : String(valoare);
  return `<dt>${escape(eticheta)}</dt><dd>${escape(text)}</dd>`;
}
