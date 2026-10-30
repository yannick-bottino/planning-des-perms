(function () {
"use strict";

// ---------------------------------------------------------------- état

const etat = {
  etape: 1, atteinte: 1,
  config: { moteur: null, deepseek_cle: false, claude: false, codex: false },
  accueil: null,         // écran de premier lancement : { choix, phase, ... } ; null hors de cet écran
  ferme: false,          // l'outil a été arrêté depuis la page
  moteur: null,          // choix de l'étape 1
  lien: "",
  sondage: null,         // réponse de /api/sondage
  regles: null,          // { regles, non_traduits, reglages, message, manuel, moteur }
  erreurRegles: null,    // { message, index }
  calcul: null,          // réponse de /api/calculer
  bilan: null,           // réponse de /api/arbitrages
  occupe: false,
};

const NOMS_MOTEURS = { claude: "Claude", codex: "ChatGPT", deepseek: "DeepSeek", manuel: "saisie manuelle" };
const TYPES = [
  { valeur: "absence", libelle: "Absente la semaine du" },
  { valeur: "quota", libelle: "Nombre de perms du mois" },
  { valeur: "au_moins", libelle: "Au moins N perms parmi" },
  { valeur: "preference", libelle: "Préférence" },
];
const POIDS = [{ valeur: 2, libelle: "léger" }, { valeur: 20, libelle: "important" }];
const GRAVITES = { rouge: "À corriger", orange: "À vérifier", jaune: "À lire", gris: "Pour information" };

// ---------------------------------------------------------------- utilitaires

function $(id) { return document.getElementById(id); }

function el(tag, attrs, enfants) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "texte") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "classe") n.className = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const e of [].concat(enfants || [])) {
    if (e === null || e === undefined || e === false) continue;
    n.appendChild(typeof e === "string" ? document.createTextNode(e) : e);
  }
  return n;
}

function pluriel(n, mot, motPluriel) { return n + " " + (n > 1 ? (motPluriel || mot + "s") : mot); }

function annoncer(texte) { $("annonce").textContent = texte || ""; }

async function api(chemin, corps) {
  const options = corps === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps),
  };
  let rep;
  try { rep = await fetch(chemin, options); }
  catch (e) { throw new Error("L'outil ne répond plus. Relancez-le comme d'habitude (icône « Planning des perms » sur le bureau, ou lancer.bat)."); }
  let donnees = {};
  try { donnees = await rep.json(); } catch (e) { /* corps vide */ }
  if (!rep.ok) {
    const err = new Error(donnees.erreur || "Erreur inattendue.");
    err.donnees = donnees;
    throw err;
  }
  return donnees;
}

async function occuper(bouton, texteAttente, travail) {
  if (etat.occupe) return;
  etat.occupe = true;
  const texte = bouton.textContent;
  bouton.disabled = true;
  bouton.setAttribute("aria-busy", "true");
  bouton.textContent = texteAttente;
  annoncer(texteAttente);
  try { await travail(); }
  finally {
    etat.occupe = false;
    if (bouton.isConnected) {
      bouton.disabled = false;
      bouton.removeAttribute("aria-busy");
      bouton.textContent = texte;
    }
  }
}

function erreurBloc(message) {
  return el("div", { classe: "alerte rouge", role: "alert" }, [el("p", { texte: message })]);
}

function dateCourte(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? Number(m[3]) + "/" + Number(m[2]) : (iso || "");
}

// ---------------------------------------------------------------- navigation

function allerA(n) {
  etat.etape = n;
  etat.atteinte = Math.max(etat.atteinte, n);
  rendre();
  const titre = document.querySelector("#vue h1");
  if (titre) { titre.setAttribute("tabindex", "-1"); titre.focus(); }
  window.scrollTo(0, 0);
}

function rendreEtapes() {
  for (const b of document.querySelectorAll("#etapes button")) {
    const n = Number(b.dataset.etape);
    b.disabled = n > etat.atteinte || etat.occupe || !!etat.accueil;
    b.parentElement.classList.toggle("faite", n < etat.etape && n <= etat.atteinte);
    if (n === etat.etape && !etat.accueil) b.setAttribute("aria-current", "step");
    else b.removeAttribute("aria-current");
  }
  const mois = $("mois");
  if (etat.sondage) { mois.hidden = false; mois.textContent = etat.sondage.resume.titre; }
  else mois.hidden = true;
}

function rendre() {
  if (etat.ferme) return;
  arreterSuivi();
  rendreEtapes();
  const vue = $("vue");
  vue.replaceChildren();
  if (etat.accueil) { vue.appendChild(vueAccueil()); return; }
  const vues = { 1: vueSondage, 2: vueResume, 3: vueRegles, 4: vueArbitrage, 5: vueExcel };
  vue.appendChild(vues[etat.etape]());
}

// ---------------------------------------------------------------- étape 1

function choixMoteur() {
  const c = etat.config;
  const choix = etat.moteur || c.moteur
    || (c.claude ? "claude" : c.codex ? "codex" : c.deepseek_cle ? "deepseek" : "manuel");
  return (choix === "claude" || choix === "codex") && !c[choix] ? (c.deepseek_cle ? "deepseek" : "manuel") : choix;
}

function blocCleDeepSeek() {
  const zone = el("div", { classe: "cle" });
  if (etat.config.deepseek_cle_environnement) {
    zone.append(el("p", { classe: "ok-ligne", texte: "Une clé DeepSeek est fournie par l'ordinateur (variable DEEPSEEK_API_KEY)." }));
    return zone;
  }
  if (etat.config.deepseek_cle) {
    zone.append(
      el("p", { classe: "ok-ligne", texte: "Une clé DeepSeek est enregistrée sur cet ordinateur." }),
      el("button", { type: "button", classe: "btn lien", texte: "Effacer la clé", onclick: async (e) => {
        await occuper(e.currentTarget, "Effacement…", async () => {
          try {
            etat.config = await api("/api/config", { deepseek_cle: "" });
            annoncer("Clé effacée.");
          } catch (err) { annoncer(err.message); }
        });
        rendre();
      } }));
    return zone;
  }
  const champ = el("input", { id: "cle-deepseek", type: "password", autocomplete: "off",
    spellcheck: "false", classe: "champ", "aria-describedby": "aide-cle" });
  const bouton = el("button", { type: "button", classe: "btn", texte: "Enregistrer la clé" });
  bouton.addEventListener("click", async () => {
    if (!champ.value.trim()) { annoncer("Collez d'abord la clé."); champ.focus(); return; }
    let erreur = null;
    await occuper(bouton, "Enregistrement…", async () => {
      try {
        etat.config = await api("/api/config", { deepseek_cle: champ.value, moteur: "deepseek" });
        annoncer("Clé enregistrée.");
      } catch (err) { erreur = err.message; annoncer(err.message); }
    });
    rendre();
    if (erreur) { const z = document.querySelector(".cle"); if (z) z.appendChild(erreurBloc(erreur)); }
  });
  zone.append(
    el("label", { for: "cle-deepseek", texte: "Clé DeepSeek" }),
    el("p", { id: "aide-cle", classe: "aide",
      texte: "Elle commence par « sk- ». Elle reste sur cet ordinateur et ne s'affiche plus après l'enregistrement." }),
    el("div", { classe: "ligne-champ" }, [champ, bouton]));
  return zone;
}

function vueSondage() {
  const c = etat.config;
  const choix = choixMoteur();
  const champ = el("input", { id: "lien", type: "url", classe: "champ large", required: true,
    value: etat.lien, placeholder: "https://framadate.org/polls/…", autocomplete: "off",
    "aria-describedby": "aide-lien" });
  const erreur = el("div", { id: "erreur-sondage" });
  const options = [
    { valeur: "claude", titre: "Claude",
      detail: c.claude ? "Installé sur cet ordinateur." : "Pas encore installé : utilisez « Changer d'assistant ».", inactif: !c.claude },
    { valeur: "codex", titre: "ChatGPT",
      detail: c.codex ? "Installé sur cet ordinateur." : "Pas encore installé : utilisez « Changer d'assistant ».", inactif: !c.codex },
    { valeur: "deepseek", titre: "DeepSeek", detail: "Service en ligne peu coûteux. Demande une clé." },
    { valeur: "manuel", titre: "Personne (à la main)", detail: "Je lis les commentaires et je saisis les règles moi-même." },
  ];
  const radios = options.map((o) => el("label", { classe: "choix" + (o.inactif ? " inactif" : "") }, [
    el("input", { type: "radio", name: "moteur", value: o.valeur, checked: choix === o.valeur,
      disabled: o.inactif, onchange: () => { etat.moteur = o.valeur; etat.lien = champ.value; rendre(); } }),
    el("span", { classe: "choix-texte" }, [el("strong", { texte: o.titre }), el("span", { texte: o.detail })]),
  ]));
  const bouton = el("button", { type: "submit", classe: "btn primaire", texte: "Lire le sondage" });
  const form = el("form", { classe: "carte", novalidate: true }, [
    el("div", { classe: "groupe" }, [
      el("label", { for: "lien", classe: "etiquette", texte: "Lien du sondage Framadate" }),
      el("p", { id: "aide-lien", classe: "aide", texte: "Copiez l'adresse du sondage depuis votre navigateur ou depuis le mail de Framadate." }),
      champ,
    ]),
    el("fieldset", { classe: "groupe" }, [
      el("legend", { classe: "etiquette", texte: "Qui lit les commentaires des familles ?" }),
      el("p", { classe: "aide", texte: "L'IA propose des règles (absences, rattrapages, préférences). Vous les relisez toujours avant le calcul." }),
      el("div", { classe: "choix-liste" }, radios),
      choix === "deepseek" ? blocCleDeepSeek() : null,
      el("button", { type: "button", classe: "btn", texte: "Changer d'assistant", onclick: () => {
        etat.lien = champ.value;
        ouvrirAccueil();
      } }),
    ]),
    erreur,
    el("div", { classe: "actions" }, [bouton]),
  ]);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    etat.lien = champ.value.trim();
    erreur.replaceChildren();
    if (!etat.lien) { erreur.appendChild(erreurBloc("Collez le lien du sondage.")); champ.focus(); return; }
    const moteur = choixMoteur();
    if (moteur === "deepseek" && !etat.config.deepseek_cle) {
      erreur.appendChild(erreurBloc("Enregistrez d'abord la clé DeepSeek, ou choisissez une autre option."));
      return;
    }
    await occuper(bouton, "Lecture du sondage…", async () => {
      try {
        etat.config = await api("/api/config", { moteur });
        etat.moteur = moteur;
        etat.sondage = await api("/api/sondage", { lien: etat.lien });
        etat.regles = etat.calcul = etat.bilan = null;
        etat.atteinte = 2;
        annoncer("Sondage lu.");
      } catch (err) {
        erreur.appendChild(erreurBloc(err.message));
        annoncer(err.message);
      }
    });
    if (etat.sondage && etat.atteinte === 2 && !erreur.childNodes.length) allerA(2);
  });
  return el("section", { "aria-labelledby": "t1" }, [
    el("h1", { id: "t1", texte: "Préparer le planning du mois" }),
    el("p", { classe: "intro", texte: "Collez le lien du sondage. L'application lit les réponses, vous propose des règles à partir des commentaires, calcule le planning, puis produit le fichier Excel à importer dans le Google Sheet." }),
    form,
  ]);
}

// ---------------------------------------------------------------- étape 2

function chiffre(valeur, libelle) {
  return el("div", { classe: "chiffre" }, [el("span", { classe: "valeur", texte: String(valeur) }), el("span", { texte: libelle })]);
}

function listeCommentaires(commentaires) {
  if (!commentaires.length) return el("p", { classe: "aide", texte: "Aucun commentaire dans le sondage." });
  return el("ul", { classe: "commentaires" }, commentaires.map((c) => el("li", {}, [
    el("p", { classe: "qui" }, [el("strong", { texte: c.auteur }), " ", el("span", { classe: "aide", texte: "le " + dateCourte(c.date) })]),
    el("p", { classe: "texte-comm", texte: c.texte }),
  ])));
}

function vueResume() {
  const r = etat.sondage.resume;
  const moteur = choixMoteur();
  const bouton = el("button", { type: "button", classe: "btn primaire",
    texte: moteur === "manuel" ? "Saisir les règles" : "Lire les commentaires avec " + NOMS_MOTEURS[moteur] });
  const erreur = el("div");
  bouton.addEventListener("click", async () => {
    erreur.replaceChildren();
    const attente = moteur === "manuel" ? "Préparation…"
      : NOMS_MOTEURS[moteur] + " lit les commentaires (souvent moins d'une minute, parfois jusqu'à six)…";
    let ok = false;
    await occuper(bouton, attente, async () => {
      try {
        etat.regles = await api("/api/regles/proposer", { moteur });
        etat.erreurRegles = null;
        etat.calcul = etat.bilan = null;
        etat.atteinte = 3;
        ok = true;
      } catch (err) { erreur.appendChild(erreurBloc(err.message)); annoncer(err.message); }
    });
    if (ok) allerA(3);
  });
  const signaler = [];
  if (r.sans_dispo.length) signaler.push(el("div", { classe: "alerte gris" }, [
    el("h3", { texte: "Familles sans aucune dispo une semaine" }),
    el("p", { texte: "Le calcul rattrape leur perm une autre semaine du mois, sauf si vous indiquez une absence à l'étape suivante." }),
    el("ul", {}, r.sans_dispo.map((x) => el("li", { texte: x.famille + " : " + x.semaine.toLowerCase() }))),
  ]));
  if (r.peu_de_dispos.length) signaler.push(el("div", { classe: "alerte jaune" }, [
    el("h3", { texte: "Familles avec moins de 2 « oui » dans une semaine" }),
    el("p", { texte: "La règle du sondage demande au moins 2 disponibilités par semaine." }),
    el("ul", {}, r.peu_de_dispos.map((x) => el("li", { texte: x.famille + " : " + x.semaine.toLowerCase() + " (" + pluriel(x.oui, "oui", "oui") + ")" }))),
  ]));
  if (r.avertissements.length) signaler.push(el("div", { classe: "alerte orange" }, [
    el("h3", { texte: "Points à vérifier dans le sondage" }),
    el("ul", {}, r.avertissements.map((t) => el("li", { texte: t }))),
  ]));
  return el("section", { "aria-labelledby": "t2" }, [
    el("h1", { id: "t2", texte: r.titre || "Résumé du sondage" }),
    el("p", { classe: "intro", texte: "Vérifiez que c'est le bon sondage et qu'il est clos : des familles peuvent encore répondre tant qu'il est ouvert." }),
    el("div", { classe: "chiffres" }, [
      chiffre(r.familles.length, r.familles.length > 1 ? "familles" : "famille"),
      chiffre(r.nb_creneaux, "demi-journées"),
      chiffre(r.semaines.length, r.semaines.length > 1 ? "semaines" : "semaine"),
      chiffre(r.commentaires.length, r.commentaires.length > 1 ? "commentaires" : "commentaire"),
    ]),
    el("div", { classe: "carte" }, [
      el("h2", { texte: "Semaines" }),
      el("ul", { classe: "semaines" }, r.semaines.map((s) => el("li", {}, [s.titre, el("span", { classe: "aide", texte: " · " + pluriel(s.creneaux, "demi-journée") })]))),
      r.jours_fermes.length ? el("p", {}, [el("strong", { texte: "Jours fermés : " }), r.jours_fermes.join(", ") + "."]) : null,
      el("p", { classe: "aide", texte: "Familles : " + r.familles.join(", ") + "." }),
    ]),
    signaler.length ? el("div", { classe: "pile" }, signaler) : null,
    el("div", { classe: "carte" }, [el("h2", { texte: "Commentaires des familles" }), listeCommentaires(r.commentaires)]),
    erreur,
    el("div", { classe: "actions" }, [
      bouton,
      el("button", { type: "button", classe: "btn", texte: "Changer de sondage", onclick: () => allerA(1) }),
    ]),
  ]);
}

// ---------------------------------------------------------------- étape 3

function selectAvec(id, choix, valeur, etiquette, surChange) {
  const s = el("select", { id, classe: "champ", "aria-label": etiquette });
  for (const o of choix) {
    s.appendChild(el("option", { value: String(o.valeur), texte: o.libelle, selected: String(o.valeur) === String(valeur) }));
  }
  s.addEventListener("change", () => surChange(s.value));
  return s;
}

function commentairesDe(famille) {
  return etat.sondage.resume.commentaires.filter((c) => c.auteur === famille);
}

function detailRegle(r, i) {
  const o = etat.sondage.options;
  const id = "r" + i;
  const n_ = " (règle " + (i + 1) + ")";
  if (r.type === "absence") {
    return selectAvec(id + "-semaine", [{ valeur: "", libelle: "Choisir la semaine" }].concat(o.semaines),
      r.semaine || "", "Semaine d'absence" + n_, (v) => { r.semaine = v; });
  }
  if (r.type === "quota") {
    const champ = el("input", { id: id + "-quota", type: "number", min: "0", max: "20", classe: "champ court",
      value: r.quota === undefined ? "" : r.quota, "aria-label": "Nombre de perms du mois" + n_ });
    champ.addEventListener("input", () => { r.quota = champ.value === "" ? "" : Number(champ.value); });
    return el("div", { classe: "detail-ligne" }, [champ,
      el("span", { classe: "aide", texte: "perms (par défaut : 1 par semaine ouverte, soit " + o.nb_semaines + ")" })]);
  }
  if (r.type === "au_moins") {
    const n = el("input", { id: id + "-n", type: "number", min: "1", max: "10", classe: "champ court",
      value: r.n === undefined ? 1 : r.n, "aria-label": "Nombre minimum de perms" + n_ });
    n.addEventListener("input", () => { r.n = n.value === "" ? "" : Number(n.value); });
    const coches = cochesJours(r, id);
    return el("div", {}, [el("div", { classe: "detail-ligne" }, [n, el("span", { texte: "perm(s) au moins parmi :" })]), coches]);
  }
  if (r.type === "preference") {
    const choix = [{ valeur: "", libelle: "Choisir" }].concat(o.filtres, o.creneaux);
    const cible = selectAvec(id + "-cible", choix, r.cible || "", "Jour ou créneau préféré" + n_, (v) => { r.cible = v; });
    if (r.poids === undefined || r.poids === "") r.poids = 2;
    const poids = POIDS.slice();
    const v = Number(r.poids);
    if (!poids.some((p) => p.valeur === v)) {
      // Valeur venue de l'IA : gardée telle quelle, rangée dans le palier le plus proche.
      const palier = v < 6 ? "léger" : v < 10 ? "moyen" : "important";
      poids.push({ valeur: v, libelle: palier + " (" + v + ")" });
      poids.sort((a, b) => a.valeur - b.valeur);
    }
    const imp = selectAvec(id + "-poids", poids.map((p) => ({ valeur: p.valeur, libelle: "importance : " + p.libelle })),
      r.poids, "Importance de la préférence" + n_, (v) => { r.poids = Number(v); });
    return el("div", { classe: "detail-pile" }, [cible, imp]);
  }
  return el("span", { classe: "aide", texte: "Choisissez d'abord le type de règle." });
}

// Cases à cocher jour x demi-journée. Une journée entière cochée s'écrit « lundi ».
function cochesJours(r, id) {
  const coches = new Set();
  for (const c of r.parmi || []) {
    if (c.includes(":")) coches.add(c);
    else { coches.add(c + ":M"); coches.add(c + ":A"); }
  }
  const jours = etat.sondage.options.filtres.filter((f) => !f.valeur.includes(":")).map((f) => f.valeur);
  const maj = () => {
    const parmi = [];
    for (const j of jours) {
      const m = coches.has(j + ":M"), a = coches.has(j + ":A");
      if (m && a) parmi.push(j); else if (m) parmi.push(j + ":M"); else if (a) parmi.push(j + ":A");
    }
    r.parmi = parmi;
  };
  const grille = el("div", { classe: "coches", role: "group", "aria-label": "Jours possibles (règle " + (Number(id.slice(1)) + 1) + ")" });
  for (const j of jours) {
    const cases = ["M", "A"].map((d) => {
      const cle = j + ":" + d;
      const box = el("input", { type: "checkbox", id: id + "-" + cle.replace(":", "-"), checked: coches.has(cle),
        onchange: (e) => { if (e.target.checked) coches.add(cle); else coches.delete(cle); maj(); } });
      return el("label", { classe: "coche" }, [box, d === "M" ? "matin" : "après-midi"]);
    });
    grille.appendChild(el("div", { classe: "coche-jour" }, [el("span", { classe: "jour", texte: j }), ...cases]));
  }
  return grille;
}

function origineRegle(r) {
  const comms = commentairesDe(r.famille);
  if (comms.length) {
    return el("div", { classe: "origine" }, comms.map((c) => el("p", {}, [
      el("span", { classe: "aide", texte: dateCourte(c.date) + " : " }), c.texte])));
  }
  if (r.source) return el("p", { classe: "origine aide", texte: r.source });
  return el("p", { classe: "origine aide", texte: "Aucun commentaire de cette famille." });
}

function ligneRegle(r, i) {
  const o = etat.sondage.options;
  const n_ = " (règle " + (i + 1) + ")";
  const tr = el("tr", { classe: etat.erreurRegles && etat.erreurRegles.index === i ? "fautive" : null });
  const famille = selectAvec("r" + i + "-famille", [{ valeur: "", libelle: "Choisir" }].concat(o.familles.map((f) => ({ valeur: f, libelle: f }))),
    r.famille || "", "Famille" + n_, (v) => { r.famille = v; rendre(); });
  const type = selectAvec("r" + i + "-type", [{ valeur: "", libelle: "Choisir" }].concat(TYPES), r.type || "",
    "Type de règle" + n_, (v) => { r.type = v; rendre(); });
  tr.append(
    el("td", { "data-col": "Famille" }, famille),
    el("td", { "data-col": "Règle" }, type),
    el("td", { "data-col": "Détail" }, detailRegle(r, i)),
    el("td", { "data-col": "Commentaire d'origine" }, r.famille ? origineRegle(r) : null),
    el("td", {}, el("button", { type: "button", classe: "btn lien danger", texte: "Supprimer",
      "aria-label": "Supprimer la règle " + (i + 1) + (r.famille ? " de " + r.famille : ""),
      onclick: () => { etat.regles.regles.splice(i, 1); etat.erreurRegles = null; rendre(); annoncer("Règle supprimée."); } })),
  );
  return tr;
}

function blocNonTraduits() {
  const liste = etat.regles.non_traduits;
  const items = liste.map((t, i) => {
    const zone = el("textarea", { id: "nt" + i, classe: "champ", rows: "2", "aria-label": "Commentaire à traiter " + (i + 1) });
    zone.value = t;
    zone.addEventListener("input", () => { liste[i] = zone.value; });
    return el("li", { classe: "nt" }, [zone, el("button", { type: "button", classe: "btn lien danger", texte: "Retirer",
      "aria-label": "Retirer le commentaire à traiter " + (i + 1),
      onclick: () => { liste.splice(i, 1); rendre(); } })]);
  });
  return el("div", { classe: "carte" }, [
    el("h2", { texte: "À traiter pendant l'arbitrage" }),
    el("p", { classe: "aide", texte: "Demandes qui ne rentrent dans aucune règle. Elles s'afficheront en alerte jaune sur la page d'arbitrage, pour que vous les régliez à la main." }),
    items.length ? el("ul", { classe: "nt-liste" }, items) : el("p", { classe: "aide", texte: "Aucune pour l'instant." }),
    el("button", { type: "button", classe: "btn", texte: "Ajouter une demande à traiter",
      onclick: () => { liste.push(""); rendre(); const z = $("nt" + (liste.length - 1)); if (z) z.focus(); } }),
  ]);
}

function vueRegles() {
  const R = etat.regles;
  const tous = etat.sondage.resume.commentaires;
  const erreur = etat.erreurRegles ? erreurBloc(etat.erreurRegles.message + (etat.erreurRegles.index !== null && etat.erreurRegles.index !== undefined ? " (ligne " + (etat.erreurRegles.index + 1) + ")" : "")) : null;
  const bouton = el("button", { type: "button", classe: "btn primaire", texte: "Calculer le planning" });
  bouton.addEventListener("click", async () => {
    let ok = false;
    await occuper(bouton, "Calcul du planning…", async () => {
      try {
        etat.calcul = await api("/api/calculer", { regles: R.regles, non_traduits: R.non_traduits, reglages: R.reglages });
        etat.erreurRegles = null;
        etat.bilan = null;
        etat.atteinte = 4;
        ok = true;
      } catch (err) {
        // Le serveur a invalidé l'ancien calcul : les étapes 4 et 5 ne sont plus valables.
        etat.calcul = etat.bilan = null;
        etat.atteinte = 3;
        etat.erreurRegles = { message: err.message, index: err.donnees ? err.donnees.index : null };
        annoncer(err.message);
      }
    });
    if (ok) allerA(4); else rendre();
  });
  const reglages = el("details", { classe: "carte" }, [
    el("summary", { texte: "Réglages avancés" }),
    el("p", { classe: "aide", texte: "Les valeurs habituelles conviennent presque toujours." }),
    el("div", { classe: "reglages" }, [
      champReglage("cible_hebdo", "Perms visées par famille et par semaine", 0),
      champReglage("plafond_hebdo", "Maximum de perms par famille et par semaine", 0),
      champReglage("max_parents_par_creneau", "Maximum de parents par demi-journée", 1),
    ]),
  ]);
  return el("section", { "aria-labelledby": "t3", classe: "moyen" }, [
    el("h1", { id: "t3", texte: "Relire les règles" }),
    el("div", { classe: "alerte " + (R.manuel ? "orange" : "bleu") }, [el("p", { texte: R.message })]),
    el("p", { classe: "intro", texte: "Chaque ligne traduit une demande d'une famille. Corrigez, supprimez ou ajoutez des lignes. Sans règle, une famille fait une perm par semaine ouverte." }),
    erreur,
    el("div", { classe: "carte tableau-zone" }, [
      el("table", { classe: "regles" }, [
        el("caption", { classe: "invisible", texte: "Règles proposées" }),
        el("thead", {}, el("tr", {}, ["Famille", "Règle", "Détail", "Commentaire d'origine", ""].map((t) => el("th", { scope: "col", texte: t })))),
        el("tbody", {}, R.regles.length ? R.regles.map(ligneRegle)
          : el("tr", {}, el("td", { colspan: "5", classe: "vide", texte: "Aucune règle. Le calcul donnera une perm par semaine à chaque famille." }))),
      ]),
      el("button", { type: "button", classe: "btn", texte: "Ajouter une règle", onclick: () => {
        R.regles.push({ famille: "", type: "", source: "" });
        rendre();
        const s = $("r" + (R.regles.length - 1) + "-famille");
        if (s) s.focus();
      } }),
    ]),
    blocNonTraduits(),
    tous.length ? el("details", { classe: "carte" }, [
      el("summary", { texte: "Tous les commentaires du sondage (" + tous.length + ")" }),
      el("p", { classe: "aide", texte: "Vérifiez qu'aucune demande n'a été oubliée dans le tableau ou dans la liste à traiter." }),
      listeCommentaires(tous),
    ]) : null,
    reglages,
    el("div", { classe: "actions" }, [bouton,
      el("button", { type: "button", classe: "btn", texte: "Revenir au résumé", onclick: () => allerA(2) })]),
  ]);
}

function champReglage(cle, libelle, min) {
  const id = "reglage-" + cle;
  const champ = el("input", { id, type: "number", min: String(min), max: "10", classe: "champ court", value: etat.regles.reglages[cle] });
  champ.addEventListener("input", () => { etat.regles.reglages[cle] = champ.value === "" ? "" : Number(champ.value); });
  return el("div", { classe: "reglage" }, [el("label", { for: id, texte: libelle }), champ]);
}

// ---------------------------------------------------------------- étape 4

function groupesAlertes(groupes) {
  if (!groupes.length) return el("p", { classe: "ok-ligne", texte: "Aucune alerte." });
  return el("ul", { classe: "groupes" }, groupes.map((g) => el("li", { classe: "groupe-alerte " + g.gravite }, [
    el("details", {}, [
      el("summary", {}, [el("span", { classe: "badge " + g.gravite, texte: GRAVITES[g.gravite] || g.gravite }), " ",
        g.titre + " (" + g.messages.length + ")"]),
      el("ul", {}, g.messages.map((m) => el("li", { texte: m }))),
    ]),
  ])));
}

function vueArbitrage() {
  const c = etat.calcul;
  const erreur = el("div");
  const cadre = el("iframe", { src: "/arbitrage", title: "Page d'arbitrage du planning", classe: "cadre" });
  const valider = el("button", { type: "button", classe: "btn primaire", texte: "Valider l'arbitrage" });
  valider.addEventListener("click", () => {
    erreur.replaceChildren();
    let doc = null;
    try { doc = cadre.contentDocument; } catch (e) { /* cadre non chargé */ }
    const exporter = doc && (doc.getElementById("btn-export") ||
      Array.from(doc.querySelectorAll("button")).find((b) => /export/i.test(b.textContent)));
    if (!exporter) {
      erreur.appendChild(erreurBloc("La page d'arbitrage n'est pas prête. Attendez qu'elle s'affiche, puis réessayez."));
      return;
    }
    valider.disabled = true;
    valider.textContent = "Enregistrement des choix…";
    annoncer("Enregistrement des choix…");
    exporter.click();
    // Si la page n'a rien transmis, le fichier est parti dans les téléchargements : on le demande.
    clearTimeout(minuteur);
    minuteur = setTimeout(() => {
      if (etat.etape !== 4 || !valider.isConnected) return;
      valider.disabled = false;
      valider.textContent = "Valider l'arbitrage";
      erreur.replaceChildren(repliFichier());
    }, 5000);
  });
  let minuteur = null;
  function repliFichier() {
    const champ = el("input", { type: "file", id: "fichier-arbitrages", accept: ".json,application/json" });
    champ.addEventListener("change", async () => {
      const f = champ.files && champ.files[0];
      if (!f) return;
      try {
        recevoirBilan(await api("/api/arbitrages", { arbitrages: JSON.parse(await f.text()) }));
      } catch (err) {
        erreur.replaceChildren(erreurBloc(err instanceof SyntaxError ? "Ce fichier n'est pas un fichier de choix." : err.message));
      }
    });
    return el("div", { classe: "alerte orange" }, [
      el("p", { texte: "Vos choix ont été téléchargés au lieu d'être transmis. Choisissez le fichier arbitrages.json dans votre dossier Téléchargements." }),
      el("label", { for: "fichier-arbitrages", classe: "etiquette", texte: "Fichier arbitrages.json" }),
      champ,
    ]);
  }
  const garder = el("button", { type: "button", classe: "btn", texte: "Garder le planning calculé" });
  garder.addEventListener("click", () => occuper(garder, "Préparation de l'Excel…", async () => {
    try { recevoirBilan(await api("/api/arbitrages", { arbitrages: null })); }
    catch (err) { erreur.appendChild(erreurBloc(err.message)); }
  }));
  // La page a intercepté l'export : le repli par fichier n'a plus lieu d'être.
  arbitrageRecu = () => { clearTimeout(minuteur); };
  attendreArbitrage = (msg) => {
    clearTimeout(minuteur);
    if (msg.ok) recevoirBilan(msg.reponse);
    else {
      valider.disabled = false;
      valider.textContent = "Valider l'arbitrage";
      erreur.replaceChildren(erreurBloc((msg.reponse && msg.reponse.erreur) || "Les choix n'ont pas pu être enregistrés."));
    }
  };
  return el("section", { "aria-labelledby": "t4", classe: "large" }, [
    el("h1", { id: "t4", texte: "Arbitrer les cas difficiles" }),
    el("div", { classe: "chiffres" }, [
      chiffre(c.a_deux, "demi-journées à 2 parents"),
      chiffre(c.a_un, "à 1 parent"),
      chiffre(c.vides, "sans parent"),
      chiffre(c.a_trois_ou_plus, "à 3 parents ou plus"),
    ]),
    c.hors_quota.length ? el("p", {}, [el("strong", { texte: "Familles hors quota : " }),
      c.hors_quota.map((h) => h.famille + " (" + h.total + " sur " + h.quota + ")").join(", ") + "."]) : null,
    el("p", { classe: "intro", texte: "Dans la page ci-dessous, cliquez sur une case rouge ou orange pour ajouter ou retirer une famille. Vos changements sont gardés sur cet ordinateur. Quand vous avez fini, cliquez sur « Valider l'arbitrage » (ou sur « Exporter mes choix » dans la page : c'est la même chose)." }),
    erreur,
    el("div", { classe: "actions" }, [valider, garder,
      el("button", { type: "button", classe: "btn", texte: "Revenir aux règles", onclick: () => allerA(3) })]),
    cadre,
  ]);
}

let attendreArbitrage = null;
let arbitrageRecu = null;
window.addEventListener("message", (e) => {
  if (e.origin !== location.origin || !e.data) return;
  if (e.data.type === "arbitrage-recu" && arbitrageRecu && etat.etape === 4) arbitrageRecu();
  if (e.data.type === "arbitrage" && attendreArbitrage && etat.etape === 4) attendreArbitrage(e.data);
});

function recevoirBilan(bilan) {
  etat.bilan = bilan;
  etat.atteinte = 5;
  allerA(5);
  annoncer("Le fichier Excel est prêt.");
}

// ---------------------------------------------------------------- étape 5

function vueExcel() {
  const b = etat.bilan;
  const telecharger = el("a", { classe: "btn primaire", href: "/api/excel", download: b.fichier, texte: "Télécharger " + b.fichier });
  const blocD = [];
  if (b.regle_dure_violee) {
    telecharger.setAttribute("aria-disabled", "true");
    telecharger.classList.add("bloque");
    const bloquer = (e) => { if (telecharger.getAttribute("aria-disabled") === "true") e.preventDefault(); };
    telecharger.addEventListener("click", bloquer);
    const coche = el("input", { type: "checkbox", id: "confirme-d", onchange: (e) => {
      if (e.target.checked) { telecharger.removeAttribute("aria-disabled"); telecharger.classList.remove("bloque"); }
      else { telecharger.setAttribute("aria-disabled", "true"); telecharger.classList.add("bloque"); }
    } });
    blocD.push(el("div", { classe: "alerte rouge", role: "alert" }, [
      el("h2", { texte: "Vos choix enfreignent une règle" }),
      el("ul", {}, b.alertes.filter((g) => g.code === "D").flatMap((g) => g.messages).map((m) => el("li", { texte: m }))),
      el("p", { texte: "Vérifiez avec les familles concernées, ou revenez à l'arbitrage pour annuler ce choix." }),
      el("label", { classe: "coche" }, [coche, "Je confirme ces choix : les familles concernées sont d'accord."]),
    ]));
  }
  const ouvrir = el("button", { type: "button", classe: "btn", texte: "Ouvrir le dossier" });
  ouvrir.addEventListener("click", () => occuper(ouvrir, "Ouverture…", async () => {
    try { await api("/api/ouvrir-dossier", {}); annoncer("Dossier ouvert."); } catch (err) { annoncer(err.message); }
  }));
  const autres = b.alertes.filter((g) => g.code !== "D");
  return el("section", { "aria-labelledby": "t5" }, [
    el("h1", { id: "t5", texte: "Le planning est prêt" }),
    el("p", { classe: "intro", texte: b.changements > 1
      ? "Le planning tient compte de vos " + b.changements + " changements d'arbitrage."
      : b.changements === 1 ? "Le planning tient compte de votre changement d'arbitrage."
      : "Le planning est celui du calcul, sans changement." }),
    ...blocD,
    el("div", { classe: "carte" }, [
      el("div", { classe: "actions" }, [telecharger, ouvrir]),
      el("p", { classe: "aide" }, ["Le fichier est aussi enregistré dans ", el("code", { texte: b.dossier }), "."]),
      el("h2", { texte: "Publier dans le Google Sheet" }),
      el("ol", { classe: "etapes-texte" }, [
        el("li", { texte: "Ouvrez le Google Sheet du planning de la crèche." }),
        el("li", { texte: "Menu Fichier, puis Importer, puis l'onglet Importer." }),
        el("li", { texte: "Choisissez le fichier Excel, puis « Insérer de nouvelles feuilles »." }),
      ]),
      el("p", { classe: "aide", texte: "Les colonnes du personnel restent à remplir par la crèche." }),
    ]),
    el("div", { classe: "carte" }, [
      el("h2", { texte: "Perms par famille" }),
      el("table", { classe: "bilan" }, [
        el("thead", {}, el("tr", {}, ["Famille", "Perms", "Quota", ""].map((t) => el("th", { scope: "col", texte: t })))),
        el("tbody", {}, b.familles.map((f) => el("tr", { classe: f.total !== f.quota ? "ecart" : null }, [
          el("th", { scope: "row", texte: f.famille }), el("td", { texte: String(f.total) }), el("td", { texte: String(f.quota) }),
          el("td", { texte: f.total !== f.quota ? "écart" : "" }),
        ]))),
      ]),
    ]),
    el("div", { classe: "carte" }, [
      el("h2", { texte: "Demi-journées à un seul parent" }),
      b.a_un_parent.length ? el("ul", { classe: "colonnes" }, b.a_un_parent.map((t) => el("li", { texte: t })))
        : el("p", { classe: "aide", texte: "Aucune." }),
    ]),
    el("div", { classe: "carte" }, [el("h2", { texte: "Alertes restantes" }), groupesAlertes(autres)]),
    el("div", { classe: "actions" }, [
      el("button", { type: "button", classe: "btn", texte: "Revenir à l'arbitrage", onclick: () => allerA(4) }),
      el("button", { type: "button", classe: "btn", texte: "Préparer un autre mois", onclick: () => {
        Object.assign(etat, { sondage: null, regles: null, calcul: null, bilan: null, lien: "", atteinte: 1 });
        allerA(1);
      } }),
    ]),
  ]);
}

// ---------------------------------------------------------------- premier lancement (V3)

const ASSISTANTS_INFO = {
  claude: { nom: "Claude", exigence: "Demande un abonnement Claude Pro, Max, Team ou Enterprise." },
  codex: { nom: "ChatGPT", exigence: "Demande un abonnement ChatGPT Plus ou supérieur." },
};
const MESSAGE_GRATUIT = "Ce compte Claude est gratuit : il ne permet pas d'utiliser l'assistant ici. "
  + "Il faut un abonnement Pro, Max, Team ou Enterprise. Connectez-vous avec un autre compte, ou choisissez une autre réponse.";

let suiviId = 0;
function arreterSuivi() { suiviId++; }

// Interroge l'état du travail (installation ou connexion) chaque seconde, sans redessiner la page :
// un champ en cours de saisie ne doit pas être effacé. Rend le dernier état, ou null si la page a changé.
async function suivre(assistant, surMaj) {
  const moi = ++suiviId;
  while (moi === suiviId) {
    let rep = null;
    try { rep = await api("/api/assistants?rapide=1"); } catch (e) { /* la bannière de présence prend le relais */ }
    if (moi !== suiviId) return null;
    const travail = rep && rep[assistant] && rep[assistant].travail;
    if (travail) {
      surMaj(travail);
      if (travail.statut !== "en_cours") return travail;
    } else if (rep) return null;
    await new Promise((fin) => setTimeout(fin, 1000));
  }
  return null;
}

function titreAccueil() {
  const titre = document.querySelector("#vue h1");
  if (titre) { titre.setAttribute("tabindex", "-1"); titre.focus(); }
  window.scrollTo(0, 0);
}

function ouvrirAccueil() {
  etat.accueil = { choix: null, phase: "question", statuts: null, erreur: null };
  rendre();
  titreAccueil();
  chargerStatuts();
}

function pret(statuts, nom) {
  const s = statuts && statuts[nom];
  return !!(s && s.installe && s.connecte && s.abonnement_ok !== false);
}

// Détection des assistants déjà prêts : préselectionne le premier, sans écraser un choix déjà fait.
async function chargerStatuts() {
  const A = etat.accueil;
  try { A.statuts = await api("/api/assistants"); } catch (err) { return; }
  if (etat.accueil !== A || A.phase !== "question") return;
  if (!A.choix) A.choix = ["claude", "codex"].find((n) => pret(A.statuts, n)) || null;
  rendre();
}

async function terminerAccueil(choix) {
  try { etat.config = await api("/api/config", { moteur: choix }); }
  catch (err) { etat.accueil.erreur = err.message; rendre(); return; }
  etat.moteur = choix;
  etat.accueil = null;
  annoncer(NOMS_MOTEURS[choix] + " est prêt.");
  allerA(1);
}

// Décide de la suite d'après l'état réel de l'ordinateur : installer, se connecter, ou terminer.
async function orienter(choix) {
  const A = etat.accueil;
  A.choix = choix;
  A.erreur = null;
  try { A.statuts = await api("/api/assistants"); }
  catch (err) { A.erreur = err.message; A.phase = "question"; rendre(); return; }
  const s = A.statuts[choix];
  if (!s.installe) A.phase = "installer";
  else if (!s.connecte) A.phase = "connecter";
  else if (s.abonnement_ok === false) { A.phase = "connecter"; A.erreur = MESSAGE_GRATUIT; }
  else { await terminerAccueil(choix); return; }
  rendre();
  titreAccueil();
}

function vueAccueil() {
  const phases = { question: vueQuestion, deepseek: vueAccueilDeepSeek, installer: vueInstallation, connecter: vueConnexion };
  return phases[etat.accueil.phase]();
}

function vueQuestion() {
  const A = etat.accueil;
  const erreur = el("div", { id: "erreur-accueil" });
  if (A.erreur) erreur.appendChild(erreurBloc(A.erreur));
  const options = [
    { valeur: "claude", titre: "Claude", detail: ASSISTANTS_INFO.claude.exigence },
    { valeur: "codex", titre: "ChatGPT", detail: ASSISTANTS_INFO.codex.exigence },
    { valeur: "deepseek", titre: "Une clé DeepSeek", detail: "Service en ligne peu coûteux. Pas d'abonnement : une clé à coller." },
    { valeur: "manuel", titre: "Rien de tout ça (je saisirai les règles à la main)",
      detail: "Je lis les commentaires des familles et j'écris les règles moi-même." },
  ];
  const radios = options.map((o) => el("label", { classe: "choix" }, [
    el("input", { type: "radio", name: "assistant", value: o.valeur, checked: A.choix === o.valeur,
      onchange: () => { A.choix = o.valeur; erreur.replaceChildren(); } }),
    el("span", { classe: "choix-texte" }, [
      el("strong", { texte: o.titre }),
      el("span", { texte: o.detail }),
      pret(A.statuts, o.valeur) ? el("span", { classe: "ok-ligne", texte: "Déjà prêt sur cet ordinateur" }) : null,
    ]),
  ]));
  const bouton = el("button", { type: "submit", classe: "btn primaire", texte: "Continuer" });
  const form = el("form", { classe: "carte", novalidate: true }, [
    el("fieldset", { classe: "groupe" }, [
      el("legend", { classe: "etiquette", texte: "Vous avez un abonnement Claude, ChatGPT, ou une clé DeepSeek ?" }),
      el("p", { classe: "aide", texte: "Un assistant lit les commentaires des familles et propose des règles. Vous les relisez toujours avant le calcul." }),
      el("div", { classe: "choix-liste" }, radios),
    ]),
    erreur,
    el("div", { classe: "actions" }, [
      bouton,
      etat.config.moteur ? el("button", { type: "button", classe: "btn", texte: "Garder mon choix actuel",
        onclick: () => { etat.accueil = null; rendre(); titreAccueil(); } }) : null,
    ]),
  ]);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    erreur.replaceChildren();
    if (!A.choix) { erreur.appendChild(erreurBloc("Choisissez une réponse pour continuer.")); return; }
    if (A.choix === "manuel") { await terminerAccueil("manuel"); return; }
    if (A.choix === "deepseek") { A.phase = "deepseek"; rendre(); titreAccueil(); return; }
    await occuper(bouton, "Vérification de l'ordinateur…", () => orienter(A.choix));
  });
  return el("section", { "aria-labelledby": "t0" }, [
    el("h1", { id: "t0", texte: "Choisir l'assistant" }),
    el("p", { classe: "intro", texte: "L'outil peut lire les commentaires du sondage à votre place. Il faut pour cela un abonnement payant à Claude ou à ChatGPT, ou une clé DeepSeek. Sans rien de tout cela, vous saisissez les règles vous-même." }),
    form,
  ]);
}

function vueAccueilDeepSeek() {
  const A = etat.accueil;
  const fournie = etat.config.deepseek_cle || etat.config.deepseek_cle_environnement;
  return el("section", { "aria-labelledby": "t0" }, [
    el("h1", { id: "t0", texte: "Utiliser DeepSeek" }),
    el("p", { classe: "intro", texte: "Créez une clé sur le site de DeepSeek, puis collez-la ci-dessous. Elle reste sur cet ordinateur." }),
    el("div", { classe: "carte" }, [blocCleDeepSeek()]),
    el("div", { classe: "actions" }, [
      el("button", { type: "button", classe: "btn primaire", texte: "Continuer", disabled: !fournie,
        onclick: () => terminerAccueil("deepseek") }),
      el("button", { type: "button", classe: "btn", texte: "Retour", onclick: () => { A.phase = "question"; rendre(); titreAccueil(); } }),
    ]),
  ]);
}

function vueInstallation() {
  const A = etat.accueil, info = ASSISTANTS_INFO[A.choix];
  const statut = el("p", { id: "etat-travail", classe: "aide", role: "status" });
  const zoneErreur = el("div");
  const installer = el("button", { type: "button", classe: "btn primaire", texte: "Installer " + info.nom });
  const annuler = el("button", { type: "button", classe: "btn", texte: "Annuler l'installation", hidden: true });
  const retour = el("button", { type: "button", classe: "btn", texte: "Retour",
    onclick: () => { A.phase = "question"; rendre(); titreAccueil(); } });

  function suivreInstallation() {
    installer.disabled = true;
    annuler.hidden = false;
    suivre(A.choix, (t) => {
      statut.textContent = "Installation de " + info.nom + " en cours, quelques minutes (" + t.secondes + " s)…";
    }).then(async (t) => {
      if (!t) return;
      annuler.hidden = true;
      if (t.statut === "termine") { statut.textContent = "Installation terminée."; await orienter(A.choix); return; }
      statut.textContent = "";
      installer.disabled = false;
      installer.textContent = "Réessayer";
      zoneErreur.replaceChildren(erreurBloc(t.statut === "annule" ? "Installation annulée."
        : (t.message || "L'installation n'a pas abouti. Réessayez.")));
    });
  }
  installer.addEventListener("click", async () => {
    zoneErreur.replaceChildren();
    try { await api("/api/assistants/installer", { assistant: A.choix }); }
    catch (err) { zoneErreur.appendChild(erreurBloc(err.message)); return; }
    statut.textContent = "Installation de " + info.nom + " en cours, quelques minutes…";
    suivreInstallation();
  });
  annuler.addEventListener("click", async () => {
    try { await api("/api/assistants/annuler", { assistant: A.choix }); } catch (err) { annoncer(err.message); }
  });
  // Une installation déjà lancée (retour sur cet écran) reprend son suivi.
  const deja = A.statuts && A.statuts[A.choix] && A.statuts[A.choix].travail;
  if (deja && deja.type === "installation" && deja.statut === "en_cours") setTimeout(suivreInstallation, 0);
  return el("section", { "aria-labelledby": "t0" }, [
    el("h1", { id: "t0", texte: "Installer " + info.nom }),
    el("p", { classe: "intro", texte: info.nom + " n'est pas encore installé sur cet ordinateur. L'installation prend quelques minutes et ne demande pas de droits d'administrateur." }),
    el("p", { classe: "aide", texte: "Rappel : " + info.exigence.charAt(0).toLowerCase() + info.exigence.slice(1) }),
    el("div", { classe: "carte" }, [statut, zoneErreur]),
    el("div", { classe: "actions" }, [installer, annuler, retour]),
  ]);
}

function vueConnexion() {
  const A = etat.accueil, info = ASSISTANTS_INFO[A.choix], chatgpt = A.choix === "codex";
  const statut = el("p", { id: "etat-travail", classe: "aide", role: "status" });
  const zoneLien = el("div", { id: "zone-lien" });
  const zoneCode = el("div", { classe: "cle", hidden: true });
  const zoneErreur = el("div");
  if (A.erreur) zoneErreur.appendChild(erreurBloc(A.erreur));
  const gratuit = A.erreur === MESSAGE_GRATUIT;
  const ouvrir = el("button", { type: "button", classe: "btn primaire",
    texte: gratuit ? "Se connecter avec un autre compte" : "Ouvrir la page de connexion" });
  const autre = chatgpt ? el("button", { type: "button", classe: "btn", texte: "Autre méthode : code à usage unique" }) : null;
  const annuler = el("button", { type: "button", classe: "btn", texte: "Annuler la connexion", hidden: true });
  const retour = el("button", { type: "button", classe: "btn", texte: "Retour",
    onclick: () => { A.phase = "question"; A.erreur = null; rendre(); titreAccueil(); } });
  const champ = el("input", { id: "code-connexion", type: "text", autocomplete: "off", spellcheck: "false",
    classe: "champ", "aria-describedby": "aide-code" });
  const envoyer = el("button", { type: "button", classe: "btn", texte: "Envoyer le code" });
  zoneCode.append(
    el("label", { for: "code-connexion", texte: "Si la page affiche un code, collez-le ici" }),
    el("p", { id: "aide-code", classe: "aide", texte: "La plupart du temps, aucun code n'est demandé : la connexion se termine toute seule." }),
    el("div", { classe: "ligne-champ" }, [champ, envoyer]));

  // Redessine le lien et le code à partir de l'état du travail. Le texte vient d'un programme : textContent seulement,
  // et le serveur ne renvoie que des liens https vers les sites de l'éditeur.
  function afficher(t) {
    const enAttente = t.statut === "en_cours";
    statut.textContent = enAttente
      ? (t.methode === "code" ? "En attente de votre autorisation sur le site de ChatGPT…"
        : "En attente de votre connexion dans le navigateur…")
      : "";
    const lien = typeof t.lien === "string" && t.lien.startsWith("https://") && !t.lien.includes("\\") ? t.lien : null;
    const morceaux = [];
    if (lien && enAttente) {
      morceaux.push(el("p", {}, [
        t.methode === "code" ? "1. Ouvrez ce lien : " : "Si la page ne s'est pas ouverte toute seule, ouvrez ce lien : ",
        el("a", { href: lien, target: "_blank", rel: "noopener noreferrer", texte: "page de connexion de " + info.nom })]));
    }
    if (t.methode === "code" && t.code && enAttente) {
      morceaux.push(el("p", {}, ["2. Saisissez ce code à usage unique : ", el("strong", { classe: "code-appareil", texte: t.code })]));
    }
    zoneLien.replaceChildren(...morceaux);
  }

  function suivreConnexion(methode) {
    ouvrir.disabled = true;
    if (autre) autre.disabled = true;
    annuler.hidden = false;
    zoneCode.hidden = methode === "code" || chatgpt;  // `codex login` ne lit rien sur son entrée
    suivre(A.choix, afficher).then(async (t) => {
      if (!t) return;
      annuler.hidden = true;
      if (t.statut === "termine") { statut.textContent = "Connexion réussie."; await orienter(A.choix); return; }
      zoneCode.hidden = true;
      ouvrir.disabled = false;
      ouvrir.textContent = "Réessayer";
      if (autre) autre.disabled = false;
      zoneErreur.replaceChildren(erreurBloc(t.statut === "annule" ? "Connexion annulée." : (t.message || "La connexion n'a pas abouti. Réessayez.")));
      annoncer("La connexion n'a pas abouti.");
    });
  }
  async function connecter(methode) {
    zoneErreur.replaceChildren();
    A.erreur = null;
    try { await api("/api/assistants/connecter", { assistant: A.choix, methode }); }
    catch (err) { zoneErreur.appendChild(erreurBloc(err.message)); return; }
    statut.textContent = "Ouverture de la page de connexion…";
    suivreConnexion(methode);
  }
  ouvrir.addEventListener("click", () => connecter("navigateur"));
  if (autre) autre.addEventListener("click", () => connecter("code"));
  annuler.addEventListener("click", async () => {
    try { await api("/api/assistants/annuler", { assistant: A.choix }); } catch (err) { annoncer(err.message); }
  });
  envoyer.addEventListener("click", async () => {
    const code = champ.value.trim();
    if (!code) { annoncer("Collez d'abord le code."); champ.focus(); return; }
    envoyer.disabled = true;
    try {
      await api("/api/assistants/code", { assistant: A.choix, code });
      champ.value = "";
      statut.textContent = "Code envoyé, vérification en cours…";
      annoncer("Code envoyé.");
    } catch (err) { zoneErreur.replaceChildren(erreurBloc(err.message)); }
    envoyer.disabled = false;
  });
  const deja = A.statuts && A.statuts[A.choix] && A.statuts[A.choix].travail;
  if (deja && deja.type === "connexion" && deja.statut === "en_cours") setTimeout(() => suivreConnexion(deja.methode), 0);
  return el("section", { "aria-labelledby": "t0" }, [
    el("h1", { id: "t0", texte: "Se connecter à " + info.nom }),
    el("p", { classe: "intro", texte: "Une page de connexion va s'ouvrir dans votre navigateur. Connectez-vous avec votre compte " + info.nom + ", puis revenez sur cette page : elle continue toute seule." }),
    el("p", { classe: "aide", texte: "Rappel : " + info.exigence.charAt(0).toLowerCase() + info.exigence.slice(1) }),
    el("div", { classe: "carte" }, [
      statut, zoneLien, zoneCode, zoneErreur,
      chatgpt ? el("p", { classe: "aide", texte: "Autre méthode, si la page ne s'ouvre pas : un code à usage unique. Elle doit d'abord être autorisée dans les réglages de sécurité de votre compte ChatGPT." }) : null,
    ]),
    el("div", { classe: "actions" }, [ouvrir, autre, annuler, retour]),
  ]);
}

// ---------------------------------------------------------------- arrêt et présence (V3-4)

const PRESENCE_MS = 60000;
const INACTIF_MAX_MS = 2 * 60 * 60 * 1000;
let derniereAction = Date.now();
let minuteurPresence = null;

function signalerPresence() {
  if (etat.ferme) return;
  if (Date.now() - derniereAction > INACTIF_MAX_MS) { clearInterval(minuteurPresence); minuteurPresence = null; return; }
  const banniere = $("banniere-arret");
  api("/api/presence", {}).then(() => { banniere.hidden = true; }).catch(() => {
    banniere.textContent = "L'outil s'est arrêté. Relancez-le comme d'habitude (icône « Planning des perms » sur le bureau, ou lancer.bat).";
    banniere.hidden = false;
  });
}

function demarrerPresence() {
  if (minuteurPresence === null) minuteurPresence = setInterval(signalerPresence, PRESENCE_MS);
}

function noterAction() {
  derniereAction = Date.now();
  if (!etat.ferme) demarrerPresence();
}

function montrerFerme() {
  etat.ferme = true;
  etat.accueil = null;
  arreterSuivi();
  clearInterval(minuteurPresence);
  minuteurPresence = null;
  for (const n of [$("fermer"), $("mois"), $("banniere-arret"), document.querySelector("header nav")]) n.hidden = true;
  $("vue").replaceChildren(el("section", { "aria-labelledby": "t-ferme" }, [
    el("h1", { id: "t-ferme", texte: "L'outil est fermé" }),
    el("p", { classe: "intro", texte: "Vos fichiers du mois sont gardés sur cet ordinateur. Vous pouvez fermer cet onglet." }),
    el("p", { texte: "Pour rouvrir l'outil, cliquez sur l'icône « Planning des perms » sur le bureau." }),
  ]));
  annoncer("L'outil est fermé.");
  titreAccueil();
}

async function fermerOutil() {
  try { await api("/api/arreter", {}); } catch (err) { /* déjà arrêté : le résultat est le même */ }
  montrerFerme();
}

// ---------------------------------------------------------------- démarrage

for (const b of document.querySelectorAll("#etapes button")) {
  b.addEventListener("click", () => { if (!b.disabled) allerA(Number(b.dataset.etape)); });
}

$("fermer").addEventListener("click", fermerOutil);
for (const evenement of ["click", "keydown"]) document.addEventListener(evenement, noterAction, true);
demarrerPresence();

// L'écran de premier lancement remplace l'étape 1 tant qu'aucun assistant n'est choisi.
function demarrer(config) {
  etat.config = config;
  if (!config.moteur) etat.accueil = { choix: null, phase: "question", statuts: null, erreur: null };
  rendre();
  if (etat.accueil) chargerStatuts();
}
api("/api/etat").then(demarrer).catch((err) => { rendre(); annoncer(err.message); });
})();
