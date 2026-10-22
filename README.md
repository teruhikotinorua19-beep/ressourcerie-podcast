# Podcast de veille HG-EMC — Ressourcerie

Chaque matin (heure de Tahiti) :

1. 5 h 20 — GitHub Actions collecte les nouveautés (`collecte.py`, `.github/workflows/collecter.yml`) et committe `travail/candidats.json` (le réseau du cloud Claude bloque les sources) ;
2. 6 h 05 — une routine Claude note et choisit les articles, écrit le script (voir `CONSIGNES.md`) ;
3. Piper lit le script, voix française libre (`episode.py`) ;
4. l'épisode et le flux `docs/feed.xml` partent sur GitHub Pages (`.github/workflows/publier.yml`).

L'app Claude GitHub doit avoir accès à ce dépôt (sinon push refusé en 403).

S'abonner : Apple Podcasts → Bibliothèque → « … » → « Suivre un podcast par URL » → `<base_url>/feed.xml` (voir `podcast.json`).

- Réglages : `podcast.json` (adresse, titre, voix, durée de conservation).
- Profil et sources : `veille_sources.json` (même format que sur le Mac).
- Mémoire : `etat/vus.json` (articles déjà vus), `etat/dernier.json` (dernier passage).
- Le flux est public mais non répertorié (non soumis à l’annuaire Apple, `noindex`). Contenu : résumés d'articles publics, aucune donnée personnelle.

Test local : `python3 collecte.py`, écrire `travail/selection.json` et `travail/script.txt` à la main, puis `python3 episode.py`.
