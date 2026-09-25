import os
import re
import time
import requests
import feedparser
import trafilatura
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, unquote
from deep_translator import GoogleTranslator
from flask import Flask, render_template_string, request

app = Flask(__name__)

# --- SYSTÈME DE CACHE EN MÉMOIRE ---
CACHE_FEEDS = {}         # {cat_key: (timestamp, articles_list)}
CACHE_ARTICLES = {}      # {url: (timestamp, raw_text)}
CACHE_TRANSLATIONS = {}  # {(url, target_lang): (timestamp, title, content)}

FEED_CACHE_TTL = 600      # 10 minutes pour les flux
ARTICLE_CACHE_TTL = 86400  # 24 heures pour les articles et traductions

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
        margin-bottom: 24px;
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
        padding: 16px; 
        margin-bottom: 14px; 
        border-radius: 16px; 
        border: 1px solid var(--border-color);
        box-shadow: 0 2px 8px rgba(0,0,0,0.03); 
    }
    .card-body-layout {
        display: flex;
        gap: 12px;
        align-items: flex-start;
        margin-bottom: 12px;
    }
    .card-thumb {
        width: 84px;
        height: 84px;
        border-radius: 10px;
        object-fit: cover;
        flex-shrink: 0;
        background: var(--border-color);
    }
    .card-main { flex: 1; }
    .card-meta { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
    .tag { font-size: 0.72rem; font-weight: 700; padding: 3px 8px; border-radius: 20px; background: rgba(37,99,235,0.1); color: var(--accent-color); }
    .date { font-size: 0.72rem; color: var(--text-secondary); }
    .card-title { font-size: 1rem; font-weight: 700; line-height: 1.35; color: var(--text-primary); }
    
    .card-actions {
        display: flex;
        gap: 8px;
        align-items: center;
    }
    .btn { 
        flex: 1;
        text-align: center; 
        padding: 9px 12px; 
        background: var(--accent-color); 
        color: #ffffff; 
        text-decoration: none; 
        border-radius: 10px; 
        font-weight: 600; 
        font-size: 0.85rem; 
    }
    .btn-fav {
        background: var(--bg-color);
        border: 1px solid var(--border-color);
        padding: 8px 12px;
        border-radius: 10px;
        cursor: pointer;
        font-size: 1.1rem;
        transition: background 0.2s;
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
    .back { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 16px; color: var(--accent-color); text-decoration: none; font-weight: 600; font-size: 0.95rem; }
    
    .fav-banner {
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 14px;
        border-radius: 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        text-decoration: none;
        color: var(--text-primary);
        margin-bottom: 24px;
        font-weight: 700;
    }
"""

BOOKMARK_JS = """
<script>
function getFavs() {
    return JSON.parse(localStorage.getItem('news_favs') || '[]');
}
function isFav(url) {
    return getFavs().some(item => item.url === url);
}
function toggleFav(url, title, source, date, cat, img) {
    let favs = getFavs();
    const idx = favs.findIndex(item => item.url === url);
    if (idx >= 0) {
        favs.splice(idx, 1);
    } else {
        favs.push({ url, title, source, date, cat, img });
    }
    localStorage.setItem('news_favs', JSON.stringify(favs));
    updateFavBtns();
}
function updateFavBtns() {
    document.querySelectorAll('.btn-fav').forEach(btn => {
        const url = btn.getAttribute('data-url');
        btn.innerHTML = isFav(url) ? '⭐' : '📌';
    });
    const countEl = document.getElementById('fav-count');
    if (countEl) countEl.innerText = getFavs().length;
}
document.addEventListener('DOMContentLoaded', updateFavBtns);
</script>
"""

def parse_and_filter_date(entry):
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time:
        dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if (now - dt) > timedelta(hours=48):
            return None, None
        formatted_date = dt.strftime("%d/%m à %H:%M")
        return dt, formatted_date
    return None, "Aujourd'hui"

def extract_image_from_entry(entry):
    if "media_content" in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get("url")
    if "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
        return entry.media_thumbnail[0].get("url")
    if "enclosures" in entry and len(entry.enclosures) > 0:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image"):
                return enc.get("href")
    summary = entry.get("summary", "") or entry.get("description", "")
    if summary:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
        if m:
            return m.group(1)
    return None

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
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        
        chunks = []
        curr_chunk = []
        curr_len = 0
        
        for p in paragraphs:
            if curr_len + len(p) > 2500:
                chunks.append("\n\n".join(curr_chunk))
                curr_chunk = [p]
                curr_len = len(p)
            else:
                curr_chunk.append(p)
                curr_len += len(p)
        if curr_chunk:
            chunks.append("\n\n".join(curr_chunk))

        translated_chunks = []
        for chunk in chunks:
            try:
                res = translator.translate(chunk)
                translated_chunks.append(res if res else chunk)
            except Exception:
                translated_chunks.append(chunk)
                
        return "\n\n".join(translated_chunks)
    except Exception as e:
        print("Erreur globale de traduction :", e)
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

        <a class="fav-banner" href="/favorites">
            <span>⭐ À lire plus tard (Favoris)</span>
            <span id="fav-count" style="background: var(--accent-color); color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 0.85rem;">0</span>
        </a>

        <h2 style="font-size: 1.1rem; margin-bottom: 12px; color: var(--text-secondary);">Choisissez un domaine :</h2>
        <div class="category-grid">
            {"".join([f'''
            <a class="cat-card" href="/category?cat={cat_key}">
                <div class="cat-icon">{cat['icon']}</div>
                <div class="cat-title">{cat['name']}</div>
            </a>
            ''' for cat_key, cat in CATEGORIES.items()])}
        </div>
        {BOOKMARK_JS}
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
    now_time = time.time()
    
    # Vérification du cache de flux
    if cat_key in CACHE_FEEDS and (now_time - CACHE_FEEDS[cat_key]['time'] < FEED_CACHE_TTL):
        articles = CACHE_FEEDS[cat_key]['articles']
    else:
        articles = []
        for source_name, feed_url in cat_info["feeds"].items():
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:8]:
                    dt, formatted_date = parse_and_filter_date(entry)
                    if formatted_date is None:
                        continue
                        
                    img_url = extract_image_from_entry(entry)
                    
                    articles.append({
                        "dt": dt or datetime.now(timezone.utc),
                        "title": entry.title,
                        "source": source_name,
                        "date": formatted_date,
                        "img": img_url or "",
                        "safe_url": quote(entry.link, safe=""),
                        "safe_title": quote(entry.title, safe=""),
                        "raw_url": entry.link
                    })
            except Exception:
                continue

        articles.sort(key=lambda x: x["dt"], reverse=True)
        CACHE_FEEDS[cat_key] = {'time': now_time, 'articles': articles}

    articles_html = ""
    for a in articles:
        img_tag = f'<img class="card-thumb" src="{a["img"]}" loading="lazy" alt="" />' if a["img"] else ''
        articles_html += f'''
        <div class="card">
            <div class="card-body-layout">
                {img_tag}
                <div class="card-main">
                    <div class="card-meta">
                        <span class="tag">{a['source']}</span>
                        <span class="date">{a['date']}</span>
                    </div>
                    <div class="card-title">{a['title']}</div>
                </div>
            </div>
            <div class="card-actions">
                <a class="btn" href="/article?url={a['safe_url']}&title={a['safe_title']}&cat={cat_key}&lang=fr">Lire l'article</a>
                <button class="btn-fav" data-url="{a['raw_url']}" onclick="toggleFav('{a['raw_url']}', '{quote(a['title'], safe='')}', '{a['source']}', '{a['date']}', '{cat_key}', '{a['img']}')">📌</button>
            </div>
        </div>
        '''

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
            {articles_html if articles else '<p style="color: var(--text-secondary);">Aucun article publié ces dernières 48 heures.</p>'}
        </div>
        {BOOKMARK_JS}
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
    now_time = time.time()
    
    cache_key = (target_url, target_lang)
    
    # Récupération depuis le cache de traduction
    if cache_key in CACHE_TRANSLATIONS and (now_time - CACHE_TRANSLATIONS[cache_key]['time'] < ARTICLE_CACHE_TTL):
        translated_title = CACHE_TRANSLATIONS[cache_key]['title']
        translated_content = CACHE_TRANSLATIONS[cache_key]['content']
    else:
        # Récupération de l'article brut
        if target_url in CACHE_ARTICLES and (now_time - CACHE_ARTICLES[target_url]['time'] < ARTICLE_CACHE_TTL):
            raw_content = CACHE_ARTICLES[target_url]['text']
        else:
            raw_content = fetch_clean_article(target_url)
            CACHE_ARTICLES[target_url] = {'time': now_time, 'text': raw_content}
            
        translated_title = translate_text(title, target_lang)
        translated_content = translate_text(raw_content, target_lang)
        
        CACHE_TRANSLATIONS[cache_key] = {
            'time': now_time, 
            'title': translated_title, 
            'content': translated_content
        }
    
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
            .audio-btn {{ background: var(--bg-color); border: 1px solid var(--border-color); padding: 6px 12px; border-radius: 8px; color: var(--text-primary); cursor: pointer; font-weight: 700; font-size: 0.85rem; }}
            article {{ font-size: 1.05rem; line-height: 1.8; color: var(--text-primary); margin-top: 20px; white-space: pre-line; }}
            h1 {{ font-size: 1.5rem; line-height: 1.35; margin-bottom: 12px; }}
            .actions {{ margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border-color); text-align: center; display: flex; justify-content: center; gap: 10px; }}
        </style>
    </head>
    <body>
        <a class="back" href="{back_url}">&larr; Retour au flux</a>
        
        <div class="top-bar">
            <div class="lang-switch">
                <a class="{btn_fr_class}" href="/article?url={quote(raw_url, safe='')}&title={quote(raw_title, safe='')}&cat={cat_key}&lang=fr">🇫🇷 Français</a>
                <a class="{btn_en_class}" href="/article?url={quote(raw_url, safe='')}&title={quote(raw_title, safe='')}&cat={cat_key}&lang=en">🇬🇧 English</a>
            </div>
            <button id="speech-btn" class="audio-btn" onclick="toggleAudio()">🔊 Écouter</button>
        </div>

        <header style="text-align: left; padding-bottom: 12px;">
            <h1>{translated_title}</h1>
        </header>

        <article id="article-body">{translated_content}</article>

        <div class="actions">
            <a class="btn-outline" href="{target_url}" target="_blank" rel="noopener">Voir l'original ↗</a>
            <button class="btn-fav" data-url="{target_url}" onclick="toggleFav('{target_url}', '{quote(raw_title, safe='')}', 'Source', '', '{cat_key}', '')">📌</button>
        </div>

        {BOOKMARK_JS}
        <script>
            let synth = window.speechSynthesis;
            let utterance = null;

            function toggleAudio() {{
                const btn = document.getElementById('speech-btn');
                if (synth.speaking && !synth.paused) {{
                    synth.pause();
                    btn.innerHTML = "▶️ Reprendre";
                    return;
                }}
                if (synth.paused) {{
                    synth.resume();
                    btn.innerHTML = "⏸️ Pause";
                    return;
                }}
                
                const text = document.getElementById('article-body').innerText;
                utterance = new SpeechSynthesisUtterance(text);
                utterance.lang = "{target_lang}" === "en" ? "en-US" : "fr-FR";
                
                utterance.onend = function() {{
                    btn.innerHTML = "🔊 Écouter";
                }};
                
                synth.speak(utterance);
                btn.innerHTML = "⏸️ Pause";
            }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/favorites")
def favorites():
    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Mes Favoris - News info</title>
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <a class="back" href="/">&larr; Accueil</a>
        <header style="text-align: left; margin-bottom: 20px;">
            <h1>⭐ Articles sauvegardés</h1>
            <p style="text-align:left;">À lire plus tard</p>
        </header>

        <div id="favs-list"></div>

        <script>
            function renderFavs() {{
                const favs = JSON.parse(localStorage.getItem('news_favs') || '[]');
                const container = document.getElementById('favs-list');
                if (favs.length === 0) {{
                    container.innerHTML = '<p style="color: var(--text-secondary);">Aucun article sauvegardé pour le moment.</p>';
                    return;
                }}
                
                let html = '';
                favs.forEach(a => {{
                    const title = decodeURIComponent(a.title);
                    const safeTitle = encodeURIComponent(title);
                    const safeUrl = encodeURIComponent(a.url);
                    const imgTag = a.img ? `<img class="card-thumb" src="${{a.img}}" loading="lazy" alt="" />` : '';
                    
                    html += `
                    <div class="card">
                        <div class="card-body-layout">
                            ${{imgTag}}
                            <div class="card-main">
                                <div class="card-meta">
                                    <span class="tag">${{a.source}}</span>
                                    <span class="date">${{a.date}}</span>
                                </div>
                                <div class="card-title">${{title}}</div>
                            </div>
                        </div>
                        <div class="card-actions">
                            <a class="btn" href="/article?url=${{safeUrl}}&title=${{safeTitle}}&cat=${{a.cat}}&lang=fr">Lire l'article</a>
                            <button class="btn-fav" onclick="removeFav('${{a.url}}')">🗑️</button>
                        </div>
                    </div>
                    `;
                }});
                container.innerHTML = html;
            }}

            function removeFav(url) {{
                let favs = JSON.parse(localStorage.getItem('news_favs') || '[]');
                favs = favs.filter(item => item.url !== url);
                localStorage.setItem('news_favs', JSON.stringify(favs));
                renderFavs();
            }}

            document.addEventListener('DOMContentLoaded', renderFavs);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
