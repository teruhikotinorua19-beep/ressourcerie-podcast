#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Veille documentaire — Ressourcerie.

Va chercher les nouveautés de la recherche et de l'actualité éducative sur les
sources déclarées dans `veille_sources.json`, écarte ce qui a déjà été vu, fait
NOTER le reste par Claude au regard des missions de Greg (un seul appel, patron
de `chercher_sens.py`), et range les items retenus dans `veille.json`.

DEUX RÉSERVOIRS, JAMAIS MÉLANGÉS (décision du 2026-08-04) :
  - `veille.json`    = le FIL. Périssable, horodaté, purgé tout seul. Ce script
                       n'écrit que là.
  - `catalogue.json` = le FOND (53 réfs triées main). Ce script n'y touche
                       JAMAIS. Une brève n'entre au fond que si Greg la
                       « verse » explicitement, via `ajouter_pdf.py`.

Usage :
    python3.13 veille.py                  # depuis le dernier lancement
    python3.13 veille.py --jours 60       # fenêtre forcée
    python3.13 veille.py --sans-ia        # collecte seule, aucune notation
    python3.13 veille.py --blanc          # tout faire SANS rien écrire (essai)
    python3.13 veille.py --sans-memoire   # écrit le fil MAIS n'inscrit rien
                                          # dans la mémoire des vus : les items
                                          # écartés repasseront devant une
                                          # version améliorée du tri. À utiliser
                                          # tant que le prompt de notation n'est
                                          # pas réglé.
    python3.13 veille.py --json           # sortie machine (pour router.php)

Ajouter une source sans éditer le JSON à la main — colle l'URL de N'IMPORTE
quelle page du site, le script y cherche le flux, le teste et l'inscrit :
    python3.13 veille.py --ajouter-source "https://exemple.fr/un/article" --nom "Exemple"

Zéro dépendance : stdlib seule (urllib + xml.etree), comme le reste de l'outil.
RGPD : sources publiques uniquement ; seuls des titres et résumés publics
partent chez Claude pour la notation. Aucune donnée nominative.
"""
import sys, os, re, json, html, time, hashlib, shutil, subprocess, tempfile
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE / "veille_sources.json"
FIL = HERE / "veille.json"
VUS = HERE / "veille_vus.json"
PDFS = HERE / "PDFs"          # les statuts d'avancement y vivent (comme l'ajout)

UA = "Ressourcerie-veille/1.0 (veille documentaire personnelle)"
TIMEOUT_HTTP = 25          # par source : une source morte ne bloque pas le lot
TIMEOUT_CLAUDE = 180
MAX_ITEMS_NOTES = 120      # plafond de sécurité sur la taille du prompt
PAUSE = 0.3                # politesse entre deux requêtes


# ---------------------------------------------------------------- utilitaires

def ecrire_json(path, data, indent=None):
    """Écriture atomique : tmp + os.replace (un crash ne tronque pas le JSON)."""
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=indent),
                         encoding="utf-8")
    os.replace(tmp, path)


def charger(p, defaut):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else defaut
    except Exception:
        return defaut


def maintenant():
    return datetime.now(timezone.utc)


def statut(token, **kw):
    """Avancement lisible par l'appli (mécanique de « ➕ Ajouter » et du
    documentaliste). Sans token, on n'écrit rien."""
    if not token:
        return
    try:
        PDFS.mkdir(exist_ok=True)
        tmp = PDFS / f".statut-veille-{token}.json.tmp"
        tmp.write_text(json.dumps(kw, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, PDFS / f".statut-veille-{token}.json")
    except Exception:
        pass


def uid_de(url, titre):
    """Identité d'un item. On la calcule sur le TITRE normalisé, pas sur l'URL :
    un même article revient sous deux identifiants OpenAlex, et se retrouve à la
    fois dans HAL et dans OpenAlex (constaté au test du 2026-08-04). Repli sur
    l'URL pour les titres trop courts pour être discriminants."""
    t = re.sub(r"[^a-z0-9]+", "", (titre or "").lower())
    base = t if len(t) >= 15 else (url or "").strip().lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def nettoyer(txt, limite=700):
    """HTML → texte lisible, sans dépendance."""
    if not txt:
        return ""
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", txt)
    t = re.sub(r"(?i)<br\s*/?>|</p>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t[:limite]


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_HTTP) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def http_texte(url, timeout=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/rss+xml, application/xml, text/xml"})
    with urllib.request.urlopen(req, timeout=timeout or TIMEOUT_HTTP) as r:
        brut = r.read()
    return brut.decode("utf-8", "replace")


def sans_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def date_iso(txt):
    """RFC 822 (RSS) ou ISO 8601 (Atom) → datetime aware. None si illisible."""
    if not txt:
        return None
    txt = txt.strip()
    try:
        d = parsedate_to_datetime(txt)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        pass
    try:
        d = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


# ------------------------------------------------------------------ collecte

def collecter_rss(src, depuis):
    """RSS 2.0 et Atom, même code : on ignore les espaces de noms."""
    items = []
    racine = ET.fromstring(http_texte(src["url"]))
    entrees = [e for e in racine.iter() if sans_ns(e.tag) in ("item", "entry")]
    for e in entrees[: src.get("max", 20)]:
        champs = {}
        lien = ""
        for enfant in e:
            nom = sans_ns(enfant.tag)
            if nom == "link":
                # RSS : le lien est dans le texte ; Atom : dans l'attribut href
                lien = lien or (enfant.get("href") or (enfant.text or "").strip())
            else:
                champs.setdefault(nom, (enfant.text or "").strip())
        # Certains flux (Géoconfluences, Plone) n'ont pas de <link> par item :
        # l'URL de l'article n'est que dans <guid>.
        if not lien and champs.get("guid", "").startswith("http"):
            lien = champs["guid"]
        titre = nettoyer(champs.get("title", ""), 300)
        if not titre:
            continue
        d = (date_iso(champs.get("pubDate") or champs.get("published")
                      or champs.get("updated") or champs.get("date")))
        if d and d < depuis:
            continue
        resume = nettoyer(champs.get("description") or champs.get("summary")
                          or champs.get("content") or "")
        items.append({
            "url": lien, "titre": titre, "resume": resume,
            "date": d.date().isoformat() if d else "",
            "auteurs": nettoyer(champs.get("creator") or champs.get("author") or "", 120),
            "source_id": src["id"], "source_nom": src["nom"], "pdf": "",
        })
    return items


def collecter_hal(src, depuis):
    items = []
    jours = max(1, (maintenant() - depuis).days)
    for q in src.get("requetes", []):
        params = {
            "q": q,
            "fq": f"submittedDate_tdate:[NOW-{jours}DAYS TO NOW]",
            "fl": "docid,title_s,uri_s,abstract_s,producedDateY_i,authFullName_s,fileMain_s,submittedDate_tdate",
            "rows": str(src.get("max_par_requete", 10)),
            "sort": "submittedDate_tdate desc",
            "wt": "json",
        }
        url = "https://api.archives-ouvertes.fr/search/?" + urllib.parse.urlencode(params)
        d = http_json(url)
        for doc in d.get("response", {}).get("docs", []):
            titre = (doc.get("title_s") or [""])[0]
            if not titre:
                continue
            dt = date_iso(doc.get("submittedDate_tdate", ""))
            auteurs = ", ".join((doc.get("authFullName_s") or [])[:4])
            items.append({
                "url": doc.get("uri_s", ""),
                "titre": nettoyer(titre, 300),
                "resume": nettoyer((doc.get("abstract_s") or [""])[0]),
                "date": dt.date().isoformat() if dt else str(doc.get("producedDateY_i", "")),
                "auteurs": auteurs,
                "source_id": src["id"], "source_nom": src["nom"],
                "pdf": doc.get("fileMain_s", "") or "",
            })
        time.sleep(PAUSE)
    return items


def resume_openalex(inv):
    """OpenAlex donne l'abstract en index inversé — on le remet à l'endroit."""
    if not isinstance(inv, dict) or not inv:
        return ""
    positions = []
    for mot, idx in inv.items():
        for i in idx:
            positions.append((i, mot))
    positions.sort()
    return " ".join(m for _, m in positions)


def collecter_openalex(src, depuis):
    """Tri par PERTINENCE (défaut d'OpenAlex), surtout pas par date : trier par
    date sur un ensemble large remonte les nouveautés d'un fatras hors sujet."""
    items = []
    aujourdhui = maintenant().date().isoformat()
    for q in src.get("requetes", []):
        filtre = (f"title_and_abstract.search:{q},"
                  f"from_publication_date:{depuis.date().isoformat()},"
                  f"to_publication_date:{aujourdhui}")
        params = {
            "filter": filtre,
            "per-page": str(src.get("max_par_requete", 10)),
            "select": "id,doi,title,publication_date,abstract_inverted_index,authorships,primary_location,open_access",
        }
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        d = http_json(url)
        for w in d.get("results", []):
            titre = w.get("title") or ""
            if not titre:
                continue
            auteurs = ", ".join(
                (a.get("author") or {}).get("display_name", "")
                for a in (w.get("authorships") or [])[:4])
            lieu = w.get("primary_location") or {}
            items.append({
                "url": w.get("doi") or lieu.get("landing_page_url") or w.get("id", ""),
                "titre": nettoyer(titre, 300),
                "resume": nettoyer(resume_openalex(w.get("abstract_inverted_index"))),
                "date": w.get("publication_date", ""),
                "auteurs": auteurs,
                "source_id": src["id"], "source_nom": src["nom"],
                "pdf": (w.get("open_access") or {}).get("oa_url") or lieu.get("pdf_url") or "",
            })
        time.sleep(PAUSE)
    return items


COLLECTEURS = {"rss": collecter_rss, "hal": collecter_hal, "openalex": collecter_openalex}


def collecter(conf, depuis, journal):
    bruts = []
    for src in conf.get("sources", []):
        if not src.get("actif") or not src.get("id"):
            continue
        fn = COLLECTEURS.get(src.get("type"))
        if not fn:
            journal.append(f"⚠ {src.get('id')} : type « {src.get('type')} » inconnu, ignorée.")
            continue
        # Fenêtre propre à la source : une source lente (un billet par mois)
        # doit remonter plus loin qu'un fil quotidien, sinon on ne voit rien.
        # On garde la date la PLUS ANCIENNE des deux — c'est un plancher.
        depuis_src = depuis
        if src.get("fenetre_jours"):
            profond = maintenant() - timedelta(days=int(src["fenetre_jours"]))
            depuis_src = min(depuis, profond)
        try:
            lot = fn(src, depuis_src)
            bruts.extend(lot)
            journal.append(f"✓ {src['nom']} : {len(lot)} item(s)")
        except urllib.error.HTTPError as e:
            journal.append(f"✗ {src['nom']} : HTTP {e.code} — source ignorée ce coup-ci.")
        except Exception as e:
            journal.append(f"✗ {src['nom']} : {type(e).__name__} — {e}")
    return bruts


# ----------------------------------------------------------------- notation

def bloc_prompt(missions, items, plafond):
    entetes = []
    for n, it in enumerate(items, 1):
        entetes.append(
            f"[{n}] {it['titre']}\n"
            f"Source : {it['source_nom']} | Date : {it['date'] or '?'}"
            + (f" | Auteurs : {it['auteurs']}" if it["auteurs"] else "") + "\n"
            f"Résumé : {it['resume'] or '(pas de résumé)'}")
    corpus = "\n\n".join(entetes)
    # Le rôle, les priorités et les exclusions viennent du profil
    # (veille_sources.json) : changer de métier = changer le profil, pas le code.
    instruction = (
        "Tu tries une veille documentaire pour la personne décrite ci-dessous. "
        "Voici son profil et ses critères :\n\n" + missions + "\n\n"
        "On te fournit " + str(len(items)) + " nouveautés (chacune numérotée, avec "
        "sa source, sa date et son résumé). Sélectionne UNIQUEMENT celles qui lui "
        "servent vraiment, et note-les de 0 à 100.\n\n"
        "Sois SÉVÈRE et franc : mieux vaut 4 items justes que 15 tièdes. Écarte "
        "sans hésiter ce que le profil exclut ou qui en sort.\n\n"
        "Pour chaque item retenu, donne une RAISON en une phrase courte et "
        "concrète : en quoi ça lui sert, concrètement (cours, niveau, usage). Pas de "
        "paraphrase du titre.\n\n"
        "Réponds UNIQUEMENT par un tableau JSON valide, sans texte avant ni après, "
        "sans barrières de code, au format exact :\n"
        "[{\"n\": <numéro>, \"score\": <0-100>, \"raison\": \"<une phrase>\"}]\n"
        "Au maximum " + str(plafond) + " items. Si rien ne vaut le coup, renvoie []."
    )
    return instruction, corpus


def claude_noter(instruction, corpus):
    claude = str(Path.home() / ".local/bin/claude")
    if not os.path.exists(claude):
        claude = shutil.which("claude") or "claude"
    env = os.environ.copy()
    env["PATH"] = (f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:"
                   + env.get("PATH", ""))
    r = subprocess.run([claude, "-p", instruction], input=corpus,
                       capture_output=True, text=True, cwd=tempfile.gettempdir(),
                       env=env, timeout=TIMEOUT_CLAUDE)
    return (r.stdout or "").strip()


def extraire_json(s):
    """Récupère le tableau JSON même si Claude l'encadre de prose ou de ```."""
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```\s*$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\[.*\]", s, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def noter(items, profil, journal):
    plafond = int(profil.get("max_retenus", 15))
    seuil = int(profil.get("score_minimum", 55))
    lot = items[:MAX_ITEMS_NOTES]
    if len(items) > len(lot):
        journal.append(f"⚠ {len(items) - len(lot)} item(s) non notés (plafond de prompt).")
    missions = profil.get("missions", "")
    if profil.get("criteres"):
        missions += "\n\n" + profil["criteres"]
    instruction, corpus = bloc_prompt(missions, lot, plafond)
    brut = claude_noter(instruction, corpus)
    if not brut:
        raise RuntimeError("Claude n'a rien renvoyé (réseau ou quota ?).")
    data = extraire_json(brut)
    if not isinstance(data, list):
        raise RuntimeError("Réponse de Claude illisible.")
    retenus, vus_n = [], set()
    for e in data:
        if not isinstance(e, dict):
            continue
        try:
            n = int(e.get("n", 0))
        except Exception:
            continue
        if not (1 <= n <= len(lot)) or n in vus_n:
            continue
        vus_n.add(n)
        try:
            score = int(round(float(e.get("score", 0))))
        except Exception:
            score = 0
        score = max(0, min(100, score))
        if score < seuil:
            continue
        it = dict(lot[n - 1])
        it["score"] = score
        it["raison"] = str(e.get("raison", "")).strip()[:240]
        retenus.append(it)
    retenus.sort(key=lambda x: -x["score"])
    return retenus[:plafond]


# ------------------------------------------------- ajout d'une source (outil)

SUFFIXES_FLUX = ["/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml",
                 "/index.xml", "/feed/", "/?feed=rss2"]


def sonder_flux(url, timeout=10):
    """Un flux valide ? Renvoie (nb_items, date_du_plus_recent) ou None.
    Délai court : on sonde jusqu'à 9 candidats, un timeout long ferait
    patienter Greg une éternité devant un site sans flux."""
    try:
        racine = ET.fromstring(http_texte(url, timeout=timeout))
    except Exception:
        return None
    entrees = [e for e in racine.iter() if sans_ns(e.tag) in ("item", "entry")]
    if not entrees:
        return None
    dates = []
    for e in entrees:
        for c in e:
            if sans_ns(c.tag) in ("pubDate", "published", "updated", "date"):
                d = date_iso((c.text or "").strip())
                if d:
                    dates.append(d)
    return len(entrees), (max(dates) if dates else None)


def trouver_flux(page_url, token=""):
    """Découvre le flux d'un site à partir de n'IMPORTE quelle page : d'abord le
    <link rel="alternate"> du <head>, puis les suffixes usuels sur la racine."""
    candidats = []
    statut(token, phase="recherche", message="Lecture de la page…")
    try:
        req = urllib.request.Request(page_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Safari/605.1.15"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_HTTP) as r:
            page = r.read().decode("utf-8", "replace")
        for m in re.finditer(r"<link[^>]+>", page, flags=re.I):
            balise = m.group(0)
            if not re.search(r'type=["\']application/(rss|atom)\+xml', balise, re.I):
                continue
            h = re.search(r'href=["\']([^"\']+)["\']', balise, re.I)
            if h:
                candidats.append(urllib.parse.urljoin(page_url, html.unescape(h.group(1))))
    except Exception:
        pass
    p = urllib.parse.urlparse(page_url)
    racine = f"{p.scheme}://{p.netloc}"
    candidats += [racine + s for s in SUFFIXES_FLUX]
    vus_url = set()
    for n, c in enumerate(candidats, 1):
        if c in vus_url:
            continue
        vus_url.add(c)
        statut(token, phase="recherche",
               message=f"Essai {n}/{len(candidats)} : {c.split('/')[-1] or '/'}…")
        sonde = sonder_flux(c)
        if sonde:
            return c, sonde
    return None, None


def ajouter_source(page_url, nom_force=None, token=""):
    conf = charger(CONF, None)
    if not conf:
        msg = f"Profil introuvable ({CONF.name})."
        statut(token, phase="erreur", message=msg); print("ERREUR :", msg)
        return 1
    print(f"Recherche d'un flux pour {page_url} …")
    flux, sonde = trouver_flux(page_url, token)
    if not flux:
        msg = ("Aucun flux RSS/Atom trouvé sur ce site. Soit il n'en publie pas, "
               "soit il bloque les scripts (cas de education.gouv.fr).")
        statut(token, phase="erreur", message=msg)
        print(msg + "\n  → Une page d'article seule ne suffit pas : il faut un flux.")
        return 1
    nb, recent = sonde
    for s in conf.get("sources", []):
        if s.get("url") == flux:
            msg = (f"Ce flux est déjà déclaré : « {s.get('nom')} » "
                   f"({'actif' if s.get('actif') else 'inactif'}).")
            statut(token, phase="fini", deja=True, message=msg)
            print(msg)
            return 0
    dom = urllib.parse.urlparse(flux).netloc.replace("www.", "")
    ident = re.sub(r"[^a-z0-9]+", "_", dom.lower()).strip("_")
    existants = {s.get("id") for s in conf.get("sources", [])}
    base, n = ident, 2
    while ident in existants:
        ident = f"{base}_{n}"; n += 1
    src = {"id": ident, "nom": nom_force or dom, "type": "rss",
           "actif": True, "url": flux, "max": 20}
    conf["sources"].append(src)
    ecrire_json(CONF, conf, indent=2)
    dormante = bool(recent and (maintenant() - recent).days > 90)
    msg = (f"{nb} article(s), le plus récent du "
           f"{recent.date().isoformat() if recent else 'date inconnue'}.")
    if dormante:
        msg += (f" ⚠ Rien publié depuis {(maintenant() - recent).days} jours — "
                "source peut-être arrêtée.")
    statut(token, phase="fini", deja=False, flux=flux, nom=src["nom"],
           items=nb, dormante=dormante, message=msg)
    print(f"✓ Flux trouvé  : {flux}")
    print("  " + msg)
    print(f"✓ Ajoutée au profil sous l'identifiant « {ident} ».")
    print(f"  Renomme-la et règle `max` / `fenetre_jours` dans {CONF.name} si besoin.")
    return 0


# --------------------------------------------------------------------- main

def main():
    args = sys.argv[1:]
    sortie_json = "--json" in args
    sans_ia = "--sans-ia" in args
    blanc = "--blanc" in args
    sans_memoire = "--sans-memoire" in args
    token = ""
    if "--token" in args:
        i = args.index("--token")
        token = args[i + 1] if i + 1 < len(args) else ""
    jours = None
    if "--jours" in args:
        i = args.index("--jours")
        try:
            jours = int(args[i + 1])
        except Exception:
            jours = None

    # Outil d'ajout de source : découvre le flux d'un site depuis n'importe
    # laquelle de ses pages, le teste, et l'inscrit au profil.
    if "--ajouter-source" in args:
        i = args.index("--ajouter-source")
        url = args[i + 1] if i + 1 < len(args) else ""
        nom = None
        if "--nom" in args:
            j = args.index("--nom")
            nom = args[j + 1] if j + 1 < len(args) else None
        tok = ""
        if "--token" in args:
            k = args.index("--token")
            tok = args[k + 1] if k + 1 < len(args) else ""
        if not url:
            print("Usage : veille.py --ajouter-source <url du site> [--nom \"…\"]")
            sys.exit(1)
        sys.exit(ajouter_source(url, nom, tok))

    journal = []
    try:
        conf = charger(CONF, None)
        if not conf:
            raise RuntimeError(f"Profil de veille introuvable ou illisible : {CONF.name}")
        profil = conf.get("profil", {})
        fil = charger(FIL, {"dernier_lancement": "", "items": []})
        vus = charger(VUS, {})

        # Fenêtre : depuis le dernier lancement, sinon la valeur par défaut.
        if jours is not None:
            depuis = maintenant() - timedelta(days=max(1, jours))
        else:
            d = date_iso(fil.get("dernier_lancement", ""))
            depuis = d or (maintenant()
                           - timedelta(days=int(profil.get("fenetre_defaut_jours", 30))))
        journal.append(f"Fenêtre : depuis le {depuis.date().isoformat()}")
        actives = [s for s in conf.get("sources", []) if s.get("actif")]
        statut(token, phase="collecte",
               message=f"Interrogation de {len(actives)} source(s)…")

        bruts = collecter(conf, depuis, journal)
        if not bruts:
            raise RuntimeError("Aucune source n'a répondu — rien à trier.")

        # Dédoublonnage interne + oubli de ce qui a déjà été proposé une fois.
        nouveaux, vus_ce_lot = [], set()
        for it in bruts:
            u = uid_de(it["url"], it["titre"])
            if u in vus or u in vus_ce_lot:
                continue
            vus_ce_lot.add(u)
            it["uid"] = u
            nouveaux.append(it)
        journal.append(f"{len(bruts)} collecté(s) → {len(nouveaux)} nouveau(x) jamais vu(s)")

        if not nouveaux:
            resultat = {"ok": True, "retenus": [], "collectes": len(bruts),
                        "nouveaux": 0, "journal": journal,
                        "message": "Rien de neuf depuis le dernier lancement."}
        elif sans_ia:
            resultat = {"ok": True, "retenus": [], "collectes": len(bruts),
                        "nouveaux": len(nouveaux), "journal": journal,
                        "apercu": [{"titre": i["titre"], "source": i["source_nom"],
                                    "date": i["date"]} for i in nouveaux],
                        "message": "Collecte seule (--sans-ia) : aucune notation."}
        else:
            statut(token, phase="notation",
                   message=f"{len(nouveaux)} nouveauté(s) — Claude fait le tri…")
            retenus = noter(nouveaux, profil, journal)
            journal.append(f"Claude en retient {len(retenus)} "
                           f"(score ≥ {profil.get('score_minimum', 55)})")
            horodatage = maintenant().isoformat()
            for it in retenus:
                it["vu_le"] = horodatage
                it["statut"] = "nouveau"
            resultat = {"ok": True, "retenus": retenus, "collectes": len(bruts),
                        "nouveaux": len(nouveaux), "journal": journal}

            if not blanc:
                # Le fil : les retenus en tête, purge des vieux items.
                limite = maintenant() - timedelta(
                    days=int(profil.get("purge_apres_jours", 180)))
                anciens = [i for i in fil.get("items", [])
                           if (date_iso(i.get("vu_le", "")) or maintenant()) >= limite]
                deja = {i.get("uid") for i in anciens}
                fil["items"] = [i for i in retenus if i["uid"] not in deja] + anciens
                fil["dernier_lancement"] = horodatage
                ecrire_json(FIL, fil, indent=1)
                # Mémoire des vus : TOUT le lot, écartés compris (jamais reproposés).
                # Sauf en --sans-memoire, où l'on garde les écartés « frais » pour
                # qu'un prompt de notation amélioré puisse les rattraper.
                if sans_memoire:
                    journal.append("⚠ --sans-memoire : aucun item marqué vu, "
                                   "ce lot sera renoté au prochain lancement.")
                else:
                    jour = maintenant().date().isoformat()
                    for it in nouveaux:
                        vus[it["uid"]] = jour
                    ecrire_json(VUS, vus)

        statut(token, phase="fini",
               retenus=len(resultat.get("retenus", [])),
               collectes=resultat.get("collectes", 0),
               nouveaux=resultat.get("nouveaux", 0),
               message=resultat.get("message", ""), journal=journal)

        if sortie_json:
            sys.stdout.write(json.dumps(resultat, ensure_ascii=False))
        else:
            for l in journal:
                print(l)
            print()
            if resultat.get("message"):
                print(resultat["message"])
            for it in resultat.get("apercu", []):
                print(f"  · {it['date']:<10} {it['source']:<28} {it['titre'][:70]}")
            for it in resultat.get("retenus", []):
                print(f"\n[{it['score']:>3}] {it['titre']}")
                print(f"      {it['source_nom']} — {it['date'] or 'date ?'}")
                print(f"      ↳ {it['raison']}")
                print(f"      {it['url']}")
            if blanc:
                print("\n(essai à blanc : rien n'a été écrit)")

    except subprocess.TimeoutExpired:
        resultat = {"ok": False, "erreur": "Claude a mis trop de temps (timeout).",
                    "journal": journal}
        statut(token, phase="erreur", message=resultat["erreur"], journal=journal)
        if sortie_json:
            sys.stdout.write(json.dumps(resultat, ensure_ascii=False))
        else:
            print("\n".join(journal)); print("ERREUR :", resultat["erreur"])
        sys.exit(1)
    except Exception as e:
        resultat = {"ok": False, "erreur": str(e), "journal": journal}
        statut(token, phase="erreur", message=str(e), journal=journal)
        if sortie_json:
            sys.stdout.write(json.dumps(resultat, ensure_ascii=False))
        else:
            print("\n".join(journal)); print("ERREUR :", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
