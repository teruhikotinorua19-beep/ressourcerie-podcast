# Podcast de veille HG-EMC — Ressourcerie

Chaque matin vers 6 h (heure de Tahiti), une routine Claude dans le cloud :

1. collecte les nouveautés des sources (`collecte.py`, collecteurs repris de la Ressourcerie du Mac) ;
2. note et choisit les articles, écrit le script (voir `CONSIGNES.md`) ;
3. fait lire le script par Piper, voix française libre (`episode.py`) ;
4. publie l'épisode et le flux `docs/feed.xml` sur GitHub Pages (`.github/workflows/publier.yml`).

S'abonner : Apple Podcasts → Bibliothèque → « … » → « Suivre un podcast par URL » → `<base_url>/feed.xml` (voir `podcast.json`).

- Réglages : `podcast.json` (adresse, titre, voix, durée de conservation).
- Profil et sources : `veille_sources.json` (même format que sur le Mac).
- Mémoire : `etat/vus.json` (articles déjà vus), `etat/dernier.json` (dernier passage).
- Le flux est public mais non répertorié (`itunes:block`, `noindex`). Contenu : résumés d'articles publics, aucune donnée personnelle.

Test local : `python3 collecte.py`, écrire `travail/selection.json` et `travail/script.txt` à la main, puis `python3 episode.py`.
