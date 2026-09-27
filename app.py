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

# --- IN-MEMORY CACHE ---
CACHE_FEEDS = {}         # {cat_key: (timestamp, articles_list)}
CACHE_ARTICLES = {}      # {url: (timestamp, raw_text)}
CACHE_TRANSLATIONS = {}  # {url: (timestamp, title, content)}

FEED_CACHE_TTL = 600      # 10 minutes
ARTICLE_CACHE_TTL = 86400  # 24 hours

CATEGORIES = {
    "politics": {
        "name": "Politics & World",
        "icon": "🌐",
        "feeds": {
            "BBC News": "http://feeds.bbci.co.uk/news/world/rss.xml",
            "Reuters": "https://news.google.com/rss/search?q=site:reuters.com+world+when:2d&hl=en-US&gl=US&ceid=US:en",
            "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
            "AP News": "https://news.google.com/rss/search?q=site:apnews.com+when:2d&hl=en-US&gl=US&ceid=US:en"
        }
    },
    "economy": {
        "name": "Business & Economy",
        "icon": "📈",
        "feeds": {
            "Bloomberg": "https://news.google.com/rss/search?q=site:bloomberg.com+when:2d&hl=en-US&gl=US&ceid=US:en",
            "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            "Financial Times": "https://news.google.com/rss/search?q=site:ft.com+when:2d&hl=en-US&gl=US&ceid=US:en",
            "CNBC": "https://www.cnbc.com/id/100003114/device/rss/rss.html"
        }
    },
    "tech": {
        "name": "Tech & AI",
        "icon": "💻",
        "feeds": {
            "The Verge": "https://www.theverge.com/rss/index.xml",
            "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
            "TechCrunch": "https://techcrunch.com/feed/",
            "Wired": "https://www.wired.com/feed/category/gear/latest/rss",
            "BleepingComputer": "https://www.bleepingcomputer.com/feed/"
        }
    },
    "philosophy": {
        "name": "Philosophy & Thought",
        "icon": "🧠",
        "feeds": {
            "Aeon Essays": "https://aeon.co/feed.rss",
            "Psyche": "https://psyche.co/feed.rss",
            "The Conversation": "https://news.google.com/rss/search?q=philosophy+society+when:3d&hl=en-US&gl=US&ceid=US:en"
        }
    },
    "cinema": {
        "name": "Movies & TV",
        "icon": "🎬",
        "feeds": {
            "Variety": "https://variety.com/feed/",
            "IndieWire": "https://www.indiewire.com/feed/",
            "Hollywood Reporter": "https://news.google.com/rss/search?q=site:hollywoodreporter.com+when:2d&hl=en-US&gl=US&ceid=US:en"
        }
    },
    "anime": {
        "name": "Anime & Manga",
        "icon": "⛩️",
        "feeds": {
            "Anime News Network": "https://www.animenewsnetwork.com/news/rss.xml",
            "Crunchyroll News": "https://news.google.com/rss/search?q=site:crunchyroll.com/news+when:2d&hl=en-US&gl=US&ceid=US:en",
            "Sakuga Blog": "https://blog.sakugabooru.com/feed/"
        }
    },
    "science": {
        "name": "Science & Space",
        "icon": "🔬",
        "feeds": {
            "Nature News": "https://www.nature.com/nature.rss",
            "SciTechDaily": "https://scitechdaily.com/feed/",
            "Live Science": "https://www.livescience.com/feeds/all"
        }
    },
    "health": {
        "name": "Health & Medicine",
        "icon": "🩺",
        "feeds": {
            "Medical News Today": "https://www.medicalnewstoday.com/feed",
            "Healthline": "https://news.google.com/rss/search?q=site:healthline.com+when:3d&hl=en-US&gl=US&ceid=US:en"
        }
    },
    "sports": {
        "name": "Sports",
        "icon": "⚽",
        "feeds": {
            "BBC Sport": "http://feeds.bbci.co.uk/sport/rss.xml",
            "ESPN": "https://www.espn.com/espn/rss/news",
            "The Athletic": "https://news.google.com/rss/search?q=site:theathletic.com+when:2d&hl=en-US&gl=US&ceid=US:en"
        }
    },
    "culture": {
        "name": "Culture & Society",
        "icon": "🎭",
        "feeds": {
            "The Atlantic": "https://news.google.com/rss/search?q=site:theatlantic.com+when:3d&hl=en-US&gl=US&ceid=US:en",
            "The New Yorker": "https://www.newyorker.com/feed/everything"
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
    header p { font-size: 0.85rem; color: var(--text-secondary); margin-top: 4px; }
    
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
function toggleFav(url, title, source, date, cat, img, summary) {
    let favs = getFavs();
    const idx = favs.findIndex(item => item.url === url);
    if (idx >= 0) {
        favs.splice(idx, 1);
    } else {
        favs.push({ url, title, source, date, cat, img, summary });
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
        formatted_date = dt.strftime("%b %d, %H:%M")
        return dt, formatted_date
    return None, "Today"

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

def fetch_clean_article(url, summary_fallback=""):
    """
    Primary method uses Jina AI Reader (https://r.jina.ai/)
    Bypasses Cloudflare & Bot Blockers seamlessly!
    """
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-No-Cache": "true"
    }
    
    # 1. Try Jina Reader
    try:
        resp = requests.get(jina_url, headers=headers, timeout=12)
        if resp.status_code == 200 and len(resp.text.strip()) > 150:
            content = resp.text
            # Remove Jina markdown headers if present
            if "Markdown Content:" in content:
                content = content.split("Markdown Content:", 1)[1]
            
            # Clean markdown links/images for clean reading
            clean_text = re.sub(r'!?\[.*?\]\(.*?\)', '', content)
            clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
            
            if len(clean_text) > 100:
                return clean_text
    except Exception:
        pass

    # 2. Fallback to Direct Trafilatura Extraction
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            text = trafilatura.extract(resp.text, include_links=False, output_format="txt") or ""
            if text and len(text.strip()) > 100:
                return text
    except Exception:
        pass

    # 3. Fallback to RSS summary if available
    if summary_fallback and len(summary_fallback.strip()) > 15:
        return f"Article Summary:\n\n{summary_fallback}"

    return "The full content of this article is protected by the source website. Please click 'View Original ↗' below to read it directly on the source site."

def translate_to_english(text):
    if not text:
        return text
    
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    if not paragraphs:
        return text

    translator = GoogleTranslator(source='auto', target='en')
    translated_paragraphs = []
    
    chunk = ""
    for p in paragraphs:
        if len(chunk) + len(p) < 900:
            chunk += ("\n\n" if chunk else "") + p
        else:
            try:
                res = translator.translate(chunk)
                translated_paragraphs.append(res if res else chunk)
            except Exception:
                translated_paragraphs.append(chunk)
            chunk = p
            
    if chunk:
        try:
            res = translator.translate(chunk)
            translated_paragraphs.append(res if res else chunk)
        except Exception:
            translated_paragraphs.append(chunk)

    return "\n\n".join(translated_paragraphs)

@app.route("/")
def index():
    today = datetime.now().strftime("%A, %B %d, %Y")
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>News Info Hub</title>
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <header>
            <h1>News Info Hub</h1>
            <p>{today}</p>
        </header>

        <a class="fav-banner" href="/favorites">
            <span>⭐ Read Later (Bookmarks)</span>
            <span id="fav-count" style="background: var(--accent-color); color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 0.85rem;">0</span>
        </a>

        <h2 style="font-size: 1.1rem; margin-bottom: 12px; color: var(--text-secondary);">Select a Category:</h2>
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
        return "Category not found.", 404
        
    cat_info = CATEGORIES[cat_key]
    now_time = time.time()
    
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
                    summary_raw = entry.get("summary", "") or entry.get("description", "")
                    summary_clean = re.sub(r'<[^>]+>', '', summary_raw).strip()
                    
                    articles.append({
                        "dt": dt or datetime.now(timezone.utc),
                        "title": entry.title,
                        "source": source_name,
                        "date": formatted_date,
                        "img": img_url or "",
                        "summary": summary_clean,
                        "safe_url": quote(entry.link, safe=""),
                        "safe_title": quote(entry.title, safe=""),
                        "safe_summary": quote(summary_clean, safe=""),
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
                <a class="btn" href="/article?url={a['safe_url']}&title={a['safe_title']}&cat={cat_key}&summary={a['safe_summary']}">Read Article</a>
                <button class="btn-fav" data-url="{a['raw_url']}" onclick="toggleFav('{a['raw_url']}', '{quote(a['title'], safe='')}', '{a['source']}', '{a['date']}', '{cat_key}', '{a['img']}', '{a['safe_summary']}')">📌</button>
            </div>
        </div>
        '''

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{cat_info['name']} - News Info</title>
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <a class="back" href="/">&larr; All Categories</a>
        <header style="text-align: left; margin-bottom: 20px;">
            <div style="font-size: 2.5rem; margin-bottom: 4px;">{cat_info['icon']}</div>
            <h1>{cat_info['name']}</h1>
            <p style="text-align:left;">Published in the last 48 hours</p>
        </header>

        <div class="articles-list">
            {articles_html if articles else '<p style="color: var(--text-secondary);">No articles published in the last 48 hours.</p>'}
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
    raw_summary = request.args.get("summary", "")
    cat_key = request.args.get("cat", "")
    
    if not raw_url:
        return "Missing URL.", 400
        
    target_url = unquote(raw_url)
    title = unquote(raw_title)
    summary_fallback = unquote(raw_summary)
    now_time = time.time()
    
    if target_url in CACHE_TRANSLATIONS and (now_time - CACHE_TRANSLATIONS[target_url]['time'] < ARTICLE_CACHE_TTL):
        translated_title = CACHE_TRANSLATIONS[target_url]['title']
        translated_content = CACHE_TRANSLATIONS[target_url]['content']
    else:
        if target_url in CACHE_ARTICLES and (now_time - CACHE_ARTICLES[target_url]['time'] < ARTICLE_CACHE_TTL):
            raw_content = CACHE_ARTICLES[target_url]['text']
        else:
            raw_content = fetch_clean_article(target_url, summary_fallback)
            CACHE_ARTICLES[target_url] = {'time': now_time, 'text': raw_content}
            
        translated_title = translate_to_english(title)
        translated_content = translate_to_english(raw_content)
        
        CACHE_TRANSLATIONS[target_url] = {
            'time': now_time, 
            'title': translated_title, 
            'content': translated_content
        }
    
    back_url = f"/category?cat={cat_key}" if cat_key else "/"
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{translated_title}</title>
        <style>
            {COMMON_CSS}
            body {{ background: var(--card-bg); }}
            .top-bar {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color); }}
            .audio-btn {{ background: var(--bg-color); border: 1px solid var(--border-color); padding: 8px 14px; border-radius: 8px; color: var(--text-primary); cursor: pointer; font-weight: 700; font-size: 0.85rem; }}
            article {{ font-size: 1.05rem; line-height: 1.8; color: var(--text-primary); margin-top: 20px; white-space: pre-line; }}
            h1 {{ font-size: 1.5rem; line-height: 1.35; margin-bottom: 12px; }}
            .actions {{ margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border-color); text-align: center; display: flex; justify-content: center; gap: 10px; }}
        </style>
    </head>
    <body>
        <div class="top-bar">
            <a class="back" style="margin-bottom:0;" href="{back_url}">&larr; Back to Feed</a>
            <button id="speech-btn" class="audio-btn" onclick="toggleAudio()">🔊 Listen</button>
        </div>

        <header style="text-align: left; padding-bottom: 12px;">
            <h1>{translated_title}</h1>
        </header>

        <article id="article-body">{translated_content}</article>

        <div class="actions">
            <a class="btn-outline" href="{target_url}" target="_blank" rel="noopener">View Original ↗</a>
            <button class="btn-fav" data-url="{target_url}" onclick="toggleFav('{target_url}', '{quote(raw_title, safe='')}', 'Source', '', '{cat_key}', '', '{quote(raw_summary, safe='')}')">📌</button>
        </div>

        {BOOKMARK_JS}
        <script>
            let synth = window.speechSynthesis;
            let speechChunks = [];
            let currentChunk = 0;
            let isSpeaking = false;

            function stopAudio() {{
                synth.cancel();
                isSpeaking = false;
                document.getElementById('speech-btn').innerHTML = "🔊 Listen";
            }}

            function toggleAudio() {{
                const btn = document.getElementById('speech-btn');
                if (isSpeaking) {{
                    stopAudio();
                    return;
                }}

                const fullText = document.getElementById('article-body').innerText;
                if (!fullText || fullText.length < 5) return;

                speechChunks = fullText.match(/[^.!?]+[.!?]+/g) || [fullText];
                currentChunk = 0;
                isSpeaking = true;
                btn.innerHTML = "⏹️ Stop";

                speakNext();
            }}

            function speakNext() {{
                if (!isSpeaking || currentChunk >= speechChunks.length) {{
                    stopAudio();
                    return;
                }}

                const chunkText = speechChunks[currentChunk].trim();
                if (!chunkText) {{
                    currentChunk++;
                    speakNext();
                    return;
                }}

                const utterance = new SpeechSynthesisUtterance(chunkText);
                utterance.lang = "en-US";
                utterance.rate = 1.0;

                utterance.onend = function() {{
                    currentChunk++;
                    speakNext();
                }};

                utterance.onerror = function() {{
                    currentChunk++;
                    speakNext();
                }};

                synth.speak(utterance);
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
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Saved Articles - News Info</title>
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <a class="back" href="/">&larr; Home</a>
        <header style="text-align: left; margin-bottom: 20px;">
            <h1>⭐ Saved Articles</h1>
            <p style="text-align:left;">Read later</p>
        </header>

        <div id="favs-list"></div>

        <script>
            function renderFavs() {{
                const favs = JSON.parse(localStorage.getItem('news_favs') || '[]');
                const container = document.getElementById('favs-list');
                if (favs.length === 0) {{
                    container.innerHTML = '<p style="color: var(--text-secondary);">No saved articles yet.</p>';
                    return;
                }}
                
                let html = '';
                favs.forEach(a => {{
                    const title = decodeURIComponent(a.title);
                    const safeTitle = encodeURIComponent(title);
                    const safeUrl = encodeURIComponent(a.url);
                    const safeSummary = a.summary || '';
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
                            <a class="btn" href="/article?url=${{safeUrl}}&title=${{safeTitle}}&cat=${{a.cat}}&summary=${{safeSummary}}">Read Article</a>
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
