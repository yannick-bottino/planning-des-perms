// Page d'attente ouverte depuis un fichier local (file://), jamais servie par l'outil.
// Adresse : demarrage.html#<port>, avec en essai « &delai=<secondes> » pour raccourcir l'attente.
(function () {
"use strict";

const [brut, ...autres] = location.hash.slice(1).split("&");
const options = Object.fromEntries(autres.map((x) => x.split("=")));
const port = /^\d{1,5}$/.test(brut) && Number(brut) > 0 && Number(brut) < 65536 ? Number(brut) : 0;
const delai = Number(options.delai) > 0 ? Number(options.delai) * 1000 : 120000;
const debut = Date.now();

function perdu() {
  document.getElementById("etat").hidden = true;
  document.getElementById("echec").hidden = false;
}

// Une réponse opaque (no-cors) suffit : elle prouve que l'outil écoute sur ce port.
function essayer() {
  if (!port || Date.now() - debut > delai) { perdu(); return; }
  fetch("http://127.0.0.1:" + port + "/api/etat", { mode: "no-cors", cache: "no-store" })
    .then(() => location.replace("http://127.0.0.1:" + port + "/"))
    .catch(() => setTimeout(essayer, 500));
}
essayer();
})();
