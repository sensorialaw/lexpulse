"""
LexPulse v4 — Agent de veille juridique
Focus : données de santé, CNIL, jurisprudence RGPD, AI Act
Note hebdomadaire formalisée avec notes de bas de page
Fiches d'arrêt depuis Légifrance via PISTE
"""
import os, json, datetime, requests, sys, re
from pathlib import Path

MISTRAL_KEY = os.environ["MISTRAL_API_KEY"]
PISTE_KEY   = os.environ.get("PISTE_API_KEY", "")
TODAY       = datetime.date.today().isoformat()
WEEK_START  = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
SINCE_APRIL = "2025-04-01"

DATA_FILE    = Path("data/veille.json")
is_first_run = not DATA_FILE.exists()
DATE_FROM    = SINCE_APRIL if is_first_run else WEEK_START

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASS", "")
GMAIL_TO   = os.environ.get("GMAIL_RECIPIENT", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LexPulse/1.0)"}

CATEGORY_MAP = {
    "rgpd": "RGPD", "ai": "AI Act", "sante": "Données de santé",
    "juris": "Jurisprudence", "legis": "Législation", "dsa": "DSA / Plateformes",
    "cyber": "Cybersécurité",
}

# Mots-clés de pertinence — strict
STRICT_KEYWORDS = [
    "RGPD","données personnelles","protection des données","données à caractère personnel",
    "AI Act","intelligence artificielle","algorithme","système d'IA","modèle de fondation",
    "DSA","DMA","plateforme","hébergeur","éditeur","modération de contenu",
    "CNIL","EDPB","DPO","délégué protection","délibération","sanction CNIL","mise en demeure",
    "données de santé","HDS","SNDS","entrepôt de données de santé","EDS","EEDS",
    "MR-001","MR-003","MR-006","méthodologie de référence","AIPD",
    "recherche en santé","Jardé","CEREES","CESREES",
    "droit au déréférencement","droit à l'oubli","consentement numérique",
    "cookies","traceurs","profilage","transfert de données","BCR","CCT",
    "violation de données","fuite de données","notification de violation",
    "NIS2","cybersécurité","ANSSI","OIV","OSE",
    "CJUE","Cour de justice","Meta Platforms","Google","Microsoft données",
    "Cour de cassation données","Conseil d'État numérique",
    "Data Act","Data Governance Act","EHDS","espace européen données de santé",
    "blockchain","crypto","MiCA","actifs numériques","registre distribué",
    "biométrie","reconnaissance faciale","identification biométrique",
    "échantillons biologiques","biobanque","génomique","séquençage",
    "pseudonymisation","anonymisation","réidentification",
    "sous-traitant","responsable traitement","co-responsabilité",
    "lignes directrices","recommandation CNIL","avis CEPD",
]

def is_relevant(item):
    text = (item.get("title","") + " " + item.get("text","")).lower()
    return any(kw.lower() in text for kw in STRICT_KEYWORDS)

# ─── RSS PARSER ───────────────────────────────────────────

def parse_rss(url, source, category, max_items=6):
    import xml.etree.ElementTree as ET
    items = []
    try:
        r = requests.get(url, timeout=12, headers=HEADERS)
        if not r.ok: return items
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title","").strip()
            desc  = item.findtext("description","").strip()
            link  = item.findtext("link","").strip()
            pub   = item.findtext("pubDate", TODAY)[:16]
            if title:
                items.append({"title":title,"source":source,"category":category,
                              "date":pub,"url":link,"text":desc[:800]})
        if not items:
            for entry in root.findall(".//atom:entry",ns)[:max_items]:
                title = entry.findtext("atom:title","",ns).strip()
                le = entry.find("atom:link",ns)
                link = le.get("href","") if le is not None else ""
                summary = entry.findtext("atom:summary","",ns).strip()
                pub = entry.findtext("atom:updated",TODAY,ns)[:10]
                if title:
                    items.append({"title":title,"source":source,"category":category,
                                  "date":pub,"url":link,"text":summary[:800]})
    except Exception: pass
    return items

# ─── SOURCES ──────────────────────────────────────────────

def fetch_cnil():
    items = parse_rss("https://www.cnil.fr/fr/rss.xml","CNIL","rgpd",max_items=10)
    # Priorité aux délibérations et sanctions
    items.sort(key=lambda x: any(k in x["title"].lower() for k in
               ["sanction","délibération","mise en demeure","avertissement"]), reverse=True)
    return items

def fetch_edpb():
    return parse_rss("https://www.edpb.europa.eu/news/news_en.rss","EDPB","rgpd",max_items=6)

def fetch_linc():
    return parse_rss("https://linc.cnil.fr/fr/rss.xml","LINC (CNIL)","rgpd",max_items=4)

def fetch_village_justice():
    items = []
    for rub, cat in [("431","rgpd"),("","ai"),("","legis")]:
        url = f"https://www.village-justice.com/articles/spip.php?page=backend{'&rubrique='+rub if rub else ''}"
        items += parse_rss(url,"Village de la Justice",cat,max_items=6)
    return items

def fetch_legalis():
    items = parse_rss("https://www.legalis.net/feed/","Legalis.net","juris",max_items=8)
    for slug, cat in [("vie-privee","rgpd"),("responsabilite","dsa")]:
        items += parse_rss(f"https://www.legalis.net/jurisprudences/{slug}/feed/",
                           "Legalis.net", cat, max_items=4)
    return items

def fetch_donneespersonnelles():
    items = []
    for url, cat in [
        ("https://www.donneespersonnelles.fr/actualite-rgpd-2026","rgpd"),
        ("https://www.donneespersonnelles.fr/actualite-ia-2026","ai"),
    ]:
        try:
            r = requests.get(url, timeout=10, headers=HEADERS)
            if not r.ok: continue
            from html.parser import HTMLParser
            class P(HTMLParser):
                def __init__(self): super().__init__(); self.items=[]; self._in=False; self._cur=None
                def handle_starttag(self,tag,attrs):
                    if tag=="a":
                        d=dict(attrs)
                        href=d.get("href","")
                        if "donneespersonnelles.fr" in href and len(href)>45:
                            self._in=True; self._cur={"url":href,"text":""}
                def handle_endtag(self,tag):
                    if tag=="a" and self._in:
                        self._in=False
                        if self._cur and len(self._cur.get("text","").strip())>15:
                            self.items.append(self._cur); self._cur=None
                def handle_data(self,data):
                    if self._in and self._cur: self._cur["text"]+=data
            p=P(); p.feed(r.text)
            for it in p.items[:5]:
                t=it["text"].strip()
                if t: items.append({"title":t,"source":"donneespersonnelles.fr",
                                    "category":cat,"date":TODAY,"url":it["url"],"text":t})
        except Exception: pass
    return items

def fetch_eurlex():
    items = []
    for query, cat in [("AI Act regulation","ai"),("GDPR data protection","rgpd"),
                        ("Digital Services Act","dsa"),("health data space","sante")]:
        try:
            r = requests.get("https://publications.europa.eu/webapi/rdf/sparql",
                params={"query":f"""SELECT ?title ?date ?url WHERE {{
                  ?doc <http://purl.org/dc/elements/1.1/title> ?title .
                  ?doc <http://purl.org/dc/elements/1.1/date> ?date .
                  OPTIONAL {{?doc <http://www.w3.org/2002/07/owl#sameAs> ?url}}
                  FILTER(lang(?title)="fr"||lang(?title)="en")
                  FILTER(contains(lcase(str(?title)),lcase("{query.split()[0]}")))
                  FILTER(?date>="{DATE_FROM}"^^<http://www.w3.org/2001/XMLSchema#date>)
                }} LIMIT 3""","format":"application/sparql-results+json"},timeout=15)
            if r.ok:
                for b in r.json().get("results",{}).get("bindings",[]):
                    items.append({"title":b.get("title",{}).get("value",""),
                                  "source":"EUR-Lex","category":cat,
                                  "date":b.get("date",{}).get("value",TODAY)[:10],
                                  "url":b.get("url",{}).get("value",""),
                                  "text":b.get("title",{}).get("value","")})
        except Exception: pass
    return items

def fetch_judilibre():
    items = []
    if not PISTE_KEY or PISTE_KEY=="vide": return items
    for query in ["données personnelles RGPD","droit à l'oubli numérique","données de santé"]:
        try:
            r = requests.get("https://api.piste.gouv.fr/cassation/judilibre/v1.0/search",
                             headers={"KeyId":PISTE_KEY},
                             params={"query":query,"date_start":DATE_FROM,"page_size":3},
                             timeout=15)
            if r.ok:
                for item in r.json().get("results",[]):
                    items.append({
                        "title": item.get("titre","Arrêt Cour de cassation"),
                        "source":"Cour de cassation","category":"juris",
                        "date":item.get("decision_date",TODAY)[:10],
                        "url":f"https://www.courdecassation.fr/decision/{item.get('id','')}",
                        "text":item.get("sommaire","")[:1000],
                        "legifrance_id": item.get("id",""),
                        "is_jurisprudence": True
                    })
        except Exception: pass
    return items

def fetch_legifrance_decision(decision_id):
    """Récupère le texte complet d'une décision via PISTE/Légifrance."""
    if not PISTE_KEY or PISTE_KEY=="vide" or not decision_id: return ""
    try:
        r = requests.get(
            f"https://api.piste.gouv.fr/cassation/judilibre/v1.0/decision?id={decision_id}",
            headers={"KeyId":PISTE_KEY}, timeout=15)
        if r.ok:
            data = r.json()
            return data.get("text","")[:3000] or data.get("sommaire","")[:2000]
    except Exception: pass
    return ""

def fetch_arcom():
    return parse_rss("https://www.arcom.fr/feed","ARCOM","dsa",max_items=4)

def fetch_senat():
    items = parse_rss("https://www.senat.fr/rss/rss_actualites.xml","Sénat","legis",max_items=8)
    return [i for i in items if any(k.lower() in (i["title"]+i["text"]).lower()
            for k in ["numérique","données","IA","RGPD","cyber","AI Act","DSA","santé","plateforme"])]

def collect_all():
    all_items = []
    sources = [
        ("CNIL", fetch_cnil),
        ("EDPB", fetch_edpb),
        ("LINC", fetch_linc),
        ("Village de la Justice", fetch_village_justice),
        ("Legalis", fetch_legalis),
        ("donneespersonnelles.fr", fetch_donneespersonnelles),
        ("EUR-Lex", fetch_eurlex),
        ("Judilibre", fetch_judilibre),
        ("ARCOM", fetch_arcom),
        ("Sénat", fetch_senat),
    ]
    for name, fn in sources:
        print(f"   → {name}...")
        try:
            items = fn()
            filtered = [i for i in items if is_relevant(i)]
            print(f"      {len(filtered)}/{len(items)} pertinents")
            all_items += filtered
        except Exception as e:
            print(f"      ❌ {e}")
    seen = set()
    unique = []
    for it in all_items:
        k = it["title"][:60].lower().strip()
        if k not in seen and len(it["title"])>10:
            seen.add(k); unique.append(it)
    return unique

# ─── HAL ──────────────────────────────────────────────────

def search_hal(query, max_results=3):
    try:
        r = requests.get("https://api.archives-ouvertes.fr/search/",
            params={"q":query,"fl":"title_s,uri_s,authFullName_s,producedDate_tdate",
                    "rows":max_results,"sort":"producedDate_tdate desc",
                    "fq":"docType_s:ART OR docType_s:REPORT"},timeout=10)
        if r.ok:
            return [{"title":d.get("title_s",[""])[0],"url":d.get("uri_s",""),
                     "authors":", ".join(d.get("authFullName_s",[])[:2]),
                     "date":d.get("producedDate_tdate","")[:4]}
                    for d in r.json().get("response",{}).get("docs",[]) if d.get("uri_s")]
    except Exception: pass
    return []

# ─── MISTRAL ──────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es juriste expert en droit du numérique français et européen, spécialisé RGPD, données de santé, AI Act, DSA.
Ton style : précis, direct, juridique. Phrases courtes. Termes techniques exacts.
INTERDIT : "il convient de noter", "force est de constater", "à cet égard", "il y a lieu de", "dans ce contexte", "il importe de souligner", "notons que", "on peut observer".
Chaque phrase = une information concrète. Pas de remplissage."""

def mistral(prompt, system=SYSTEM_PROMPT):
    r = requests.post("https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization":f"Bearer {MISTRAL_KEY}","Content-Type":"application/json"},
        json={"model":"mistral-small-latest","messages":[
            {"role":"system","content":system},
            {"role":"user","content":prompt}
        ]},timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def parse_json_response(raw):
    raw = raw.strip()
    raw = re.sub(r'^```json\s*','',raw); raw = re.sub(r'^```\s*','',raw)
    raw = re.sub(r'\s*```$','',raw).strip()
    return json.loads(raw)

# ─── FICHE D'ARRÊT ────────────────────────────────────────

def make_fiche_arret(item):
    # Tenter de récupérer la décision complète sur Légifrance
    full_text = ""
    legifrance_url = item.get("url","")
    if item.get("legifrance_id"):
        full_text = fetch_legifrance_decision(item["legifrance_id"])
        print(f"      Légifrance : {len(full_text)} caractères récupérés")

    hal = search_hal(item["title"][:60])

    prompt = f"""Décision : "{item['title']}"
Juridiction : {item['source']} | Date : {item.get('date','')}
URL officielle : {legifrance_url}
Texte intégral/sommaire : {full_text or item.get('text','')[:1500]}

Génère une fiche d'arrêt JSON complète (UNIQUEMENT le JSON, sans backticks) :
{{
  "title": "titre reformulé précis avec juridiction et date",
  "juridiction": "juridiction exacte",
  "date": "{item.get('date','')}",
  "reference": "référence de la décision si disponible (numéro de pourvoi, etc.)",
  "contexte": "2 phrases : domaine juridique concerné et cadre réglementaire applicable",
  "faits": "3-4 phrases : faits de l'espèce de façon précise et chronologique",
  "procedure": "2 phrases : déroulement procédural, juridictions saisies, prétentions des parties ou moyen du pourvoi",
  "probleme_droit": "question juridique précise sous forme interrogative",
  "solution": "3-4 phrases : solution retenue, fondement juridique exact, articles cités",
  "portee": "2-3 phrases : apport doctrinal, règle dégagée, impact pratique pour les DPO/juristes conformité",
  "articles_cites": ["liste des textes cités : ex. art. 9 RGPD, art. L.1110-4 CSP"],
  "mots_cles": ["3-5 mots-clés juridiques"],
  "ressources_hal": {json.dumps(hal[:2], ensure_ascii=False)},
  "legifrance_url": "{legifrance_url}",
  "impact": "élevé / modéré / faible",
  "impact_level": "high / med / low"
}}"""
    try:
        data = parse_json_response(mistral(prompt))
        data.update({"type":"arret","category":"juris","category_label":"Jurisprudence",
                     "source":item["source"],"url":legifrance_url or item.get("url","")})
        return data
    except Exception:
        return {"title":item["title"],"type":"arret","category":"juris","category_label":"Jurisprudence",
                "juridiction":item["source"],"date":item.get("date",""),"reference":"",
                "contexte":item.get("text","")[:300],"faits":"","procedure":"","probleme_droit":"",
                "solution":"","portee":"","articles_cites":[],"mots_cles":[],"ressources_hal":hal[:2],
                "legifrance_url":legifrance_url,"source":item["source"],"url":item.get("url",""),
                "impact":"modéré","impact_level":"med"}

# ─── ARTICLE ENRICHI ──────────────────────────────────────

def enrich_article(item):
    if item.get("category") == "juris" or item.get("is_jurisprudence"):
        return make_fiche_arret(item)

    hal = search_hal(item["title"][:60])
    hal_ctx = "\n".join(f"[{i+1}] {h['title']} — {h['authors']} ({h['date']}) {h['url']}"
                        for i,h in enumerate(hal)) if hal else ""

    prompt = f"""Actualité : "{item['title']}"
Source : {item['source']} | Catégorie : {item.get('category','')}
Texte : {item.get('text','')[:600]}
{f"Sources HAL disponibles :{chr(10)}{hal_ctx}" if hal_ctx else ""}

JSON (UNIQUEMENT le JSON, sans backticks) :
{{
  "title": "titre précis reformulé",
  "type": "article",
  "summary": "2 phrases factuelles : ce qui s'est passé, qui, quoi",
  "analysis": "2-3 phrases d'analyse juridique : texte applicable, enjeu, portée",
  "portee": "1-2 phrases : impact concret pour juristes conformité et DPO",
  "articles_cites": ["textes juridiques applicables"],
  "mots_cles": ["3-5 mots-clés juridiques"],
  "ressources_hal": {json.dumps(hal[:2], ensure_ascii=False)},
  "impact": "élevé / modéré / faible",
  "impact_level": "high / med / low",
  "category": "{item.get('category','rgpd')}",
  "category_label": "{CATEGORY_MAP.get(item.get('category','rgpd'),'RGPD')}",
  "date": "{item.get('date',TODAY)}",
  "source": "{item['source']}",
  "url": "{item.get('url','')}"
}}"""
    try:
        data = parse_json_response(mistral(prompt))
        return data
    except Exception:
        return {"title":item["title"],"type":"article","summary":item.get("text","")[:200],
                "analysis":"","portee":"","articles_cites":[],"mots_cles":[],"ressources_hal":hal[:2],
                "impact":"modéré","impact_level":"med","category":item.get("category","rgpd"),
                "category_label":CATEGORY_MAP.get(item.get("category","rgpd"),"RGPD"),
                "date":item.get("date",TODAY),"source":item["source"],"url":item.get("url","")}

# ─── NOTE HEBDOMADAIRE ────────────────────────────────────

def generate_note_hebdo(articles):
    week_label = f"{WEEK_START} au {TODAY}"

    # Jurisprudences et délibérations en priorité
    juris = [a for a in articles if a.get("category")=="juris"]
    rgpd  = [a for a in articles if a.get("category")=="rgpd"]
    sante = [a for a in articles if a.get("category")=="sante"]
    ai    = [a for a in articles if a.get("category")=="ai"]
    legis = [a for a in articles if a.get("category") in ("legis","dsa")]

    digest = "\n".join(f"[{a.get('category_label','')}] {a['title']}" for a in articles[:25])

    # Sources HAL pour notes de bas de page
    hal_doctrine = search_hal("RGPD données personnelles santé jurisprudence 2025", max_results=5)
    hal_refs = "\n".join(f"[{i+1}] {h['title']} — {h['authors']} ({h['date']}) — {h['url']}"
                         for i,h in enumerate(hal_doctrine))

    prompt = f"""Semaine du {week_label}.
Actualités collectées (UNIQUEMENT droit du numérique — exclure tout ce qui n'est pas numérique/données/IA) :
{digest}

Sources doctrinales HAL disponibles pour notes de bas de page :
{hal_refs}

Rédige une NOTE JURIDIQUE HEBDOMADAIRE formalisée (700-900 mots) en HTML.

Structure OBLIGATOIRE :
<h3>I. Jurisprudence et décisions des autorités</h3>
→ Délibérations CNIL, arrêts CJUE, Cour de cassation, Conseil d'État sur RGPD/données

<h3>II. Données de santé et recherche</h3>
→ MR, AIPD, HDS, SNDS, EDS, échantillons biologiques, EHDS

<h3>III. Intelligence artificielle et régulation</h3>
→ AI Act, lignes directrices, obligations de transparence

<h3>IV. Plateformes et droit des contenus</h3>
→ DSA, DMA, responsabilité, modération (si actualité significative)

<h3>V. À surveiller</h3>
→ 3 points concrets pour la semaine prochaine

Règles rédactionnelles ABSOLUES :
- Zéro phrase creuse. Chaque phrase = fait juridique précis + fondement textuel.
- Employer les termes exacts : "au sens de l'art. X du RGPD", "en application de l'art. Y AI Act".
- Si tu cites une source HAL : <sup><a href="URL" target="_blank">[n]</a></sup>
- Balises : <h3> pour sections, <p> pour texte, <strong> pour termes clés.
- Terminer par : <div class="footnotes"><ol><li>références HAL citées</li></ol></div>
- NE PAS inclure de sujets hors droit du numérique (huissiers, dénigrement commercial, etc.)"""

    try:
        full = mistral(prompt)
        intro_prompt = f"""En 2-3 phrases directes, résume la tendance dominante de la semaine {week_label} en droit du numérique. Pas de formules creuses. Actualités : {digest[:600]}"""
        intro = mistral(intro_prompt)
        tags = []
        if juris: tags.append("Jurisprudence")
        if sante: tags.append("Données de santé")
        if ai: tags.append("AI Act")
        if rgpd: tags.append("RGPD")
        return {"title":f"Note de veille — Droit du numérique — Semaine du {WEEK_START}",
                "week":week_label,"intro":f"<p>{intro}</p>","full_content":full,
                "tags":tags[:4],"hal_sources":hal_doctrine}
    except Exception:
        return {"title":"Note hebdomadaire","week":week_label,
                "intro":"<p>Note en cours de génération.</p>",
                "full_content":"<p>Contenu indisponible.</p>","tags":["RGPD"],"hal_sources":[]}

def generate_suggestions(articles):
    juris = [a for a in articles if a.get("category")=="juris"]
    top = juris[0]["title"][:40] if juris else articles[0]["title"][:40] if articles else "RGPD"
    return [
        f"Fiche d'arrêt : {top}…",
        "Résume les délibérations CNIL de la semaine",
        "Quelles obligations AI Act s'appliquent en août 2026 ?",
        "Impact des nouvelles MR sur la recherche en santé",
    ]

def compute_stats(articles):
    from collections import Counter
    cats = Counter(a["category"] for a in articles)
    return {"total":len(articles),"rgpd":cats.get("rgpd",0),"ai":cats.get("ai",0),
            "sante":cats.get("sante",0),"juris":cats.get("juris",0),
            "legis":cats.get("legis",0)+cats.get("dsa",0)+cats.get("cyber",0)}

def merge_with_existing(new_articles):
    if not DATA_FILE.exists(): return new_articles
    try:
        old = json.loads(DATA_FILE.read_text()).get("articles",[])
        seen = set(a["title"][:60].lower() for a in new_articles)
        for a in old:
            if a["title"][:60].lower() not in seen: new_articles.append(a)
        return new_articles[:100]
    except Exception: return new_articles

# ─── EMAIL ────────────────────────────────────────────────

def send_email_digest(note, articles):
    if not GMAIL_USER or not GMAIL_PASS: return
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    juris = [a for a in articles if a.get("category")=="juris"][:3]
    top   = [a for a in articles if a.get("category")!="juris"][:4]
    juris_html = "".join(f"<li>⚖️ <strong>{a['title']}</strong></li>" for a in juris)
    top_html   = "".join(f"<li>[{a.get('category_label','')}] {a['title']}</li>" for a in top)
    html = f"""<html><body style="font-family:Georgia,serif;max-width:700px;margin:auto;color:#1a1a1a;background:#f8f7f4">
    <div style="background:#1a1a2e;padding:24px 32px">
      <div style="font-size:24px;font-weight:900;color:#fff;letter-spacing:-1px">LexPulse</div>
      <div style="font-size:13px;color:#8899bb;margin-top:4px">Veille droit du numérique — {TODAY}</div>
    </div>
    <div style="padding:24px 32px;background:#fff;border-bottom:3px solid #e63946">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#e63946;margin-bottom:8px">Note de la semaine</div>
      <h2 style="font-size:20px;margin:0 0 12px;line-height:1.3">{note['title']}</h2>
      <div style="font-size:14px;line-height:1.7;color:#333">{note['intro']}</div>
    </div>
    <div style="padding:20px 32px;background:#fff;margin-top:2px">
      {f'<div style="margin-bottom:16px"><div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#854f0b;margin-bottom:8px">Jurisprudence</div><ul style="font-size:13px;line-height:1.8;padding-left:20px">{juris_html}</ul></div>' if juris_html else ''}
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#2d4a8a;margin-bottom:8px">Actualités</div>
      <ul style="font-size:13px;line-height:1.8;padding-left:20px">{top_html}</ul>
    </div>
    </body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"LexPulse — Veille droit du numérique {TODAY}"
    msg["From"] = GMAIL_USER; msg["To"] = GMAIL_TO
    msg.attach(MIMEText(html,"html"))
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(GMAIL_USER,GMAIL_PASS)
        s.sendmail(GMAIL_USER,GMAIL_TO,msg.as_string())
    print(f"✅ Email envoyé à {GMAIL_TO}")

# ─── MAIN ─────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv)>1 else "--full"
    if mode == "--email-only":
        if DATA_FILE.exists():
            data = json.loads(DATA_FILE.read_text())
            send_email_digest(data["note_hebdo"],data["articles"])
        sys.exit(0)

    print(f"🔍 Collecte {'complète depuis avril 2025' if is_first_run else 'hebdomadaire'}...")
    raw = collect_all()
    print(f"   → {len(raw)} éléments pertinents")

    print("🤖 Enrichissement...")
    articles = []
    for i,item in enumerate(raw[:25]):
        t = item['title'][:55]
        print(f"   {i+1}/{min(len(raw),25)} — {t}")
        articles.append(enrich_article(item))

    print("📝 Note hebdomadaire...")
    note = generate_note_hebdo(articles)
    suggestions = generate_suggestions(articles)

    print("🔀 Fusion...")
    articles = merge_with_existing(articles)

    output = {"generated_at":datetime.datetime.utcnow().isoformat()+"Z",
              "note_hebdo":note,"articles":articles,
              "stats":compute_stats(articles),"suggestions":suggestions}

    Path("data").mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(f"✅ veille.json ({len(articles)} articles)")

    if mode != "--no-email":
        send_email_digest(note,articles)
    print("✅ Terminé !")
