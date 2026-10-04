import os
import re
import time
import html
import json
import random
import requests
import feedparser
import trafilatura
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from deep_translator import GoogleTranslator
from flask import Flask, render_template_string, request, jsonify, send_from_directory

app = Flask(__name__)

# --- SYSTÈME DE CACHE BORNE AVEC PURGE AUTOMATIQUE (RAM-SAFE) ---
class BoundedTTLCache:
    def __init__(self, ttl_seconds, max_size=300):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self.cache = {}

    def get(self, key):
        if key in self.cache:
            timestamp, value = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None

    def set(self, key, value):
        self.purge_expired()
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][0])
            del self.cache[oldest_key]
        self.cache[key] = (time.time(), value)

    def purge_expired(self):
        now = time.time()
        expired = [k for k, (t, _) in self.cache.items() if now - t >= self.ttl]
        for k in expired:
            del self.cache[k]

CACHE_FEEDS = BoundedTTLCache(ttl_seconds=600, max_size=50)
CACHE_ARTICLES = BoundedTTLCache(ttl_seconds=86400, max_size=300)
CACHE_TRANSLATIONS = BoundedTTLCache(ttl_seconds=86400, max_size=300)
CACHE_SUMMARIES = BoundedTTLCache(ttl_seconds=86400, max_size=300)
CACHE_SEARCH = BoundedTTLCache(ttl_seconds=300, max_size=100)

# --- ROTATION DE USER-AGENTS RÉALISTES ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

# --- RÉSUMÉ EXTRACTIF (TextRank via sumy, léger) ---
def generate_summary(text, sentence_count=5):
    if not text or len(text.strip()) < 200:
        return None
    try:
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.summarizers.text_rank import TextRankSummarizer
        import nltk
        
        # Télécharger les données NLTK si nécessaire
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt', quiet=True)
            nltk.download('punkt_tab', quiet=True)
        
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = TextRankSummarizer()
        summary_sentences = summarizer(parser.document, sentence_count)
        
        if summary_sentences:
            summary = " ".join([str(s) for s in summary_sentences])
            if len(summary) > 50:
                return summary
    except Exception:
        pass
    return None

# --- SCRAPING ANTI-BOT AMÉLIORÉ ---
def fetch_with_curl_cffi(url, headers=None):
    try:
        from curl_cffi import requests as curl_requests
        h = headers or get_random_headers()
        resp = curl_requests.get(url, headers=h, timeout=15, impersonate="chrome")
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text
    except Exception:
        pass
    return None

def fetch_clean_article(url, summary_fallback=""):
    real_url = resolve_real_url(url)
    jina_url = f"https://r.jina.ai/{real_url}"
    headers = get_random_headers()
    
    raw_text = ""
    
    # 1. Jina Reader
    try:
        resp = requests.get(jina_url, headers=headers, timeout=10)
        if resp.status_code == 200 and len(resp.text.strip()) > 150:
            content = resp.text
            if "Markdown Content:" in content:
                content = content.split("Markdown Content:", 1)[1]
            
            clean_text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', content)
            clean_text = re.sub(r'#{1,6}\s*', '', clean_text)
            clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
            
            if len(clean_text) > 300:
                return clean_text
            raw_text = clean_text
    except Exception:
        pass

    # 2. curl_cffi
    html_content = fetch_with_curl_cffi(real_url)
    if html_content:
        try:
            text = trafilatura.extract(html_content, include_links=False, output_format="txt") or ""
            if len(text.strip()) > 300:
                return text.strip()
            if len(text.strip()) > len(raw_text):
                raw_text = text.strip()
        except Exception:
            pass

    # 3. Trafilatura direct
    try:
        resp = requests.get(real_url, headers=headers, timeout=6)
        if resp.status_code == 200:
            text = trafilatura.extract(resp.text, include_links=False, output_format="txt") or ""
            if len(text.strip()) > 300:
                return text.strip()
            if len(text.strip()) > len(raw_text):
                raw_text = text.strip()
    except Exception:
        pass

    if len(raw_text) > 150:
        return raw_text

    # 4. Fallback Paywall
    if summary_fallback and len(summary_fallback.strip()) > 15:
        return f"{summary_fallback}\n\n[Note: The full article is restricted or paywalled on the source website. Click 'View Original ↗' below to read directly on the publisher site.]"

    return "The full content of this article is protected or restricted by the source website. Please click 'View Original ↗' below to read it directly on the publisher site."

# --- CATÉGORIES DE FEEDS ---
CATEGORIES = {
    "politics": {
        "name": "Politics & World",
        "icon": "🌐",
        "feeds": {
            "BBC News": "http://feeds.bbci.co.uk/news/world/rss.xml",
            "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
            "CNN World": "http://rss.cnn.com/rss/edition_world.rss",
            "NPR World": "https://feeds.npr.org/1004/rss.xml",
            "Deutsche Welle": "https://rss.dw.com/xml/rss-out_top-stories"
        }
    },
    "economy": {
        "name": "Business & Economy",
        "icon": "📈",
        "feeds": {
            "CNBC": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            "Fortune": "https://fortune.com/feed/",
            "Business Insider": "https://www.businessinsider.com/rss",
            "Yahoo Finance": "https://finance.yahoo.com/news/rssindex"
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
            "Engadget": "https://www.engadget.com/rss.xml",
            "BleepingComputer": "https://www.bleepingcomputer.com/feed/"
        }
    },
    "philosophy": {
        "name": "Philosophy & Thought",
        "icon": "🧠",
        "feeds": {
            "Aeon Essays": "https://aeon.co/feed.rss",
            "Psyche": "https://psyche.co/feed.rss",
            "Daily Nous": "https://dailynous.com/feed/",
            "Institute of Art and Ideas": "https://iai.tv/rss/articles"
        }
    },
    "cinema": {
        "name": "Movies & TV",
        "icon": "🎬",
        "feeds": {
            "Variety": "https://variety.com/feed/",
            "IndieWire": "https://www.indiewire.com/feed/",
            "Collider": "https://collider.com/feed/",
            "Deadline": "https://deadline.com/feed/",
            "Screen Rant": "https://screenrant.com/feed/"
        }
    },
    "anime": {
        "name": "Anime & Manga",
        "icon": "⛩️️",
        "feeds": {
            "Anime News Network": "https://www.animenewsnetwork.com/news/rss.xml",
            "Otaku USA Magazine": "https://otakuusamagazine.com/feed/",
            "Sakuga Blog": "https://blog.sakugabooru.com/feed/",
            "Anime Herald": "https://www.animeherald.com/feed/"
        }
    },
    "science": {
        "name": "Science & Space",
        "icon": "🔬",
        "feeds": {
            "Nature News": "https://www.nature.com/nature.rss",
            "SciTechDaily": "https://scitechdaily.com/feed/",
            "Live Science": "https://www.livescience.com/feeds/all",
            "Space.com": "https://www.space.com/feeds/all",
            "Phys.org": "https://phys.org/rss-feed/"
        }
    },
    "health": {
        "name": "Health & Medicine",
        "icon": "🩺",
        "feeds": {
            "Medical News Today": "https://www.medicalnewstoday.com/feed",
            "Harvard Health": "https://www.health.harvard.edu/blog/feed",
            "Everyday Health": "https://www.everydayhealth.com/rss/"
        }
    },
    "sports": {
        "name": "Sports",
        "icon": "⚽",
        "feeds": {
            "BBC Sport": "http://feeds.bbci.co.uk/sport/rss.xml",
            "ESPN": "https://www.espn.com/espn/rss/news",
            "CBS Sports": "https://www.cbssports.com/rss/headlines/",
            "Sky Sports": "https://www.skysports.com/rss/12040"
        }
    },
    "culture": {
        "name": "Culture & Society",
        "icon": "🎭",
        "feeds": {
            "The New Yorker": "https://www.newyorker.com/feed/everything",
            "Rolling Stone": "https://www.rollingstone.com/feed/",
            "Smithsonian Magazine": "https://www.smithsonianmag.com/rss/latest_articles/",
            "Slate": "https://slate.com/feeds/all.rss"
        }
    }
}

# --- LOGO MASCOTTE EN SVG VECTORIEL ---
MASCOT_SVG = """
<svg class="brand-logo" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
        <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#2563eb" />
            <stop offset="100%" stop-color="#7c3aed" />
        </linearGradient>
        <linearGradient id="eyeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#38bdf8" />
            <stop offset="100%" stop-color="#2563eb" />
        </linearGradient>
    </defs>
    <circle cx="50" cy="50" r="46" fill="url(#logoGrad)" opacity="0.12"/>
    <circle cx="50" cy="50" r="40" stroke="url(#logoGrad)" stroke-width="2.5" stroke-dasharray="4 3"/>
    <path d="M28 36 L50 22 L72 36 L68 68 L50 82 L32 68 Z" fill="url(#logoGrad)"/>
    <circle cx="41" cy="44" r="7.5" fill="#ffffff"/>
    <circle cx="59" cy="44" r="7.5" fill="#ffffff"/>
    <circle cx="41" cy="44" r="4" fill="url(#eyeGrad)"/>
    <circle cx="59" cy="44" r="4" fill="url(#eyeGrad)"/>
    <circle cx="42.5" cy="42.5" r="1.5" fill="#ffffff"/>
    <circle cx="60.5" cy="42.5" r="1.5" fill="#ffffff"/>
    <path d="M46 51 L50 56 L54 51 Z" fill="#f59e0b"/>
    <path d="M36 62 Q50 70 64 62" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" fill="none" opacity="0.9"/>
</svg>
"""

COMMON_CSS = f"""
    :root {{
        --bg-color: #f8fafc;
        --card-bg: #ffffff;
        --text-primary: #0f172a;
        --text-secondary: #64748b;
        --border-color: #e2e8f0;
        --accent-color: #2563eb;
        --accent-gradient: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
    }}
    @media (prefers-color-scheme: dark) {{
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --border-color: #334155;
            --accent-color: #3b82f6;
            --accent-gradient: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
        }}
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ 
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
        background: var(--bg-color); 
        color: var(--text-primary); 
        max-width: 720px; 
        margin: 0 auto; 
        padding: 20px 16px 40px 16px;
        line-height: 1.5;
    }}
    
    .brand-header {{
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        margin-bottom: 24px;
        padding-top: 10px;
        text-align: center;
    }}
    .brand-logo {{
        width: 72px;
        height: 72px;
        margin-bottom: 10px;
        filter: drop-shadow(0 4px 12px rgba(37, 99, 235, 0.2));
        transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    }}
    .brand-logo:hover {{
        transform: scale(1.08) rotate(-3deg);
    }}
    .brand-title {{
        font-size: 2.1rem;
        font-weight: 900;
        letter-spacing: -0.8px;
        background: var(--accent-gradient);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }}
    .brand-sub {{
        font-size: 0.85rem;
        color: var(--text-secondary);
        margin-top: 4px;
        font-weight: 500;
    }}
    
    .category-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
        gap: 12px;
        margin-bottom: 24px;
    }}
    .cat-card {{
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 16px 12px;
        border-radius: 16px;
        text-decoration: none;
        color: var(--text-primary);
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        transition: all 0.2s ease;
        box-shadow: 0 2px 5px rgba(0,0,0,0.02);
    }}
    .cat-card:hover {{
        transform: translateY(-2px);
        border-color: var(--accent-color);
        box-shadow: 0 6px 16px rgba(0,0,0,0.06);
    }}
    .cat-card:active {{ transform: scale(0.97); }}
    .cat-icon {{ font-size: 2rem; margin-bottom: 8px; }}
    .cat-title {{ font-size: 0.9rem; font-weight: 700; line-height: 1.2; }}

    .card {{ 
        background: var(--card-bg); 
        padding: 18px; 
        margin-bottom: 16px; 
        border-radius: 18px; 
        border: 1px solid var(--border-color);
        box-shadow: 0 4px 12px rgba(0,0,0,0.03); 
        transition: border-color 0.2s ease;
    }}
    .card:hover {{
        border-color: var(--accent-color);
    }}
    .card-body-layout {{
        display: flex;
        gap: 14px;
        align-items: flex-start;
        margin-bottom: 14px;
    }}
    .card-thumb {{
        width: 88px;
        height: 88px;
        border-radius: 12px;
        object-fit: cover;
        flex-shrink: 0;
        background: var(--border-color);
    }}
    .card-main {{ flex: 1; }}
    .card-meta {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }}
    .tag {{ font-size: 0.72rem; font-weight: 700; padding: 3px 9px; border-radius: 20px; background: rgba(37,99,235,0.12); color: var(--accent-color); }}
    .date {{ font-size: 0.72rem; color: var(--text-secondary); }}
    .card-title {{ font-size: 1.05rem; font-weight: 700; line-height: 1.4; color: var(--text-primary); }}
    
    .card-actions {{
        display: flex;
        gap: 10px;
        align-items: center;
    }}
    .btn {{ 
        flex: 1;
        text-align: center; 
        padding: 10px 14px; 
        background: var(--accent-gradient); 
        color: #ffffff; 
        text-decoration: none; 
        border-radius: 12px; 
        font-weight: 700; 
        font-size: 0.88rem; 
        box-shadow: 0 2px 8px rgba(37,99,235,0.25);
        transition: opacity 0.2s;
    }}
    .btn:hover {{ opacity: 0.92; }}
    .btn-fav {{
        background: var(--bg-color);
        border: 1px solid var(--border-color);
        padding: 8px 12px;
        border-radius: 12px;
        cursor: pointer;
        font-size: 1.1rem;
        transition: transform 0.15s ease;
    }}
    .btn-fav:active {{ transform: scale(0.88); }}
    .btn-outline {{
        display: inline-block;
        padding: 9px 16px;
        border: 1px solid var(--border-color);
        border-radius: 10px;
        color: var(--text-primary);
        text-decoration: none;
        font-size: 0.88rem;
        font-weight: 700;
        background: var(--card-bg);
    }}
    .back {{ display: inline-flex; align-items: center; gap: 6px; margin-bottom: 16px; color: var(--accent-color); text-decoration: none; font-weight: 700; font-size: 0.95rem; }}
    
    .fav-banner {{
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 14px 18px;
        border-radius: 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        text-decoration: none;
        color: var(--text-primary);
        margin-bottom: 24px;
        font-weight: 700;
        box-shadow: 0 2px 8px rgba(0,0,0,0.02);
    }}
    
    /* Search Bar */
    .search-container {{
        margin-bottom: 24px;
        position: relative;
    }}
    .search-input {{
        width: 100%;
        padding: 14px 20px 14px 48px;
        border: 2px solid var(--border-color);
        border-radius: 14px;
        background: var(--card-bg);
        color: var(--text-primary);
        font-size: 1rem;
        font-weight: 500;
        outline: none;
        transition: border-color 0.2s ease;
    }}
    .search-input:focus {{
        border-color: var(--accent-color);
    }}
    .search-icon {{
        position: absolute;
        left: 16px;
        top: 50%;
        transform: translateY(-50%);
        font-size: 1.2rem;
        opacity: 0.5;
    }}
    
    /* Theme Toggle */
    .theme-toggle {{
        position: fixed;
        top: 20px;
        right: 20px;
        width: 48px;
        height: 48px;
        border-radius: 50%;
        border: 1px solid var(--border-color);
        background: var(--card-bg);
        cursor: pointer;
        font-size: 1.3rem;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transition: all 0.2s ease;
        z-index: 1000;
    }}
    .theme-toggle:hover {{
        transform: scale(1.1);
    }}
    
    /* Share Buttons */
    .share-buttons {{
        display: flex;
        gap: 8px;
        margin-top: 12px;
        flex-wrap: wrap;
    }}
    .share-btn {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 14px;
        border-radius: 10px;
        border: 1px solid var(--border-color);
        background: var(--card-bg);
        color: var(--text-primary);
        text-decoration: none;
        font-size: 0.82rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
    }}
    .share-btn:hover {{
        border-color: var(--accent-color);
        transform: translateY(-1px);
    }}
    
    /* Summary Box */
    .summary-box {{
        background: linear-gradient(135deg, rgba(37,99,235,0.05) 0%, rgba(124,58,237,0.05) 100%);
        border: 1px solid rgba(37,99,235,0.15);
        border-radius: 14px;
        padding: 16px 18px;
        margin-bottom: 20px;
    }}
    .summary-label {{
        font-size: 0.75rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--accent-color);
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 6px;
    }}
    .summary-text {{
        font-size: 0.95rem;
        line-height: 1.7;
        color: var(--text-primary);
    }}
    
    /* Toggle Buttons */
    .view-toggle {{
        display: flex;
        gap: 8px;
        margin-bottom: 16px;
    }}
    .toggle-btn {{
        flex: 1;
        padding: 10px 14px;
        border-radius: 10px;
        border: 1px solid var(--border-color);
        background: var(--card-bg);
        color: var(--text-secondary);
        font-weight: 700;
        font-size: 0.85rem;
        cursor: pointer;
        transition: all 0.2s ease;
    }}
    .toggle-btn.active {{
        background: var(--accent-gradient);
        color: #fff;
        border-color: transparent;
    }}
"""

BOOKMARK_JS = """
<script>
function getFavs() {
    try {
        return JSON.parse(localStorage.getItem('news_favs') || '[]');
    } catch(e) { return []; }
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
        if (url) {
            btn.innerHTML = isFav(url) ? '⭐' : '📌';
        }
    });
    const countEl = document.getElementById('fav-count');
    if (countEl) countEl.innerText = getFavs().length;
}
document.addEventListener('DOMContentLoaded', updateFavBtns);
</script>
"""

GLOBAL_JS = """
<script>
// --- MODE SOMBRE MANUEL ---
function initTheme() {
    const saved = localStorage.getItem('pulsehub_theme');
    if (saved === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else if (saved === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const isDark = current === 'dark' || 
        (!current && window.matchMedia('(prefers-color-scheme: dark)').matches);
    
    if (isDark) {
        document.documentElement.setAttribute('data-theme', 'light');
        localStorage.setItem('pulsehub_theme', 'light');
    } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('pulsehub_theme', 'dark');
    }
    updateThemeBtn();
}

function updateThemeBtn() {
    const btn = document.getElementById('theme-toggle');
    if (btn) {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark' ||
            (!document.documentElement.getAttribute('data-theme') && 
             window.matchMedia('(prefers-color-scheme: dark)').matches);
        btn.innerHTML = isDark ? '☀️' : '🌙';
    }
}

// --- RECHERCHE ---
function searchArticles(query) {
    if (!query || query.length < 2) return;
    window.location.href = '/search?q=' + encodeURIComponent(query);
}

// --- PARTAGE SOCIAL ---
function shareArticle(platform, url, title) {
    const encodedUrl = encodeURIComponent(url);
    const encodedTitle = encodeURIComponent(title);
    let shareUrl = '';
    
    switch(platform) {
        case 'twitter':
            shareUrl = 'https://twitter.com/intent/tweet?url=' + encodedUrl + '&text=' + encodedTitle;
            break;
        case 'facebook':
            shareUrl = 'https://www.facebook.com/sharer/sharer.php?u=' + encodedUrl;
            break;
        case 'whatsapp':
            shareUrl = 'https://wa.me/?text=' + encodedTitle + '%20' + encodedUrl;
            break;
        case 'telegram':
            shareUrl = 'https://t.me/share/url?url=' + encodedUrl + '&text=' + encodedTitle;
            break;
        case 'linkedin':
            shareUrl = 'https://www.linkedin.com/sharing/share-offsite/?url=' + encodedUrl;
            break;
        case 'copy':
            navigator.clipboard.writeText(url).then(() => {
                alert('Link copied to clipboard!');
            });
            return;
    }
    
    if (shareUrl) {
        window.open(shareUrl, '_blank', 'width=600,height=400');
    }
}

// --- PWA ---
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    updateThemeBtn();
    
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                searchArticles(searchInput.value);
            }
        });
    }
});
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

def resolve_real_url(url):
    if "news.google.com" not in url:
        return url
    try:
        headers = get_random_headers()
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=4)
        if resp.status_code == 200:
            if "news.google.com" not in resp.url:
                return resp.url
            m = re.search(r'data-n-au=["\']([^"\']+)["\']', resp.text)
            if m:
                return m.group(1)
            m2 = re.search(r'<a[^>]+href=["\'](https?://(?!news\.google\.com)[^"\']+)["\']', resp.text)
            if m2:
                return m2.group(1)
    except Exception:
        pass
    return url

def translate_to_english(text):
    if not text or len(text.strip()) == 0:
        return text
    
    try:
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
    except Exception:
        return text

def fetch_single_feed(source_name, feed_url):
    items = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:8]:
            dt, formatted_date = parse_and_filter_date(entry)
            if formatted_date is None:
                continue
                
            img_url = extract_image_from_entry(entry)
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary_clean = re.sub(r'<[^>]+>', '', summary_raw).strip()
            title_clean = html.escape(entry.title)
            
            items.append({
                "dt": dt or datetime.now(timezone.utc),
                "title": title_clean,
                "source": html.escape(source_name),
                "date": formatted_date,
                "img": img_url or "",
                "summary": summary_clean,
                "safe_url": quote(entry.link, safe=""),
                "safe_title": quote(entry.title, safe=""),
                "safe_summary": quote(summary_clean, safe=""),
                "raw_url": entry.link
            })
    except Exception:
        pass
    return items

def get_all_articles():
    """Récupère tous les articles de toutes les catégories."""
    all_articles = []
    for cat_key, cat_info in CATEGORIES.items():
        cached_data = CACHE_FEEDS.get(cat_key)
        if cached_data:
            all_articles.extend(cached_data)
        else:
            articles = []
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(fetch_single_feed, s_name, f_url) 
                    for s_name, f_url in cat_info["feeds"].items()
                ]
                for future in as_completed(futures):
                    articles.extend(future.result())
            articles.sort(key=lambda x: x["dt"], reverse=True)
            CACHE_FEEDS.set(cat_key, articles)
            all_articles.extend(articles)
    return all_articles

@app.route("/")
def index():
    today = datetime.now().strftime("%A, %B %d, %Y")
    
    cat_cards = "".join([f'''
    <a class="cat-card" href="/category?cat={cat_key}">
        <div class="cat-icon">{cat['icon']}</div>
        <div class="cat-title">{html.escape(cat['name'])}</div>
    </a>
    ''' for cat_key, cat in CATEGORIES.items()])

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PulseHub - Global News</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#2563eb">
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()">🌙</button>
        
        <header class="brand-header">
            {MASCOT_SVG}
            <h1 class="brand-title">PulseHub</h1>
            <p class="brand-sub">{today}</p>
        </header>

        <div class="search-container">
            <span class="search-icon">🔍</span>
            <input type="text" id="search-input" class="search-input" placeholder="Search articles..." />
        </div>

        <a class="fav-banner" href="/favorites">
            <span>⭐ Read Later (Bookmarks)</span>
            <span id="fav-count" style="background: var(--accent-gradient); color: #fff; padding: 3px 11px; border-radius: 12px; font-size: 0.85rem;">0</span>
        </a>

        <h2 style="font-size: 1.1rem; margin-bottom: 14px; color: var(--text-secondary); font-weight: 700;">Categories</h2>
        <div class="category-grid">
            {cat_cards}
        </div>
        {BOOKMARK_JS}
        {GLOBAL_JS}
    </body>
    </html>
    """
    return render_template_string(html_content)

@app.route("/category")
def category():
    cat_key = request.args.get("cat")
    if not cat_key or cat_key not in CATEGORIES:
        return "Category not found.", 404
        
    cat_info = CATEGORIES[cat_key]
    
    cached_data = CACHE_FEEDS.get(cat_key)
    if cached_data:
        articles = cached_data
    else:
        articles = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(fetch_single_feed, s_name, f_url) 
                for s_name, f_url in cat_info["feeds"].items()
            ]
            for future in as_completed(futures):
                articles.extend(future.result())

        articles.sort(key=lambda x: x["dt"], reverse=True)
        CACHE_FEEDS.set(cat_key, articles)

    articles_html = ""
    for a in articles:
        img_tag = f'<img class="card-thumb" src="{html.escape(a["img"])}" loading="lazy" alt="" />' if a["img"] else ''
        
        js_title = quote(a['title'], safe='')
        js_summary = quote(a['summary'], safe='')
        js_url = quote(a['raw_url'], safe='')

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
                <button class="btn-fav" data-url="{html.escape(a['raw_url'])}" onclick="toggleFav('{js_url}', '{js_title}', '{html.escape(a['source'])}', '{a['date']}', '{cat_key}', '{html.escape(a['img'])}', '{js_summary}')">📌</button>
            </div>
        </div>
        '''

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{html.escape(cat_info['name'])} - PulseHub</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#2563eb">
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()">🌙</button>
        
        <a class="back" href="/">&larr; All Categories</a>
        <header style="text-align: left; margin-bottom: 24px;">
            <div style="font-size: 2.4rem; margin-bottom: 6px;">{cat_info['icon']}</div>
            <h1 style="font-size: 1.8rem; font-weight: 800;">{html.escape(cat_info['name'])}</h1>
            <p style="color: var(--text-secondary); font-size: 0.85rem;">Published in the last 48 hours</p>
        </header>

        <div class="articles-list">
            {articles_html if articles else '<p style="color: var(--text-secondary);">No articles published in the last 48 hours.</p>'}
        </div>
        {BOOKMARK_JS}
        {GLOBAL_JS}
    </body>
    </html>
    """
    return render_template_string(html_content)

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
    
    cached_trans = CACHE_TRANSLATIONS.get(target_url)
    if cached_trans:
        translated_title, translated_content = cached_trans
    else:
        cached_art = CACHE_ARTICLES.get(target_url)
        if cached_art:
            raw_content = cached_art
        else:
            raw_content = fetch_clean_article(target_url, summary_fallback)
            CACHE_ARTICLES.set(target_url, raw_content)
            
        translated_title = translate_to_english(title)
        translated_content = translate_to_english(raw_content)
        
        CACHE_TRANSLATIONS.set(target_url, (translated_title, translated_content))
    
    # Résumé extractif (TextRank)
    cached_summary = CACHE_SUMMARIES.get(target_url)
    if cached_summary is not None:
        ai_summary = cached_summary
    else:
        ai_summary = generate_summary(translated_content)
        CACHE_SUMMARIES.set(target_url, ai_summary)
    
    back_url = f"/category?cat={cat_key}" if cat_key else "/"
    
    if ai_summary:
        summary_html = f"""
        <div class="summary-box">
            <div class="summary-label">⚡ AI Summary</div>
            <div class="summary-text">{html.escape(ai_summary)}</div>
        </div>
        """
    else:
        summary_html = ""
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{html.escape(translated_title)}</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#2563eb">
        <style>
            {COMMON_CSS}
            body {{ background: var(--card-bg); }}
            .top-bar {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--border-color); }}
            .audio-btn {{ background: var(--bg-color); border: 1px solid var(--border-color); padding: 8px 16px; border-radius: 10px; color: var(--text-primary); cursor: pointer; font-weight: 700; font-size: 0.85rem; }}
            article {{ font-size: 1.08rem; line-height: 1.85; color: var(--text-primary); margin-top: 20px; white-space: pre-line; }}
            h1 {{ font-size: 1.6rem; line-height: 1.35; margin-bottom: 12px; font-weight: 800; }}
            .actions {{ margin-top: 28px; padding-top: 18px; border-top: 1px solid var(--border-color); text-align: center; display: flex; justify-content: center; gap: 12px; }}
        </style>
    </head>
    <body>
        <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()">🌙</button>
        
        <div class="top-bar">
            <a class="back" style="margin-bottom:0;" href="{back_url}">&larr; Back to Feed</a>
            <button id="speech-btn" class="audio-btn" onclick="toggleAudio()">🔊 Listen</button>
        </div>

        <header style="text-align: left; padding-bottom: 12px;">
            <h1>{html.escape(translated_title)}</h1>
        </header>

        {summary_html}

        <div class="view-toggle">
            <button class="toggle-btn active" onclick="showSummary()">⚡ Summary</button>
            <button class="toggle-btn" onclick="showFull()">📄 Full Article</button>
        </div>

        <article id="article-body">{html.escape(translated_content)}</article>

        <div class="actions">
            <a class="btn-outline" href="{html.escape(target_url)}" target="_blank" rel="noopener">View Original ↗</a>
            <button class="btn-fav" data-url="{html.escape(target_url)}" onclick="toggleFav('{quote(target_url, safe='')}', '{quote(title, safe='')}', 'Source', '', '{cat_key}', '', '{quote(summary_fallback, safe='')}')">📌</button>
        </div>

        <div class="share-buttons">
            <button class="share-btn" onclick="shareArticle('twitter', '{html.escape(target_url)}', '{html.escape(translated_title)}')">𝕏 Twitter</button>
            <button class="share-btn" onclick="shareArticle('facebook', '{html.escape(target_url)}', '{html.escape(translated_title)}')">📘 Facebook</button>
            <button class="share-btn" onclick="shareArticle('whatsapp', '{html.escape(target_url)}', '{html.escape(translated_title)}')">💬 WhatsApp</button>
            <button class="share-btn" onclick="shareArticle('telegram', '{html.escape(target_url)}', '{html.escape(translated_title)}')">✈️ Telegram</button>
            <button class="share-btn" onclick="shareArticle('linkedin', '{html.escape(target_url)}', '{html.escape(translated_title)}')">💼 LinkedIn</button>
            <button class="share-btn" onclick="shareArticle('copy', '{html.escape(target_url)}', '{html.escape(translated_title)}')">📋 Copy</button>
        </div>

        {BOOKMARK_JS}
        {GLOBAL_JS}
        <script>
            let synth = window.speechSynthesis;
            let speechChunks = [];
            let currentChunk = 0;
            let isSpeaking = false;

            function stopAudio() {{
                synth.cancel();
                isSpeaking = false;
                document.getElementById('speech-btn').innerHTML = "🔊 Listen";
            }};

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

            function showSummary() {{
                document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
                event.target.classList.add('active');
                const summaryBox = document.querySelector('.summary-box');
                const article = document.getElementById('article-body');
                if (summaryBox) summaryBox.style.display = 'block';
                article.style.display = 'none';
            }}

            function showFull() {{
                document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
                event.target.classList.add('active');
                const summaryBox = document.querySelector('.summary-box');
                const article = document.getElementById('article-body');
                if (summaryBox) summaryBox.style.display = 'none';
                article.style.display = 'block';
            }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html_content)

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return "No search query.", 400
    
    cached_results = CACHE_SEARCH.get(query)
    if cached_results is not None:
        results = cached_results
    else:
        all_articles = get_all_articles()
        query_lower = query.lower()
        results = []
        for a in all_articles:
            title_lower = a["title"].lower()
            summary_lower = a["summary"].lower()
            if query_lower in title_lower or query_lower in summary_lower:
                results.append(a)
        CACHE_SEARCH.set(query, results)
    
    results_html = ""
    for a in results:
        img_tag = f'<img class="card-thumb" src="{html.escape(a["img"])}" loading="lazy" alt="" />' if a["img"] else ''
        
        js_title = quote(a['title'], safe='')
        js_summary = quote(a['summary'], safe='')
        js_url = quote(a['raw_url'], safe='')

        results_html += f'''
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
                <a class="btn" href="/article?url={a['safe_url']}&title={a['safe_title']}&cat=&summary={a['safe_summary']}">Read Article</a>
                <button class="btn-fav" data-url="{html.escape(a['raw_url'])}" onclick="toggleFav('{js_url}', '{js_title}', '{html.escape(a['source'])}', '{a['date']}', '', '{html.escape(a['img'])}', '{js_summary}')">📌</button>
            </div>
        </div>
        '''

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Search: {html.escape(query)} - PulseHub</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#2563eb">
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()">🌙</button>
        
        <a class="back" href="/">&larr; Home</a>
        <header style="text-align: left; margin-bottom: 24px;">
            <h1 style="font-size: 1.8rem; font-weight: 800;">🔍 Search Results</h1>
            <p style="color: var(--text-secondary); font-size: 0.85rem;">{len(results)} results for "{html.escape(query)}"</p>
        </header>

        <div class="articles-list">
            {results_html if results else '<p style="color: var(--text-secondary);">No articles found.</p>'}
        </div>
        {BOOKMARK_JS}
        {GLOBAL_JS}
    </body>
    </html>
    """
    return render_template_string(html_content)

@app.route("/favorites")
def favorites():
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Saved Articles - PulseHub</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#2563eb">
        <style>{COMMON_CSS}</style>
    </head>
    <body>
        <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()">🌙</button>
        
        <a class="back" href="/">&larr; Home</a>
        <header style="text-align: left; margin-bottom: 24px;">
            <h1 style="font-size: 1.8rem; font-weight: 800;">⭐ Saved Articles</h1>
            <p style="color: var(--text-secondary); font-size: 0.85rem;">Read later</p>
        </header>

        <div id="favs-list"></div>

        {BOOKMARK_JS}
        {GLOBAL_JS}
        <script>
            function renderFavs() {
                const favs = getFavs();
                const container = document.getElementById('favs-list');
                if (favs.length === 0) {
                    container.innerHTML = '<p style="color: var(--text-secondary);">No saved articles yet.</p>';
                    return;
                }
                
                let html = '';
                favs.forEach(a => {
                    const title = decodeURIComponent(a.title);
                    const safeTitle = encodeURIComponent(title);
                    const safeUrl = encodeURIComponent(a.url);
                    const safeSummary = a.summary || '';
                    const imgTag = a.img ? `<img class="card-thumb" src="${a.img}" loading="lazy" alt="" />` : '';
                    
                    html += `
                    <div class="card">
                        <div class="card-body-layout">
                            ${imgTag}
                            <div class="card-main">
                                <div class="card-meta">
                                    <span class="tag">${a.source}</span>
                                    <span class="date">${a.date}</span>
                                </div>
                                <div class="card-title">${title}</div>
                            </div>
                        </div>
                        <div class="card-actions">
                            <a class="btn" href="/article?url=${safeUrl}&title=${safeTitle}&cat=${a.cat}&summary=${safeSummary}">Read Article</a>
                            <button class="btn-fav" onclick="removeFav('${a.url}')">🗑️</button>
                        </div>
                    </div>
                    `;
                });
                container.innerHTML = html;
            }

            function removeFav(url) {
                let favs = getFavs();
                favs = favs.filter(item => item.url !== url);
                localStorage.setItem('news_favs', JSON.stringify(favs));
                renderFavs();
            }

            document.addEventListener('DOMContentLoaded', renderFavs);
        </script>
    </body>
    </html>
    """
    return render_template_string(html_content)

# --- PWA ROUTES ---
@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "PulseHub - Global News",
        "short_name": "PulseHub",
        "description": "Global news aggregator with AI summaries",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f8fafc",
        "theme_color": "#2563eb",
        "icons": [
            {
                "src": "/static/icon-192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/static/icon-512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    })

@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js"), 200, {"Content-Type": "application/javascript"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
