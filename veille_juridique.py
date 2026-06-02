"""
LexPulse — Agent de veille juridique
Collecte depuis avril 2025, génère data/veille.json pour GitHub Pages
"""
import os, json, datetime, requests
from pathlib import Path

MISTRAL_KEY = os.environ["MISTRAL_API_KEY"]
TODAY = datetime.date.today().isoformat()
WEEK_START = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
SINCE_APRIL = "2025-04-01"  # première exécution : remonte depuis avril

# Si le fichier existe déjà, on incrémente. Sinon on part d'avril.
DATA_FILE = Path("data/veille.json")
is_first_run = not DATA_FILE.exists()
DATE_FROM = SINCE_APRIL if is_first_run else WEEK_START

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASS", "")
GMAIL_TO   = os.environ.get("GMAIL_RECIPIENT", "")

CATEGORY_MAP = {
    "rgpd": "RGPD",
    "ai": "AI Act",
    "sante": "Santé",
    "juris": "Jurisprudence",
    "legis": "Législation",
    "dsa": "DSA",
}

# ─── SOURCES ──────────────────────────────────────────────

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LexPulse/1.0)"}

def parse_rss(url, source, category, max_items=6):
    """Parse générique d'un flux RSS."""
    import xml.etree.ElementTree as ET
    items = []
    try:
        r = requests.get(url, timeout=12, headers=HEADERS)
        if not r.ok:
            return items
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # RSS 2.0
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            link  = item.findtext("link", "").strip()
            pub   = item.findtext("pubDate", TODAY)[:16]
            if title:
                items.append({"title": title, "source": source, "category": category,
                              "date": pub, "url": link, "text": desc[:600]})
        # Atom
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:max_items]:
                title = entry.findtext("atom:title", "", ns).strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href","") if link_el is not None else ""
                summary = entry.findtext("atom:summary", "", ns).strip()
                pub = entry.findtext("atom:updated", TODAY, ns)[:10]
                if title:
                    items.append({"title": title, "source": source, "category": category,
                                  "date": pub, "url": link, "text": summary[:600]})
    except Exception:
        pass
    return items

def scrape_donneespersonnelles():
    """Scrape donneespersonnelles.fr via flux RSS/pages."""
    items = []
    sources = [
        ("https://www.donneespersonnelles.fr/actualite-rgpd-2026", "rgpd"),
        ("https://www.donneespersonnelles.fr/actualite-ia-2026", "ai"),
        ("https://www.donneespersonnelles.fr/actualite-nis2-2026", "legis"),
    ]
    from html.parser import HTMLParser
    class H4Parser(HTMLParser):
        def __init__(self):
            super().__init__(); self.items = []; self._cur = None; self._in = False
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                d = dict(attrs)
                if d.get("href","").startswith("https://www.donneespersonnelles.fr/actualite"):
                    self._in = True; self._cur = {"url": d["href"], "text": ""}
        def handle_endtag(self, tag):
            if tag == "a" and self._in:
                self._in = False
                if self._cur and self._cur.get("text","").strip():
                    self.items.append(self._cur)
                self._cur = None
        def handle_data(self, data):
            if self._in and self._cur:
                self._cur["text"] += data
    for url, cat in sources:
        try:
            r = requests.get(url, timeout=10, headers=HEADERS)
            if not r.ok: continue
            p = H4Parser()
            p.feed(r.text)
            for it in p.items[:5]:
                t = it["text"].strip()
                if len(t) > 15:
                    items.append({"title": t, "source": "donneespersonnelles.fr",
                                  "category": cat, "date": TODAY, "url": it["url"], "text": t})
        except Exception:
            pass
    return items

def scrape_village_justice():
    """Village Justice — rubrique droit numérique via RSS."""
    # VJ expose un flux RSS général + rubriques
    rss_url = "https://www.village-justice.com/articles/spip.php?page=backend&rubrique=431"
    items = parse_rss(rss_url, "Village de la Justice", "rgpd", max_items=8)
    # Rubrique IA
    items += parse_rss(
        "https://www.village-justice.com/articles/spip.php?page=backend&rubrique=intelligence-artificielle",
        "Village de la Justice", "ai", max_items=5
    )
    # Rubrique numérique générale
    items += parse_rss(
        "https://www.village-justice.com/articles/spip.php?page=backend",
        "Village de la Justice", "legis", max_items=4
    )
    # Filtrer par pertinence thématique
    keywords = ["RGPD","données","IA","AI Act","numérique","CNIL","DSA","cyber","blockchain","plateforme"]
    filtered = [it for it in items if any(k.lower() in (it["title"]+" "+it["text"]).lower() for k in keywords)]
    return filtered[:10]

def fetch_edpb():
    """EDPB — lignes directrices et décisions."""
    return parse_rss(
        "https://www.edpb.europa.eu/news/news_en.rss",
        "EDPB", "rgpd", max_items=5
    )

def fetch_anssi():
    """ANSSI — alertes et publications NIS2/cybersécurité."""
    return parse_rss(
        "https://www.cert.ssi.gouv.fr/feed/",
        "ANSSI / CERT-FR", "legis", max_items=4
    )

def fetch_linc():
    """LINC — laboratoire innovation numérique de la CNIL."""
    items = []
    try:
        r = requests.get("https://linc.cnil.fr/fr/rss.xml", timeout=10, headers=HEADERS)
        if r.ok:
            items = parse_rss("https://linc.cnil.fr/fr/rss.xml", "LINC (CNIL)", "rgpd", max_items=4)
    except Exception:
        pass
    return items

def fetch_legalis():
    """Legalis.net — actualités et jurisprudences droit des NTIC (WordPress RSS)."""
    items = []
    items += parse_rss("https://www.legalis.net/feed/", "Legalis.net", "juris", max_items=6)
    for slug, cat in [("vie-privee", "rgpd"), ("responsabilite", "dsa"), ("e-commerce", "dsa")]:
        items += parse_rss(f"https://www.legalis.net/jurisprudences/{slug}/feed/", "Legalis.net", cat, max_items=3)
    keywords = ["données", "RGPD", "IA", "numérique", "plateforme", "vie privée",
                "responsabilité", "CNIL", "algorithme", "DSA", "cyber", "internet"]
    return [it for it in items if any(k.lower() in (it["title"]+" "+it["text"]).lower() for k in keywords)][:8]

def fetch_arcom():
    """ARCOM — décisions et recommandations (régulation plateformes, DSA, audiovisuel numérique)."""
    items = parse_rss("https://www.arcom.fr/feed", "ARCOM", "dsa", max_items=5)
    if not items:
        # Fallback scraping page actualités
        try:
            r = requests.get("https://www.arcom.fr/nos-ressources/nos-publications/actualites", timeout=10, headers=HEADERS)
            from html.parser import HTMLParser
            class LinkParser(HTMLParser):
                def __init__(self): super().__init__(); self.items = []; self._cur = None
                def handle_starttag(self, tag, attrs):
                    if tag == "a":
                        d = dict(attrs)
                        if "/nos-ressources/" in d.get("href","") and d.get("href","") != "#":
                            self._cur = {"url": "https://www.arcom.fr" + d["href"] if d["href"].startswith("/") else d["href"], "text": ""}
                            self._in = True
                def handle_endtag(self, tag):
                    if tag == "a" and hasattr(self,"_in") and self._in:
                        self._in = False
                        if self._cur and len(self._cur.get("text","")) > 15:
                            self.items.append(self._cur); self._cur = None
                def handle_data(self, data):
                    if hasattr(self,"_in") and self._in and self._cur:
                        self._cur["text"] = self._cur.get("text","") + data
            if r.ok:
                p = LinkParser(); p.feed(r.text)
                for it in p.items[:5]:
                    items.append({"title": it["text"].strip(), "source": "ARCOM", "category": "dsa",
                                  "date": TODAY, "url": it["url"], "text": it["text"].strip()})
        except Exception:
            pass
    return items

def fetch_arcep():
    """ARCEP — publications régulation télécoms, plateformes, baromètre numérique."""
    return parse_rss("https://www.arcep.fr/actualites/actualites-et-communiques.html?tx_gsbaktuell_pi1[format]=rss",
                     "ARCEP", "legis", max_items=4)

def fetch_assemblee_nationale():
    """Assemblée nationale — dossiers législatifs numériques en cours (open data)."""
    items = []
    try:
        # API open data dossiers législatifs — filtrer sur thème numérique
        r = requests.get(
            "https://data.assemblee-nationale.fr/api/v2/dossiers?theme=numérique&limit=5",
            timeout=12, headers=HEADERS
        )
        if r.ok:
            for d in r.json().get("items", []):
                items.append({
                    "title": d.get("titre", "Dossier législatif AN"),
                    "source": "Assemblée nationale",
                    "category": "legis",
                    "date": d.get("dateMiseAJour", TODAY)[:10],
                    "url": f"https://www.assemblee-nationale.fr/dyn/dossiers/{d.get('uid','')}",
                    "text": d.get("titreCourt", "")
                })
    except Exception:
        pass
    # Fallback : flux RSS général AN (ordres du jour, séances)
    if not items:
        items = parse_rss("https://www.assemblee-nationale.fr/dyn/rss/actualite.rss",
                          "Assemblée nationale", "legis", max_items=4)
        keywords = ["numérique","données","intelligence artificielle","IA","RGPD","cyber","plateforme","DSA"]
        items = [it for it in items if any(k.lower() in (it["title"]+" "+it["text"]).lower() for k in keywords)]
    return items[:5]

def fetch_senat():
    """Sénat — actualités législatives numériques."""
    items = parse_rss("https://www.senat.fr/rss/rss_actualites.xml", "Sénat", "legis", max_items=6)
    keywords = ["numérique","données","intelligence artificielle","IA","RGPD","cyber","plateforme","AI Act","DSA"]
    return [it for it in items if any(k.lower() in (it["title"]+" "+it["text"]).lower() for k in keywords)][:4]

def fetch_jorf():
    """Journal officiel (JORF) via PISTE — décrets et arrêtés numériques récents."""
    items = []
    piste_key = os.environ.get("PISTE_API_KEY", "")
    if not piste_key or piste_key == "vide":
        return items
    try:
        r = requests.get(
            "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/jorf/search",
            headers={"KeyId": piste_key, "Accept": "application/json"},
            json={"recherche": {"champs": [{"typeChamp": "ALL", "criteres": [{"typeRecherche": "EXACTE", "valeur": "données personnelles"}]}],
                                "datePublication": {"debut": DATE_FROM}, "pageNumber": 1, "pageSize": 5}},
            timeout=15
        )
        if r.ok:
            for item in r.json().get("results", []):
                items.append({
                    "title": item.get("titre", "Texte JORF"),
                    "source": "Journal officiel (JORF)",
                    "category": "legis",
                    "date": item.get("datePublication", TODAY)[:10],
                    "url": f"https://www.legifrance.gouv.fr/jorf/id/{item.get('id','')}",
                    "text": item.get("nature", "") + " — " + item.get("titre","")[:300]
                })
    except Exception:
        pass
    return items

def fetch_legiwatch_blog():
    """Legiwatch blog — articles analytiques libres sur affaires publiques et numérique."""
    items = parse_rss("https://www.legiwatch.fr/blog/rss.xml", "Legiwatch (blog)", "legis", max_items=4)
    if not items:
        items = parse_rss("https://www.legiwatch.fr/feed.xml", "Legiwatch (blog)", "legis", max_items=4)
    keywords = ["numérique","IA","RGPD","données","DSA","AI Act","cyber","plateforme","réglementation"]
    return [it for it in items if any(k.lower() in (it["title"]+" "+it["text"]).lower() for k in keywords)][:4]

def fetch_cnil_news():
    """Flux CNIL via leur flux RSS/JSON public"""
    items = []
    try:
        r = requests.get("https://www.cnil.fr/fr/rss.xml", timeout=10)
        if r.ok:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:8]:
                title = item.findtext("title", "")
                desc  = item.findtext("description", "")
                link  = item.findtext("link", "")
                pub   = item.findtext("pubDate", "")
                items.append({
                    "title": title, "source": "CNIL", "category": "rgpd",
                    "date": pub[:16] if pub else TODAY,
                    "url": link, "text": desc[:500]
                })
    except Exception:
        pass
    return items

def fetch_eurlex_recent():
    """Dernières publications EUR-Lex (AI Act, DSA, RGPD)"""
    items = []
    queries = [
        ("AI Act regulation artificial intelligence", "ai"),
        ("GDPR data protection personal data", "rgpd"),
        ("Digital Services Act platform liability", "dsa"),
    ]
    for query, cat in queries:
        try:
            r = requests.get(
                "https://publications.europa.eu/webapi/rdf/sparql",
                params={
                    "query": f"""SELECT ?title ?date ?url WHERE {{
                      ?doc <http://purl.org/dc/elements/1.1/title> ?title .
                      ?doc <http://purl.org/dc/elements/1.1/date> ?date .
                      OPTIONAL {{ ?doc <http://www.w3.org/2002/07/owl#sameAs> ?url }}
                      FILTER(lang(?title) = "fr" || lang(?title) = "en")
                      FILTER(contains(lcase(str(?title)), lcase("{query.split()[0]}")))
                      FILTER(?date >= "{DATE_FROM}"^^<http://www.w3.org/2001/XMLSchema#date>)
                    }} LIMIT 3""",
                    "format": "application/sparql-results+json"
                },
                timeout=15
            )
            if r.ok:
                for b in r.json().get("results", {}).get("bindings", []):
                    items.append({
                        "title": b.get("title", {}).get("value", ""),
                        "source": "EUR-Lex",
                        "category": cat,
                        "date": b.get("date", {}).get("value", TODAY)[:10],
                        "url": b.get("url", {}).get("value", ""),
                        "text": b.get("title", {}).get("value", "")
                    })
        except Exception:
            pass
    return items

def fetch_judilibre():
    """Cour de cassation via Judilibre"""
    items = []
    piste_key = os.environ.get("PISTE_API_KEY", "")
    if not piste_key or piste_key == "vide":
        return items
    try:
        r = requests.get(
            "https://api.piste.gouv.fr/cassation/judilibre/v1.0/search",
            headers={"KeyId": piste_key},
            params={"query": "données personnelles RGPD", "date_start": DATE_FROM, "page_size": 5},
            timeout=15
        )
        if r.ok:
            for item in r.json().get("results", []):
                items.append({
                    "title": item.get("titre", "Arrêt Cour de cassation"),
                    "source": "Cour de cassation",
                    "category": "juris",
                    "date": item.get("decision_date", TODAY)[:10],
                    "url": f"https://www.courdecassation.fr/decision/{item.get('id','')}",
                    "text": item.get("sommaire", "")[:600]
                })
    except Exception:
        pass
    return items

def collect_all():
    all_items = []
    print("   → donneespersonnelles.fr...")
    all_items += scrape_donneespersonnelles()
    print("   → Village de la Justice...")
    all_items += scrape_village_justice()
    print("   → CNIL RSS...")
    all_items += fetch_cnil_news()
    print("   → EDPB...")
    all_items += fetch_edpb()
    print("   → ANSSI...")
    all_items += fetch_anssi()
    print("   → LINC (CNIL)...")
    all_items += fetch_linc()
    print("   → Legalis.net...")
    all_items += fetch_legalis()
    print("   → ARCOM...")
    all_items += fetch_arcom()
    print("   → ARCEP...")
    all_items += fetch_arcep()
    print("   → Assemblée nationale...")
    all_items += fetch_assemblee_nationale()
    print("   → Sénat...")
    all_items += fetch_senat()
    print("   → JORF (Légifrance)...")
    all_items += fetch_jorf()
    print("   → Legiwatch blog...")
    all_items += fetch_legiwatch_blog()
    print("   → EUR-Lex...")
    all_items += fetch_eurlex_recent()
    print("   → Judilibre...")
    all_items += fetch_judilibre()
    # Dédoublonnage par titre
    seen = set()
    unique = []
    for it in all_items:
        k = it["title"][:60].lower().strip()
        if k not in seen and len(it["title"]) > 10:
            seen.add(k)
            unique.append(it)
    return unique

# ─── MISTRAL ──────────────────────────────────────────────

def mistral(prompt, system="""Tu es un juriste expert en droit du numérique français et européen.
Tu écris en français naturel et direct, comme si tu expliquais à un collègue juriste intelligent mais pressé.
Tes phrases sont courtes et claires. Tu évites absolument : les tournures administratives, les mots pompeux, le jargon inutile, les formules creuses comme "il convient de noter que", "force est de constater", "à cet égard", "en l'espèce" quand ce n'est pas nécessaire, "il y a lieu de".
Tu vas droit au but : qu'est-ce qui s'est passé, pourquoi c'est important, ce que ça change concrètement."""):
    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_KEY}", "Content-Type": "application/json"},
        json={"model": "mistral-small-latest", "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ]},
        timeout=45
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def enrich_article(item):
    """Génère un article court enrichi pour chaque actualité."""
    prompt = f"""Actualité juridique : "{item['title']}"
Source : {item['source']} | Catégorie : {item.get('category','')}
Texte brut : {item.get('text','')[:400]}

Génère un JSON avec exactement ces champs (réponds UNIQUEMENT avec le JSON, sans backticks) :
{{
  "title": "titre reformulé clair et précis",
  "summary": "résumé factuel en 2 phrases (qu'est-ce qui s'est passé ?)",
  "analysis": "analyse juridique en 2-3 phrases (enjeu, portée, ce que ça change)",
  "avant_apres": "une phrase 'Avant : X. Après : Y.' si pertinent, sinon null",
  "impact": "élevé / modéré / faible",
  "impact_level": "high / med / low",
  "category": "{item.get('category','rgpd')}",
  "category_label": "{CATEGORY_MAP.get(item.get('category','rgpd'), 'RGPD')}",
  "date": "{item.get('date', TODAY)}",
  "source": "{item['source']}",
  "url": "{item.get('url','')}"
}}"""
    try:
        raw = mistral(prompt)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(raw)
    except Exception:
        return {
            "title": item["title"], "summary": item.get("text","")[:200],
            "analysis": "", "avant_apres": None,
            "impact": "modéré", "impact_level": "med",
            "category": item.get("category","rgpd"),
            "category_label": CATEGORY_MAP.get(item.get("category","rgpd"),"RGPD"),
            "date": item.get("date", TODAY),
            "source": item["source"], "url": item.get("url","")
        }

def generate_note_hebdo(articles):
    """Génère la note juridique hebdomadaire structurée."""
    digest = "\n".join(f"- [{a['category_label']}] {a['title']} : {a['summary']}" for a in articles[:20])
    week_label = f"{WEEK_START} au {TODAY}"

    intro_prompt = f"""Tu es juriste expert en droit du numérique. Voici les actualités juridiques de la semaine ({week_label}) :

{digest}

Rédige une INTRODUCTION de la note hebdomadaire (3-4 phrases). Identifie la tendance dominante de la semaine. Style : analytique, direct, comme une lettre du juriste à ses pairs."""

    full_prompt = f"""Tu es juriste expert en droit du numérique. Voici les actualités de la semaine ({week_label}) :

{digest}

Rédige une NOTE JURIDIQUE HEBDOMADAIRE complète (600-800 mots) en HTML structuré avec :
- <h3> pour chaque grande thématique
- <p> pour les analyses
- Des balises <div class="avant-apres"><strong>Avant / Après</strong>...</div> pour les évolutions marquantes
- 3-4 thématiques max : RGPD/données, IA/AI Act, Jurisprudence, Législation EU
- Pour chaque point : contexte, ce qui change, enjeu pratique pour une équipe conformité
- Conclusion prospective (que surveiller la semaine prochaine ?)
Style : analytique mais accessible. Phrases courtes. Pas de listes à puces. Pas de jargon inutile. Écris comme tu parlerais à un collègue juriste, pas comme tu rédigerais un rapport ministériel."""

    try:
        intro = mistral(intro_prompt)
        full = mistral(full_prompt)
        tags = list(set([a["category"] for a in articles[:5]]))[:3]
        return {
            "title": f"Droit du numérique : les évolutions de la semaine du {WEEK_START}",
            "week": week_label,
            "intro": f"<p>{intro}</p>",
            "full_content": full,
            "tags": [CATEGORY_MAP.get(t,t.upper()) for t in tags]
        }
    except Exception:
        return {
            "title": "Note hebdomadaire",
            "week": week_label,
            "intro": "<p>Note en cours de génération.</p>",
            "full_content": "<p>Contenu indisponible.</p>",
            "tags": ["RGPD"]
        }

def generate_suggestions(articles):
    titles = [a["title"] for a in articles[:6]]
    suggestions = [
        f"Explique : {titles[0][:40]}…" if titles else "Quoi de neuf en RGPD ?",
        "Quel est l'impact AI Act cette semaine ?",
        "Fais-moi une fiche sur la dernière décision CNIL",
        "Résume les évolutions en droit de la santé",
    ]
    return suggestions[:4]

# ─── STATS ────────────────────────────────────────────────

def compute_stats(articles):
    from collections import Counter
    cats = Counter(a["category"] for a in articles)
    return {
        "total": len(articles),
        "rgpd": cats.get("rgpd", 0),
        "ai": cats.get("ai", 0),
        "sante": cats.get("sante", 0),
        "juris": cats.get("juris", 0),
        "legis": cats.get("legis", 0) + cats.get("dsa", 0),
    }

# ─── MERGE avec données existantes ────────────────────────

def merge_with_existing(new_articles):
    if not DATA_FILE.exists():
        return new_articles
    try:
        existing = json.loads(DATA_FILE.read_text())
        old = existing.get("articles", [])
        seen = set(a["title"][:60].lower() for a in new_articles)
        for a in old:
            if a["title"][:60].lower() not in seen:
                new_articles.append(a)
        return new_articles[:80]  # garde les 80 plus récents
    except Exception:
        return new_articles

# ─── EMAIL ────────────────────────────────────────────────

def send_email_digest(note, articles):
    if not GMAIL_USER or not GMAIL_PASS:
        return
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    top5 = "".join(f"<li><strong>[{a['category_label']}]</strong> {a['title']} — {a['summary']}</li>" for a in articles[:5])
    html = f"""<html><body style="font-family:Georgia,serif;max-width:680px;margin:auto;color:#1a1a1a">
    <div style="background:#2d4a8a;padding:20px 30px;border-radius:8px 8px 0 0">
      <h1 style="color:#fff;font-size:22px;margin:0">LexPulse</h1>
      <p style="color:#b0c0e0;font-size:13px;margin:4px 0 0">Veille juridique — {TODAY}</p>
    </div>
    <div style="border:1px solid #e8e5df;border-top:none;padding:24px 30px;border-radius:0 0 8px 8px">
      <h2 style="font-size:18px;color:#2d4a8a">{note['title']}</h2>
      <div style="font-size:14px;line-height:1.7">{note['intro']}</div>
      <hr style="border:none;border-top:1px solid #e8e5df;margin:20px 0">
      <h3 style="font-size:14px;text-transform:uppercase;letter-spacing:1px;color:#6b6860">5 actualités à retenir</h3>
      <ul style="font-size:13px;line-height:1.7;padding-left:20px">{top5}</ul>
      <div style="margin-top:24px;background:#eef2fb;padding:12px 16px;border-radius:6px;font-size:13px;color:#2d4a8a">
        → Consultez la note complète et l'agent juridique sur votre portail LexPulse
      </div>
    </div>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📋 LexPulse — Veille juridique du {TODAY}"
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_TO
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASS)
        s.sendmail(GMAIL_USER, GMAIL_TO, msg.as_string())
    print(f"✅ Email envoyé à {GMAIL_TO}")

# ─── MAIN ─────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "--full"

    if mode == "--email-only":
        # Relit le JSON existant et envoie juste l'email
        if DATA_FILE.exists():
            data = json.loads(DATA_FILE.read_text())
            print("📧 Envoi email digest...")
            send_email_digest(data["note_hebdo"], data["articles"])
            print("✅ Email envoyé !")
        else:
            print("❌ Pas de veille.json trouvé pour envoyer l'email.")
        sys.exit(0)

    # Mode normal ou --no-email
    print(f"🔍 Collecte {'complète (depuis avril 2025)' if is_first_run else 'hebdomadaire'}...")
    raw = collect_all()
    print(f"   → {len(raw)} éléments bruts collectés")

    print("🤖 Enrichissement par Mistral...")
    articles = []
    for i, item in enumerate(raw[:25]):
        print(f"   {i+1}/{min(len(raw),25)} — {item['title'][:50]}")
        articles.append(enrich_article(item))

    print("📝 Génération de la note hebdomadaire...")
    note = generate_note_hebdo(articles)
    suggestions = generate_suggestions(articles)

    print("🔀 Fusion avec données existantes...")
    articles = merge_with_existing(articles)

    output = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "note_hebdo": note,
        "articles": articles,
        "stats": compute_stats(articles),
        "suggestions": suggestions
    }

    Path("data").mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"✅ data/veille.json généré ({len(articles)} articles)")

    if mode != "--no-email":
        print("📧 Envoi email...")
        send_email_digest(note, articles)
    print("✅ Terminé !")
