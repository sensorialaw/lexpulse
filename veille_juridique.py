"""
LexPulse v3 — Agent de veille juridique
Fiches d'arrêt structurées, filtrage thématique strict, enrichissement HAL
"""
import os, json, datetime, requests, sys
from pathlib import Path

MISTRAL_KEY = os.environ["MISTRAL_API_KEY"]
TODAY = datetime.date.today().isoformat()
WEEK_START = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
SINCE_APRIL = "2025-04-01"

DATA_FILE = Path("data/veille.json")
is_first_run = not DATA_FILE.exists()
DATE_FROM = SINCE_APRIL if is_first_run else WEEK_START

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASS", "")
GMAIL_TO   = os.environ.get("GMAIL_RECIPIENT", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LexPulse/1.0)"}

CATEGORY_MAP = {
    "rgpd": "RGPD",
    "ai": "AI Act",
    "sante": "Santé",
    "juris": "Jurisprudence",
    "legis": "Législation",
    "dsa": "DSA",
    "cyber": "Cybersécurité",
}

# Mots-clés stricts — tout article ne contenant aucun de ces mots est écarté
STRICT_KEYWORDS = [
    "RGPD", "données personnelles", "données de santé", "protection des données",
    "AI Act", "intelligence artificielle", "algorithme", "modèle d'IA", "système d'IA",
    "DSA", "DMA", "plateforme", "hébergeur", "éditeur", "modération",
    "CNIL", "EDPB", "DPO", "délégué à la protection",
    "cybersécurité", "NIS2", "ANSSI", "violation de données", "fuite de données",
    "HDS", "SNDS", "données de santé", "entrepôt de données", "recherche en santé",
    "droit au déréférencement", "droit à l'oubli", "consentement",
    "cookies", "traceurs", "profilage", "transfert de données",
    "vie privée numérique", "surveillance numérique", "reconnaissance faciale",
    "blockchain", "crypto", "MiCA", "actifs numériques",
    "CJUE", "Cour de justice", "Commission européenne numérique",
    "Conseil d'État numérique", "Cour de cassation données",
]

def is_relevant(item):
    text = (item.get("title","") + " " + item.get("text","")).lower()
    return any(kw.lower() in text for kw in STRICT_KEYWORDS)

# ─── PARSING RSS ──────────────────────────────────────────

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
                              "date":pub,"url":link,"text":desc[:600]})
        if not items:
            for entry in root.findall(".//atom:entry",ns)[:max_items]:
                title = entry.findtext("atom:title","",ns).strip()
                link_el = entry.find("atom:link",ns)
                link = link_el.get("href","") if link_el is not None else ""
                summary = entry.findtext("atom:summary","",ns).strip()
                pub = entry.findtext("atom:updated",TODAY,ns)[:10]
                if title:
                    items.append({"title":title,"source":source,"category":category,
                                  "date":pub,"url":link,"text":summary[:600]})
    except Exception:
        pass
    return items

# ─── SOURCES ──────────────────────────────────────────────

def fetch_cnil_news():
    return parse_rss("https://www.cnil.fr/fr/rss.xml", "CNIL", "rgpd", max_items=8)

def fetch_edpb():
    return parse_rss("https://www.edpb.europa.eu/news/news_en.rss", "EDPB", "rgpd", max_items=5)

def fetch_anssi():
    items = parse_rss("https://www.cert.ssi.gouv.fr/feed/", "ANSSI/CERT-FR", "cyber", max_items=5)
    # Filtrer : garder uniquement alertes critiques liées aux données
    return [i for i in items if any(k in i["title"].lower() for k in ["données","rgpd","violation","fuite","ransomware","santé"])]

def fetch_linc():
    return parse_rss("https://linc.cnil.fr/fr/rss.xml", "LINC (CNIL)", "rgpd", max_items=4)

def fetch_village_justice():
    items = parse_rss("https://www.village-justice.com/articles/spip.php?page=backend&rubrique=431",
                      "Village de la Justice", "rgpd", max_items=8)
    items += parse_rss("https://www.village-justice.com/articles/spip.php?page=backend",
                       "Village de la Justice", "legis", max_items=6)
    return items

def fetch_legalis():
    items = parse_rss("https://www.legalis.net/feed/", "Legalis.net", "juris", max_items=8)
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
                        if "donneespersonnelles.fr" in d.get("href","") and len(d.get("href",""))>40:
                            self._in=True; self._cur={"url":d["href"],"text":""}
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
                if t: items.append({"title":t,"source":"donneespersonnelles.fr","category":cat,"date":TODAY,"url":it["url"],"text":t})
        except Exception: pass
    return items

def fetch_eurlex_recent():
    items = []
    for query, cat in [("AI Act regulation","ai"),("GDPR data protection","rgpd"),("Digital Services Act","dsa")]:
        try:
            r = requests.get(
                "https://publications.europa.eu/webapi/rdf/sparql",
                params={"query":f"""SELECT ?title ?date ?url WHERE {{
                  ?doc <http://purl.org/dc/elements/1.1/title> ?title .
                  ?doc <http://purl.org/dc/elements/1.1/date> ?date .
                  OPTIONAL {{ ?doc <http://www.w3.org/2002/07/owl#sameAs> ?url }}
                  FILTER(lang(?title)="fr"||lang(?title)="en")
                  FILTER(contains(lcase(str(?title)),lcase("{query.split()[0]}")))
                  FILTER(?date>="{DATE_FROM}"^^<http://www.w3.org/2001/XMLSchema#date>)
                }} LIMIT 3""","format":"application/sparql-results+json"},timeout=15)
            if r.ok:
                for b in r.json().get("results",{}).get("bindings",[]):
                    items.append({"title":b.get("title",{}).get("value",""),"source":"EUR-Lex","category":cat,
                                  "date":b.get("date",{}).get("value",TODAY)[:10],
                                  "url":b.get("url",{}).get("value",""),"text":b.get("title",{}).get("value","")})
        except Exception: pass
    return items

def fetch_judilibre():
    items = []
    piste_key = os.environ.get("PISTE_API_KEY","")
    if not piste_key or piste_key=="vide": return items
    try:
        r = requests.get("https://api.piste.gouv.fr/cassation/judilibre/v1.0/search",
                         headers={"KeyId":piste_key},
                         params={"query":"données personnelles RGPD","date_start":DATE_FROM,"page_size":5},
                         timeout=15)
        if r.ok:
            for item in r.json().get("results",[]):
                items.append({"title":item.get("titre","Arrêt Cour de cassation"),
                              "source":"Cour de cassation","category":"juris",
                              "date":item.get("decision_date",TODAY)[:10],
                              "url":f"https://www.courdecassation.fr/decision/{item.get('id','')}",
                              "text":item.get("sommaire","")[:800]})
    except Exception: pass
    return items

def fetch_arcom():
    return parse_rss("https://www.arcom.fr/feed","ARCOM","dsa",max_items=4)

def fetch_senat():
    items = parse_rss("https://www.senat.fr/rss/rss_actualites.xml","Sénat","legis",max_items=6)
    return [i for i in items if any(k.lower() in (i["title"]+i["text"]).lower()
            for k in ["numérique","données","IA","RGPD","cyber","AI Act","DSA","plateforme"])]

def collect_all():
    all_items = []
    sources = [
        ("CNIL", fetch_cnil_news),
        ("EDPB", fetch_edpb),
        ("LINC", fetch_linc),
        ("Village de la Justice", fetch_village_justice),
        ("Legalis", fetch_legalis),
        ("donneespersonnelles.fr", fetch_donneespersonnelles),
        ("EUR-Lex", fetch_eurlex_recent),
        ("Judilibre", fetch_judilibre),
        ("ARCOM", fetch_arcom),
        ("Sénat", fetch_senat),
        ("ANSSI", fetch_anssi),
    ]
    for name, fn in sources:
        print(f"   → {name}...")
        try:
            items = fn()
            filtered = [i for i in items if is_relevant(i)]
            print(f"      {len(filtered)}/{len(items)} pertinents")
            all_items += filtered
        except Exception as e:
            print(f"      ❌ Erreur : {e}")

    seen = set()
    unique = []
    for it in all_items:
        k = it["title"][:60].lower().strip()
        if k not in seen and len(it["title"])>10:
            seen.add(k); unique.append(it)
    return unique

# ─── RECHERCHE HAL ────────────────────────────────────────

def search_hal(query, max_results=3):
    """Cherche des articles académiques sur HAL en lien avec le sujet."""
    try:
        r = requests.get(
            "https://api.archives-ouvertes.fr/search/",
            params={"q":query,"fl":"title_s,uri_s,authFullName_s,producedDate_tdate,abstract_s",
                    "rows":max_results,"sort":"producedDate_tdate desc","fq":"docType_s:ART OR docType_s:REPORT"},
            timeout=10
        )
        if r.ok:
            docs = r.json().get("response",{}).get("docs",[])
            return [{"title":d.get("title_s",[""])[0],
                     "url":d.get("uri_s",""),
                     "authors":", ".join(d.get("authFullName_s",[])[:2]),
                     "date":d.get("producedDate_tdate","")[:4]} for d in docs if d.get("uri_s")]
    except Exception: pass
    return []

# ─── MISTRAL ──────────────────────────────────────────────

def mistral(prompt, system="""Tu es juriste expert en droit du numérique français et européen.
Tu écris en français direct et précis, comme tu parlerais à un collègue juriste.
Phrases courtes. Pas de formules creuses : jamais "il convient de noter", "force est de constater", "à cet égard", "il y a lieu de", "dans ce contexte".
Va droit au but : ce qui s'est passé, pourquoi c'est important, ce que ça change."""):
    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization":f"Bearer {MISTRAL_KEY}","Content-Type":"application/json"},
        json={"model":"mistral-small-latest","messages":[
            {"role":"system","content":system},
            {"role":"user","content":prompt}
        ]},timeout=45)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ─── FICHE D'ARRÊT ────────────────────────────────────────

def make_fiche_arret(item):
    """Génère une fiche d'arrêt structurée pour les décisions de jurisprudence."""
    hal_results = search_hal(item["title"][:60])
    hal_context = ""
    if hal_results:
        hal_context = "Sources académiques disponibles sur HAL :\n" + "\n".join(
            f"- {h['title']} ({h['authors']}, {h['date']}) — {h['url']}" for h in hal_results)

    prompt = f"""Décision : "{item['title']}"
Source : {item['source']} | Date : {item.get('date','')}
Texte : {item.get('text','')[:800]}
{hal_context}

Génère une fiche d'arrêt en JSON (UNIQUEMENT le JSON, sans backticks) :
{{
  "title": "titre reformulé précis",
  "juridiction": "nom de la juridiction",
  "date": "{item.get('date','')}",
  "contexte": "2 phrases : domaine juridique et enjeu général",
  "faits": "2-3 phrases : ce qui s'est passé concrètement",
  "procedure": "1-2 phrases : déroulement procédural et prétentions des parties",
  "probleme_droit": "1 phrase sous forme de question juridique précise",
  "solution": "2-3 phrases : ce qu'a décidé la juridiction et sur quel fondement (articles cités)",
  "portee": "2-3 phrases : ce que ça change, quelle règle ça fixe, qui est concerné",
  "articles_cites": ["liste des articles de loi ou règlements mentionnés"],
  "ressources_hal": {json.dumps(hal_results[:2], ensure_ascii=False)},
  "category": "juris",
  "category_label": "Jurisprudence",
  "source": "{item['source']}",
  "url": "{item.get('url','')}",
  "impact": "élevé / modéré / faible",
  "impact_level": "high / med / low"
}}"""
    try:
        raw = mistral(prompt).strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(raw)
        data["type"] = "arret"
        return data
    except Exception:
        return {
            "title":item["title"],"type":"arret","juridiction":item["source"],
            "date":item.get("date",""),"contexte":item.get("text","")[:300],
            "faits":"","procedure":"","probleme_droit":"","solution":"",
            "portee":"","articles_cites":[],"ressources_hal":[],
            "category":"juris","category_label":"Jurisprudence",
            "source":item["source"],"url":item.get("url",""),
            "impact":"modéré","impact_level":"med"
        }

# ─── ARTICLE ENRICHI ──────────────────────────────────────

def enrich_article(item):
    if item.get("category") == "juris":
        return make_fiche_arret(item)

    hal_results = search_hal(item["title"][:60])
    hal_context = ""
    if hal_results:
        hal_context = "\nSources HAL disponibles :\n" + "\n".join(
            f"- {h['title']} ({h['authors']}, {h['date']}) — {h['url']}" for h in hal_results)

    prompt = f"""Actualité : "{item['title']}"
Source : {item['source']} | Catégorie : {item.get('category','')}
Texte : {item.get('text','')[:500]}
{hal_context}

Génère un JSON (UNIQUEMENT le JSON, sans backticks) :
{{
  "title": "titre reformulé clair",
  "type": "article",
  "summary": "2 phrases : ce qui s'est passé exactement",
  "analysis": "2-3 phrases d'analyse juridique concrète (enjeu, portée, qui est concerné)",
  "portee": "1-2 phrases : ce que ça change concrètement pour les praticiens",
  "articles_cites": ["textes juridiques mentionnés si applicable"],
  "ressources_hal": {json.dumps(hal_results[:2], ensure_ascii=False)},
  "impact": "élevé / modéré / faible",
  "impact_level": "high / med / low",
  "category": "{item.get('category','rgpd')}",
  "category_label": "{CATEGORY_MAP.get(item.get('category','rgpd'),'RGPD')}",
  "date": "{item.get('date',TODAY)}",
  "source": "{item['source']}",
  "url": "{item.get('url','')}"
}}"""
    try:
        raw = mistral(prompt).strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(raw)
    except Exception:
        return {"title":item["title"],"type":"article","summary":item.get("text","")[:200],
                "analysis":"","portee":"","articles_cites":[],"ressources_hal":[],
                "impact":"modéré","impact_level":"med","category":item.get("category","rgpd"),
                "category_label":CATEGORY_MAP.get(item.get("category","rgpd"),"RGPD"),
                "date":item.get("date",TODAY),"source":item["source"],"url":item.get("url","")}

# ─── NOTE HEBDOMADAIRE ────────────────────────────────────

def generate_note_hebdo(articles):
    digest = "\n".join(f"- [{a.get('category_label','')}] {a['title']}" for a in articles[:20])
    week_label = f"{WEEK_START} au {TODAY}"

    # Cherche des sources doctrinales sur HAL pour enrichir la note
    hal_doctrine = search_hal("RGPD données personnelles intelligence artificielle 2025", max_results=4)
    hal_block = ""
    if hal_doctrine:
        hal_block = "Sources doctrinales disponibles :\n" + "\n".join(
            f"[{i+1}] {h['title']} — {h['authors']} ({h['date']}) — {h['url']}"
            for i,h in enumerate(hal_doctrine))

    prompt = f"""Semaine du {week_label}. Actualités collectées :
{digest}

{hal_block}

Rédige une note juridique hebdomadaire (600-700 mots) en HTML structuré.

Règles absolues :
- Zéro phrase creuse. Chaque phrase doit apporter une information concrète.
- Pas de "il convient", "force est de constater", "à cet égard", "dans ce contexte", "il y a lieu".
- Chaque point : fait précis + règle juridique applicable + conséquence pratique.
- Si tu cites une source HAL, utilise une note de bas de page : <sup><a href="URL">[n]</a></sup>
- Structure avec <h3> par thématique (3-4 max), <p> pour l'analyse.
- Termine par : "À surveiller la semaine prochaine" en 2-3 points concrets.

Format HTML avec notes de bas de page si sources citées :
<div class="footnotes"><ol><li id="fn1"><a href="URL">Titre — Auteur</a></li></ol></div>"""

    try:
        intro_raw = mistral(f"En 3 phrases directes (pas de formules creuses), quelle est la tendance dominante de la semaine du {week_label} en droit du numérique ? Actualités : {digest[:500]}")
        full = mistral(prompt)
        tags = list(set([a["category"] for a in articles[:5]]))[:3]
        return {
            "title": f"Veille droit du numérique — semaine du {WEEK_START}",
            "week": week_label,
            "intro": f"<p>{intro_raw}</p>",
            "full_content": full,
            "tags": [CATEGORY_MAP.get(t,t.upper()) for t in tags],
            "hal_sources": hal_doctrine
        }
    except Exception:
        return {"title":"Note hebdomadaire","week":week_label,
                "intro":"<p>Note en cours de génération.</p>",
                "full_content":"<p>Contenu indisponible.</p>","tags":["RGPD"],"hal_sources":[]}

def generate_suggestions(articles):
    titles = [a["title"] for a in articles[:4]]
    return [
        f"Explique : {titles[0][:45]}…" if titles else "Quoi de neuf en RGPD ?",
        "Quel est l'impact AI Act cette semaine ?",
        "Fais-moi une fiche sur la dernière décision CNIL",
        "Résume les évolutions en droit de la santé",
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
        existing = json.loads(DATA_FILE.read_text())
        old = existing.get("articles",[])
        seen = set(a["title"][:60].lower() for a in new_articles)
        for a in old:
            if a["title"][:60].lower() not in seen:
                new_articles.append(a)
        return new_articles[:100]
    except Exception: return new_articles

# ─── EMAIL ────────────────────────────────────────────────

def send_email_digest(note, articles):
    if not GMAIL_USER or not GMAIL_PASS: return
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    top5 = "".join(f"<li><strong>[{a.get('category_label','')}]</strong> {a['title']}</li>" for a in articles[:5])
    html = f"""<html><body style="font-family:Georgia,serif;max-width:680px;margin:auto;color:#1a1a1a">
    <div style="background:#2d4a8a;padding:20px 30px;border-radius:8px 8px 0 0">
      <h1 style="color:#fff;font-size:22px;margin:0">LexPulse</h1>
      <p style="color:#b0c0e0;font-size:13px;margin:4px 0 0">Veille droit du numérique — {TODAY}</p>
    </div>
    <div style="border:1px solid #e8e5df;border-top:none;padding:24px 30px;border-radius:0 0 8px 8px">
      <h2 style="font-size:18px;color:#2d4a8a">{note['title']}</h2>
      <div style="font-size:14px;line-height:1.7">{note['intro']}</div>
      <hr style="border:none;border-top:1px solid #e8e5df;margin:20px 0">
      <h3 style="font-size:13px;text-transform:uppercase;letter-spacing:1px;color:#6b6860">À retenir cette semaine</h3>
      <ul style="font-size:13px;line-height:1.8;padding-left:20px">{top5}</ul>
    </div></body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"LexPulse — Veille juridique {TODAY}"
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
    print(f"   → {len(raw)} éléments pertinents après filtrage")

    print("🤖 Enrichissement (articles + fiches d'arrêt)...")
    articles = []
    for i,item in enumerate(raw[:25]):
        print(f"   {i+1}/{min(len(raw),25)} — {item['title'][:55]}")
        articles.append(enrich_article(item))

    print("📝 Génération note hebdomadaire...")
    note = generate_note_hebdo(articles)
    suggestions = generate_suggestions(articles)

    print("🔀 Fusion données existantes...")
    articles = merge_with_existing(articles)

    output = {
        "generated_at": datetime.datetime.utcnow().isoformat()+"Z",
        "note_hebdo": note,
        "articles": articles,
        "stats": compute_stats(articles),
        "suggestions": suggestions
    }

    Path("data").mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(f"✅ veille.json généré ({len(articles)} articles)")

    if mode != "--no-email":
        send_email_digest(note,articles)
    print("✅ Terminé !")
