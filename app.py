import os
import requests
import feedparser
import trafilatura
from datetime import datetime
from urllib.parse import quote, unquote
from flask import Flask, render_template_string, request

app = Flask(__name__)

# Structure des Domaines et des Sources d'actualités
CATEGORIES = {
    "politique": {
        "name": "Politique & Géopolitique",
        "icon": "🌐",
        "color": "#3b82f6",
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
        "color": "#10b981",
        "feeds": {
            "Les Échos": "https://www.lesechos.fr/rss/rss_une.xml",
            "La Tribune": "https://www.latribune.fr/feed/full.xml",
            "MarketWatch (Business)": "https://feeds.content.dowjones.io/public/rss/mw_topstories"
        }
    },
    "tech": {
        "name": "Technologies & IA",
        "icon": "💻",
        "color": "#8b5cf6",
        "feeds": {
            "The Verge": "https://www.theverge.com/rss/index.xml",
            "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
            "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
            "Clubic": "https://www.clubic.com/feed/news.rss",
            "Frandroid": "https://www.frandroid.com/feed",
            "L'Usine Digitale": "https://www.usine-digitale.fr/rss"
        }
    },
    "sciences": {
        "name": "Sciences & Environnement",
        "icon": "🔬",
        "color": "#06b6d4",
        "feeds": {
            "Futura Sciences": "https://www.futura-sciences.com/rss/actualites.xml",
            "Reporterre": "https://reporterre.net/spip.php?page=backend",
            "Nature News": "https://www.nature.com/nature.rss"
        }
    },
    "sante": {
        "name": "Santé & Médecine",
        "icon": "🩺",
        "color": "#ec4899",
        "feeds": {
            "Inserm": "https://www.inserm.fr/feed/",
            "Futura Santé": "https://www.futura-sciences.com/rss/sante/actualites.xml"
        }
    },
    "sport": {
        "name": "Sport",
        "icon": "⚽",
        "color": "#f59e0b",
        "feeds": {
            "L'Équipe": "https://www.lequipe.fr/rss/actu_rss.xml",
            "RMC Sport": "https://rmcsport.bfmtv.com/rss/fil-info/",
            "BBC Sport": "http://feeds.bbci.co.uk/sport/rss.xml"
        }
    },
    "culture": {
        "name": "Culture, Société & Médias",
        "icon": "🎭",
        "color": "#6366f1",
        "feeds": {
            "France Culture": "https://www.radiofrance.fr/franceculture/rss",
            "Télérama": "https://www.telerama.fr/rss/actu.xml",
            "Le Monde Diplomatique": "https://www.monde-diplomatique.fr/rss/"
        }
    }
}

# Style CSS Global (Design Premium + Mode Sombre automatique)
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
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
        background: var(--bg-color); 
        color: var(--text-primary); 
        max-width: 680px; 
        margin: 0 auto; 
        padding: 20px 16px 40px 16px;
        line-height: 1.5;
    }
    header { text-align: center; margin-bottom: 24px; padding-top: 10px; }
    header h1 { font-size: 2rem; font-weight: 800; letter-spacing: -0.5px; color: var(--text-primary); }
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
        transition: transform 0.15s ease, box-shadow 0.15s ease;
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
    .card-title { font-size: 1.1rem; font-weight: 700; line-height: 1.4; margin-bottom: 14px; color: var(--text-primary); }
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
        transition: opacity 0.2s;
    }
    .btn:active { opacity: 0.85; }
    .back { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 20px; color: var(--accent-color); text-decoration: none; font-weight: 600; font-size: 0.95rem; }
"""

def fetch_clean_text(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        text = trafilatura.extract(response.text, include_links=False)
        return text or "Impossible d'extraire le texte brut de cet article."
    except Exception as e:
        return f"Impossible de charger la page source : {str(e)}"

# Page d'accueil : Sélection du Domaine
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

# Page d'un Domaine spécifique
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
            for entry in feed.entries[:3]: # 3 articles par source
                published_date = entry.get("published", entry.get("updated", "Aujourd'hui"))
                articles.append({
                    "title": entry.title,
                    "source": source_name,
                    "date": published_date,
                    "safe_url": quote(entry.link, safe=""),
                    "safe_title": quote(entry.title, safe="")
                })
        except Exception:
            continue

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
        </header>

        <div class="articles-list">
            {"".join([f'''
            <div class="card">
                <div class="card-meta">
                    <span class="tag">{a['source']}</span>
                    <span class="date">{a['date'][:16]}</span>
                </div>
                <div class="card-title">{a['title']}</div>
                <a class="btn" href="/article?url={a['safe_url']}&title={a['safe_title']}&cat={cat_key}">Lire l'article nettoyé</a>
            </div>
            ''' for a in articles])}
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

# Page de Lecture Nettoyée
@app.route("/article")
def article():
    raw_url = request.args.get("url")
    raw_title = request.args.get("title", "Article")
    cat_key = request.args.get("cat", "")
    
    if not raw_url:
        return "URL manquante.", 400
        
    target_url = unquote(raw_url)
    title = unquote(raw_title)
    content = fetch_clean_text(target_url)
    
    back_url = f"/category?cat={cat_key}" if cat_key else "/"
    
    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            {COMMON_CSS}
            body {{ background: var(--card-bg); }}
            article {{ font-size: 1.05rem; line-height: 1.8; color: var(--text-primary); margin-top: 20px; white-space: pre-line; }}
            h1 {{ font-size: 1.5rem; line-height: 1.35; margin-bottom: 12px; }}
        </style>
    </head>
    <body>
        <a class="back" href="{back_url}">&larr; Retour au flux</a>
        <header style="text-align: left; border-bottom: 1px solid var(--border-color); padding-bottom: 16px;">
            <h1>{title}</h1>
        </header>
        <article>{content}</article>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
