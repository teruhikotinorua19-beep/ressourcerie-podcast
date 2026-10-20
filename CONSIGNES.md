# Consignes de la routine — épisode du jour

Tu fabriques l'épisode quotidien du podcast de veille d'un professeur d'histoire-géographie-EMC en Polynésie française. Il l'écoute vers 6 h 40, heure de Tahiti. Suis les étapes dans l'ordre. Ne modifie ni le code, ni `veille_sources.json`, ni `podcast.json`, ni `voix/`.

## 1. Installer et lire les candidats

```bash
pip install -q -r requirements.txt
```

La collecte n'est PAS faite par toi : le réseau de ton environnement bloque les sites des sources. GitHub Actions l'a faite vers 5 h 20 (heure de Tahiti) et a committé `travail/candidats.json` : le champ `genere` (date UTC), le profil (`missions`, `criteres`, `score_minimum`, `max_retenus`) et les nouveautés jamais vues (`uid`, `titre`, `source`, `date`, `auteurs`, `url`, `resume`).

Vérifie `genere` : s'il date de plus de 20 heures (la collecte du jour a échoué), considère qu'il n'y a aucun candidat et passe directement à l'épisode de rappel décrit plus bas. Ignore aussi tout candidat dont l'`uid` figure déjà dans `etat/vus.json`. N'essaie pas de lancer `collecte.py` toi-même.

## 2. Noter et choisir (c'est toi qui le fais)

Lis `travail/candidats.json`. Note chaque candidat de 0 à 100 au regard de `missions` et `criteres`.

- Sois sévère et franc : mieux vaut 4 articles justes que 15 tièdes. Écarte sans hésiter ce que les critères excluent.
- Retiens ceux dont la note atteint `score_minimum`, au plus 8, du plus utile au moins utile.
- Pour chacun, rédige une **raison** : une phrase courte et concrète qui dit en quoi il sert (niveau, chapitre, usage en classe). Pas de paraphrase du titre.

Écris `travail/selection.json` :

```json
{"rappel": false, "items": [{"uid": "…", "score": 82, "raison": "…"}]}
```

**S'il n'y a aucun article retenu** (ou aucun candidat), l'épisode existe quand même : c'est un **rappel**. Prends dans `docs/episodes.json` les 3 ou 4 meilleurs articles des 7 derniers jours (champs `uid`, `score`, `raison` de chaque item) et écris-les dans `selection.json` avec `"rappel": true`. Si l'historique est vide aussi, fais un épisode très court qui dit simplement qu'il n'y a rien de neuf aujourd'hui, avec `"items": []` et `"rappel": true`.

## 3. Écrire le script

Écris `travail/script.txt` : le texte parlé, lu tel quel par une voix de synthèse.

- 500 à 750 mots (250 à 400 pour un rappel, annoncé comme tel).
- Ouverture d'une ou deux phrases : « Veille du 21 octobre », le nombre d'articles, le fil conducteur s'il y en a un.
- Puis chaque article, du plus utile au moins utile : de quoi il parle, pour quel niveau et quel chapitre il sert, ce qu'on peut en tirer en classe. Varie les transitions, ne fais pas une liste.
- Clôture d'une phrase, sans formule de politesse.
- Le professeur est tutoyé.

Contraintes orales strictes :

- texte brut uniquement : pas de Markdown, pas de titre, pas de puce, pas d'emoji, pas d'URL ;
- écris en toutes lettres ce qui se lit mal : « sixième », « seconde », « première », « vingtième siècle », « pour cent », les dates (« mille neuf cent quatre-vingt-treize ») ; les sigles courants peuvent rester (EMC, IA, ONU) ;
- un titre en langue étrangère : donne son sens en français ;
- phrases courtes, ton direct et vivant, sans flagornerie ni formule creuse ;
- n'invente rien au-delà des titres et résumés fournis.

## 4. Fabriquer et publier

```bash
python3 episode.py
git add docs etat
git commit -m "Épisode du $(TZ=Pacific/Tahiti date +%Y-%m-%d)"
git push origin HEAD:main || git push origin HEAD
```

`episode.py` fait la voix (Piper), le MP3, le flux `docs/feed.xml`, la page `docs/index.html`, met à jour la mémoire `etat/` et purge les vieux épisodes. Ne committe jamais `travail/`. La publication en ligne se fait ensuite toute seule (GitHub Actions).

## En cas de problème

Une collecte vide ou périmée n'est PAS un échec : c'est un épisode de rappel. Si une autre étape échoue (installation de Piper, `episode.py`, push refusé), ne contourne pas en modifiant le code. Termine en expliquant précisément ce qui a échoué, avec le message d'erreur.
