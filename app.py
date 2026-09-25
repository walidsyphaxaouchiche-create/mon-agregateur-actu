import os
import time
import requests
import feedparser
import trafilatura
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, unquote
from deep_translator import GoogleTranslator
from flask import Flask, render_template_string, request

app = Flask(__name__)

CATEGORIES = {
    "politique": {
        "name": "Politique & Géopolitique",
        "icon": "🌐",
        "feeds": {
            "Le Monde (Politique)": "https://www.lemonde.fr/politique/rss_full.xml",
            "BBC News (World)": "http://feeds.bbci.co.uk/news/world/rss.xml",
            "Courrier International": "https://www.courrierinternational.com/feed/category/690/rss.xml",
            "Le Figaro (International)": "https://www.lefigaro.fr/rss/figaro_international.xml"
        }
    },
    "economie": {
        "name": "Économie & Finance",
        "icon": "📈",
        "feeds": {
            "Les Échos": "https://www.lesechos.fr/rss/rss_une.xml",
            "La Tribune": "https://www.latribune.fr/feed/full.xml",
            "MarketWatch (Business)": "https://feeds.content.dowjones.io/public/rss/mw_topstories"
        }
    },
    "tech": {
        "name": "Technologies & IA",
        "icon": "💻",
        "feeds": {
            "The Verge": "https://www.theverge.com/rss/index.xml",
            "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
            "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
            "Clubic": "https://www.clubic.com/feed/news.rss",
            "Frandroid": "https://www.frandroid.com/feed",
            "L'Usine Digitale": "https://www.usine-digitale.fr/rss"
        }
    },
    "philosophie": {
        "name": "Philosophie & Pensée",
        "icon": "🧠",
        "feeds": {
            "Philosophie Magazine": "https://www.philomag.com/rss.xml",
            "Aeon Essays (En)": "https://aeon.co/feed.rss",
            "France Culture (Idées)": "https://www.radiofrance.fr/franceculture/rss"
        }
    },
    "cinema": {
        "name": "Cinéma & Séries",
        "icon": "🎬",
        "feeds": {
            "Variety (En)": "https://variety.com/feed/",
            "IndieWire (En)": "https://www.indiewire.com/feed/",
            "Première": "https://www.premiere.fr/rss/actus.xml",
            "Allociné": "https://www.allocine.fr/rss/news.xml"
        }
    },
    "anime": {
        "name": "Anime & Manga",
        "icon": "⛩️",
        "feeds": {
            "Anime News Network (En)": "https://www.animenewsnetwork.com/news/rss.xml",
            "Manga-News": "https://www.manga-news.com/index.php/feed/rss",
            "Sakuga Blog (En)": "https://blog.sakugabooru.com/feed/"
        }
    },
    "sciences": {
        "name": "Sciences & Environnement",
        "icon": "🔬",
        "feeds": {
            "Futura Sciences": "https://www.futura-sciences.com/rss/actualites.xml",
            "Reporterre": "https://reporterre.net/spip.php?page=backend",
            "Nature News": "https://www.nature.com/nature.rss"
        }
    },
    "sante": {
        "name": "Santé & Médecine",
        "icon": "🩺",
        "feeds": {
            "Inserm": "https://www.inserm.fr/feed/",
            "Futura Santé": "https://www.futura-sciences.com/rss/sante/actualites.xml"
        }
    },
    "sport": {
        "name": "Sport",
        "icon": "⚽",
        "feeds": {
            "L'Équipe": "https://www.lequipe.fr/rss/actu_rss.xml",
            "RMC Sport": "https://rmcsport.bfmtv.com/rss/fil-info/",
            "BBC Sport": "http://feeds.bbci.co.uk/sport/rss.xml"
        }
    },
    "culture": {
        "name": "Culture, Société & Médias",
        "icon": "🎭",
        "feeds": {
            "France Culture": "https://www.radiofrance.fr/franceculture/rss",
            "Télérama": "https://www.telerama.fr/rss/actu.xml",
            "Le Monde Diplomatique": "https://www.monde-diplomatique.fr/rss/"
        }
    }
}

COMMON_CSS = """
    :root {
        --bg-color: #f8fafc;
        --card-bg: #ffffff;
        --text-primary: #0f172a;
        --text-secondary: #64748b;
        --border-color: #e2e8f0;
        --accent-color: #2563eb;
    }
    @media (prefers-color-scheme: dark) {
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --border-color: #334155;
            --accent-color: #3b82f6;
        }
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { 
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
        background: var(--bg-color); 
        color: var(--text-primary); 
        max-width: 680px; 
        margin: 0 auto; 
        padding: 20px 16px 40px 16px;
        line-height: 1.5;
    }
    header { text-align: center; margin-bottom: 24px; padding-top: 10px; }
    header h1 { font-size: 2rem; font-weight: 800; letter-spacing: -0.5px; }
    header p { font-size: 0.85rem; color: var(--text-secondary); margin-top: 4px; text-transform: capitalize; }
    
    .category-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
        gap: 12px;
        margin-bottom: 30px;
    }
    .cat-card {
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 14px;
        border-radius: 14px;
        text-decoration: none;
        color: var(--text-primary);
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        transition: transform 0.15s ease;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .cat-card:active { transform: scale(0.97); }
    .cat-icon { font-size: 1.8rem; margin-bottom: 6px; }
    .cat-title { font-size: 0.88rem; font-weight: 600; line-height: 1.2; }

    .card { 
        background: var(--card-bg); 
        padding: 18px; 
        margin-bottom: 14px; 
        border-radius: 16px; 
        border: 1px solid var(--border-color);
        box-shadow: 0 2px 8px rgba(0,0,0,0.03); 
    }
    .card-meta { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
    .tag { font-size: 0.75rem; font-weight: 700; padding: 4px 10px; border-radius: 20px; background: rgba(37,99,235,0.1); color: var(--accent-color); }
    .date { font-size: 0.75rem; color: var(--text-secondary); }
    .card-title { font-size: 1.1rem; font-weight: 700; line-height: 1.4; margin-bottom: 14px; }
    .btn { 
        display: block; 
        text-align: center; 
        padding: 10px 14px; 
        background: var(--accent-color); 
        color: #ffffff; 
        text-decoration: none; 
        border-radius: 10px; 
        font-weight: 600; 
        font-size: 0.88rem; 
    }
    .btn-outline {
        display: inline-block;
        padding: 8px 14px;
        border: 1px solid var(--border-color);
        border-radius: 8px;
        color: var(--text-primary);
        text-decoration: none;
        font-size: 0.85rem;
        font-weight: 600;
        background: var(--card-bg);
    }
    .back { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 20px; color: var(--accent-color); text-decoration: none; font-weight: 600; font-size: 0.95rem; }
"""

def parse_and_filter_date(entry):
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time:
        dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if (now - dt) > timedelta(hours=48):
            return None, None
        formatted_date = dt.strftime("%d/%m/%Y à %H:%M")
        return dt, formatted_date
    return None, "Aujourd'hui"

def fetch_clean_article(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        text = trafilatura.extract(response.text, include_links=False, output_format="txt")
        return text or "Impossible d'extraire le texte brut de cet article."
    except Exception as e:
        return f"Erreur lors du chargement : {str(e)}"

def translate_text(text, target_lang):
    if not text or target_lang == "original":
        return text
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        paragraphs = text.split('\n')
        translated = []
        for p in paragraphs:
            if p.strip():
                if len(p) > 3500:
                    chunks = [p[i:i+3500] for i in range(0, len(p), 3500)]
                    translated.append("".join([translator.translate(c) for c in chunks]))
                else:
                    translated.append(translator.translate(p))
            else:
                translated.append("")
        return "\n".join(translated)
    except Exception:
        return text

@app.route("/")
def index():
    today = datetime.now().strftime("%A %d %B %Y")
    
    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>News info</title>
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <header>
            <h1>News info</h1>
            <p>{today}</p>
        </header>

        <h2 style="font-size: 1.1rem; margin-bottom: 12px; color: var(--text-secondary);">Choisissez un domaine :</h2>
        <div class="category-grid">
            {"".join([f'''
            <a class="cat-card" href="/category?cat={cat_key}">
                <div class="cat-icon">{cat['icon']}</div>
                <div class="cat-title">{cat['name']}</div>
            </a>
            ''' for cat_key, cat in CATEGORIES.items()])}
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/category")
def category():
    cat_key = request.args.get("cat")
    if not cat_key or cat_key not in CATEGORIES:
        return "Domaine introuvable.", 404
        
    cat_info = CATEGORIES[cat_key]
    articles = []
    
    for source_name, feed_url in cat_info["feeds"].items():
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                dt, formatted_date = parse_and_filter_date(entry)
                if formatted_date is None:
                    continue
                    
                articles.append({
                    "dt": dt or datetime.now(timezone.utc),
                    "title": entry.title,
                    "source": source_name,
                    "date": formatted_date,
                    "safe_url": quote(entry.link, safe=""),
                    "safe_title": quote(entry.title, safe="")
                })
        except Exception:
            continue

    articles.sort(key=lambda x: x["dt"], reverse=True)

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{cat_info['name']} - News info</title>
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <a class="back" href="/">&larr; Tous les domaines</a>
        <header style="text-align: left; margin-bottom: 20px;">
            <div style="font-size: 2.5rem; margin-bottom: 4px;">{cat_info['icon']}</div>
            <h1>{cat_info['name']}</h1>
            <p style="text-align:left;">Articles publiés ces dernières 48h</p>
        </header>

        <div class="articles-list">
            {"".join([f'''
            <div class="card">
                <div class="card-meta">
                    <span class="tag">{a['source']}</span>
                    <span class="date">{a['date']}</span>
                </div>
                <div class="card-title">{a['title']}</div>
                <a class="btn" href="/article?url={a['safe_url']}&title={a['safe_title']}&cat={cat_key}&lang=fr">Lire l'article nettoyé</a>
            </div>
            ''' for a in articles]) if articles else '<p style="color: var(--text-secondary);">Aucun article publié ces dernières 48 heures.</p>'}
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/article")
def article():
    raw_url = request.args.get("url")
    raw_title = request.args.get("title", "Article")
    cat_key = request.args.get("cat", "")
    target_lang = request.args.get("lang", "fr")
    
    if not raw_url:
        return "URL manquante.", 400
        
    target_url = unquote(raw_url)
    title = unquote(raw_title)
    
    raw_content = fetch_clean_article(target_url)
    translated_title = translate_text(title, target_lang)
    translated_content = translate_text(raw_content, target_lang)
    
    back_url = f"/category?cat={cat_key}" if cat_key else "/"
    
    btn_fr_class = "btn-lang active" if target_lang == "fr" else "btn-lang"
    btn_en_class = "btn-lang active" if target_lang == "en" else "btn-lang"
    
    html = f"""
    <!DOCTYPE html>
    <html lang="{target_lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{translated_title}</title>
        <style>
            {COMMON_CSS}
            body {{ background: var(--card-bg); }}
            .top-bar {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color); flex-wrap: wrap; gap: 10px; }}
            .lang-switch {{ display: flex; gap: 6px; }}
            .btn-lang {{ text-decoration: none; padding: 6px 12px; border-radius: 8px; font-size: 0.8rem; font-weight: 700; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-primary); }}
            .btn-lang.active {{ background: var(--accent-color); color: #fff; border-color: var(--accent-color); }}
            .font-btn {{ background: var(--bg-color); border: 1px solid var(--border-color); padding: 6px 12px; border-radius: 6px; color: var(--text-primary); cursor: pointer; font-weight: 700; }}
            article {{ font-size: 1.05rem; line-height: 1.8; color: var(--text-primary); margin-top: 20px; white-space: pre-line; }}
            h1 {{ font-size: 1.5rem; line-height: 1.35; margin-bottom: 12px; }}
            .actions {{ margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border-color); text-align: center; }}
        </style>
    </head>
    <body>
        <a class="back" href="{back_url}">&larr; Retour au flux</a>
        
        <div class="top-bar">
            <div class="lang-switch">
                <a class="{btn_fr_class}" href="/article?url={quote(raw_url, safe='')}&title={quote(raw_title, safe='')}&cat={cat_key}&lang=fr">🇫🇷 Français</a>
                <a class="{btn_en_class}" href="/article?url={quote(raw_url, safe='')}&title={quote(raw_title, safe='')}&cat={cat_key}&lang=en">🇬🇧 English</a>
            </div>
            <div>
                <button class="font-btn" onclick="adjustFont(-0.1)">A-</button>
                <button class="font-btn" onclick="adjustFont(0.1)">A+</button>
            </div>
        </div>

        <header style="text-align: left; padding-bottom: 12px;">
            <h1>{translated_title}</h1>
        </header>

        <article id="article-body">{translated_content}</article>

        <div class="actions">
            <a class="btn-outline" href="{target_url}" target="_blank" rel="noopener">Voir l'article original ↗</a>
        </div>

        <script>
            let currentSize = 1.05;
            function adjustFont(delta) {{
                currentSize = Math.max(0.85, Math.min(1.5, currentSize + delta));
                document.getElementById('article-body').style.fontSize = currentSize + 'rem';
            }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
