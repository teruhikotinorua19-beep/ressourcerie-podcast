#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 1 de l'épisode du jour : collecte des nouveautés.

Interroge les sources de `veille_sources.json` (mêmes collecteurs que la
Ressourcerie du Mac, importés de `veille.py`), écarte ce qui a déjà été vu
(`etat/vus.json`) et écrit les candidats dans `travail/candidats.json`.
Ne note RIEN : la notation est faite par l'agent de la routine (voir
CONSIGNES.md), pas par un appel `claude -p`.

Lancé chaque matin par GitHub Actions (.github/workflows/collecter.yml) : le
réseau de l'environnement cloud de Claude bloque les sites des sources, celui
de GitHub non. Le fichier produit est committé pour que la routine le lise.

    python3 collecte.py
"""
import json, sys
from datetime import timedelta
from pathlib import Path

import veille as V

HERE = Path(__file__).resolve().parent
VUS = HERE / "etat" / "vus.json"
DERNIER = HERE / "etat" / "dernier.json"
CANDIDATS = HERE / "travail" / "candidats.json"
MAX_CANDIDATS = 120        # même plafond que la notation sur le Mac


def main():
    conf = V.charger(V.CONF, None)
    if not conf:
        sys.exit("veille_sources.json introuvable ou illisible.")
    profil = conf.get("profil", {})
    vus = V.charger(VUS, {})
    dernier = V.charger(DERNIER, {})

    depuis = V.date_iso(dernier.get("lancement", "")) or (
        V.maintenant() - timedelta(days=int(profil.get("fenetre_defaut_jours", 30))))
    journal = [f"Fenêtre : depuis le {depuis.date().isoformat()}"]
    bruts = V.collecter(conf, depuis, journal)
    if not bruts and CANDIDATS.exists():
        # Aucune source joignable (réseau bloqué) : on garde la dernière collecte.
        print("\n".join(journal))
        sys.exit("Aucune source n'a répondu : travail/candidats.json est conservé tel quel.")

    candidats, ce_lot = [], set()
    for it in bruts:
        u = V.uid_de(it["url"], it["titre"])
        if u in vus or u in ce_lot:
            continue
        ce_lot.add(u)
        candidats.append({"uid": u, "titre": it["titre"], "source": it["source_nom"],
                          "date": it.get("date", ""), "auteurs": it.get("auteurs", ""),
                          "url": it.get("url", ""), "resume": it.get("resume", "")})
    candidats.sort(key=lambda i: i["date"] or "", reverse=True)
    candidats = candidats[:MAX_CANDIDATS]

    CANDIDATS.parent.mkdir(exist_ok=True)
    V.ecrire_json(CANDIDATS, {
        "genere": V.maintenant().isoformat(timespec="minutes"),
        "profil": {k: profil.get(k) for k in ("missions", "criteres", "score_minimum", "max_retenus")},
        "items": candidats,
    }, indent=1)
    journal.append(f"{len(bruts)} collecté(s) → {len(candidats)} candidat(s) jamais vu(s)")
    print("\n".join(journal))
    print(f"→ {CANDIDATS.relative_to(HERE)}")


if __name__ == "__main__":
    main()
