#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 3 de l'épisode du jour : voix, flux de podcast, mémoire.

Lit ce que l'agent a préparé dans `travail/` :
  - selection.json : {"rappel": false, "items": [{"uid", "score", "raison"}, …]}
  - script.txt     : le texte parlé de l'épisode

puis :
  1. fait lire le script par Piper (voix libre, hors ligne) → MP3 ;
  2. range l'épisode dans docs/episodes/ et l'inscrit dans docs/episodes.json ;
  3. régénère docs/feed.xml (le flux auquel Apple Podcasts est abonné) et docs/index.html ;
  4. marque TOUS les candidats du jour comme vus (retenus ou non) ;
  5. supprime les épisodes plus vieux que `garder_jours`.

    python3 episode.py
"""
import io, json, re, sys, wave
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE / "podcast.json"
TRAVAIL = HERE / "travail"
DOCS = HERE / "docs"
EPISODES = DOCS / "episodes"
HISTO = DOCS / "episodes.json"
VUS = HERE / "etat" / "vus.json"
DERNIER = HERE / "etat" / "dernier.json"
TAHITI = timezone(timedelta(hours=-10))     # pas d'heure d'été à Tahiti
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def lire(p, defaut):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else defaut
    except Exception:
        return defaut


def ecrire(p, data):
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def nettoyer_oral(t):
    """Filet de sécurité si le script contient du Markdown ou des URL."""
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_#`>]+", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def synthese_mp3(texte, voix):
    """Piper → WAV en mémoire → MP3 64 kbit/s mono (lameenc, sans ffmpeg)."""
    from piper import PiperVoice
    import lameenc
    v = PiperVoice.load(str(HERE / "voix" / f"{voix}.onnx"))
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        v.synthesize_wav(texte, w)
    tampon.seek(0)
    with wave.open(tampon) as w:
        pcm, freq = w.readframes(w.getnframes()), w.getframerate()
    enc = lameenc.Encoder()
    enc.set_bit_rate(64); enc.set_in_sample_rate(freq); enc.set_channels(1); enc.set_quality(2)
    return enc.encode(pcm) + enc.flush(), len(pcm) / 2 / freq


def duree_hms(s):
    s = int(round(s))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def notes_episode(ep):
    """Notes d'épisode affichées dans l'app Podcasts : la liste des articles."""
    lignes = [f"<p>{escape(ep['description'])}</p>", "<ul>"]
    for it in ep["items"]:
        lien = f'<a href="{escape(it["url"])}">{escape(it["titre"])}</a>' if it.get("url") else escape(it["titre"])
        lignes.append(f"<li>{lien} — {escape(it.get('source', ''))}"
                      + (f"<br>{escape(it['raison'])}" if it.get("raison") else "") + "</li>")
    lignes.append("</ul>")
    return "".join(lignes)


def ecrire_flux(conf, histo):
    base = conf["base_url"].rstrip("/")
    items = []
    for ep in histo:
        items.append(f"""    <item>
      <title>{escape(ep['titre'])}</title>
      <description><![CDATA[{notes_episode(ep)}]]></description>
      <pubDate>{ep['pubdate']}</pubDate>
      <guid isPermaLink="false">{escape(ep['fichier'])}</guid>
      <enclosure url="{base}/episodes/{escape(ep['fichier'])}" length="{ep['taille']}" type="audio/mpeg"/>
      <itunes:duration>{ep['duree']}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
    </item>""")
    flux = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(conf['titre'])}</title>
    <link>{base}/</link>
    <atom:link href="{base}/feed.xml" rel="self" type="application/rss+xml"/>
    <language>fr</language>
    <description>{escape(conf['description'])}</description>
    <itunes:author>{escape(conf['auteur'])}</itunes:author>
    <itunes:image href="{base}/couverture.jpg"/>
    <itunes:category text="Education"/>
    <itunes:explicit>false</itunes:explicit>
    <itunes:block>Yes</itunes:block>
{chr(10).join(items)}
  </channel>
</rss>
"""
    (DOCS / "feed.xml").write_text(flux, encoding="utf-8")


def ecrire_index(conf, histo):
    base = conf["base_url"].rstrip("/")
    lignes = "".join(
        f'<li><a href="episodes/{escape(ep["fichier"])}">{escape(ep["titre"])}</a> '
        f'<span>{ep["duree"][3:]}</span></li>' for ep in histo)
    (DOCS / "index.html").write_text(f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{escape(conf['titre'])}</title>
<style>
:root{{--fond:#f6f5f2;--texte:#1c1c1c;--doux:#5d6470;--accent:#1b3a5c}}
@media (prefers-color-scheme:dark){{:root{{--fond:#14171c;--texte:#e9e7e2;--doux:#9aa3b0;--accent:#8fb8dd}}}}
body{{margin:0;padding:24px 16px;background:var(--fond);color:var(--texte);font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:640px;margin:auto}}
a{{color:var(--accent)}} li{{margin:6px 0}} span{{color:var(--doux);font-size:13px}}
code{{word-break:break-all}}
</style></head><body>
<h1>{escape(conf['titre'])}</h1>
<p>{escape(conf['description'])}</p>
<p>S’abonner dans Apple Podcasts : onglet Bibliothèque → « … » → « Suivre un podcast par URL », puis coller :<br><code>{base}/feed.xml</code></p>
<ul>{lignes}</ul>
</body></html>
""", encoding="utf-8")


def main():
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    selection = lire(TRAVAIL / "selection.json", None)
    script_p = TRAVAIL / "script.txt"
    if selection is None or not script_p.exists():
        sys.exit("travail/selection.json ou travail/script.txt manquant.")
    script = nettoyer_oral(script_p.read_text(encoding="utf-8"))
    if len(script) < 200:
        sys.exit("Script vide ou trop court.")
    candidats = {i["uid"]: i for i in lire(TRAVAIL / "candidats.json", {}).get("items", [])}
    histo = lire(HISTO, [])

    now = datetime.now(TAHITI)
    jour = now.date().isoformat()
    nom = f"veille-{jour}.mp3"
    k = 2
    while (EPISODES / nom).exists():
        nom = f"veille-{jour}-{k}.mp3"; k += 1

    # Les items d'un épisode de rappel viennent de l'historique, pas des candidats.
    connus = dict(candidats)
    for ep in histo:
        for it in ep["items"]:
            connus.setdefault(it.get("uid", ""), it)
    items = []
    for s in selection.get("items", []):
        c = connus.get(s.get("uid"), {})
        items.append({"uid": s.get("uid", ""), "titre": c.get("titre", s.get("titre", "")),
                      "url": c.get("url", ""), "source": c.get("source", ""),
                      "score": s.get("score"), "raison": s.get("raison", c.get("raison", ""))})

    mp3, secondes = synthese_mp3(script, conf.get("voix", "fr_FR-siwis-medium"))
    EPISODES.mkdir(parents=True, exist_ok=True)
    (EPISODES / nom).write_bytes(mp3)

    rappel = bool(selection.get("rappel"))
    date_orale = f"{now.day} {MOIS[now.month - 1]}"
    histo.insert(0, {
        "fichier": nom, "date": jour, "pubdate": format_datetime(now),
        "titre": f"Veille du {date_orale}" + (" — rappel" if rappel else ""),
        "description": (f"Rappel : {len(items)} article(s) déjà présentés." if rappel
                        else f"{len(items)} article(s) retenu(s) pour la classe."),
        "duree": duree_hms(secondes), "taille": len(mp3), "items": items,
    })

    # Purge des vieux épisodes (fichier + entrée du flux).
    limite = (now - timedelta(days=int(conf.get("garder_jours", 14)))).date().isoformat()
    garde = []
    for ep in histo:
        if ep["date"] < limite:
            (EPISODES / ep["fichier"]).unlink(missing_ok=True)
        else:
            garde.append(ep)
    ecrire(HISTO, garde)
    ecrire_flux(conf, garde)
    ecrire_index(conf, garde)

    # Mémoire : tout le lot du jour est « vu », retenu ou non (jamais reproposé).
    vus = lire(VUS, {})
    for u in candidats:
        vus[u] = jour
    ecrire(VUS, vus)
    ecrire(DERNIER, {"lancement": datetime.now(timezone.utc).isoformat()})

    print(f"✓ {nom} — {duree_hms(secondes)}, {len(mp3) // 1024} Ko, {len(items)} article(s)"
          + (" (rappel)" if rappel else ""))


if __name__ == "__main__":
    main()
