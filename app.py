import os
import feedparser
import trafilatura
from flask import Flask, render_template_string, request

app = Flask(__name__)

# Liste de vos flux RSS
FEEDS = {
    "Clubic (Tech)": "https://www.clubic.com/feed/news.rss",
    "Le Monde (Actu)": "https://www.lemonde.fr/rss/une.xml",
    "Frandroid (Tech)": "https://www.frandroid.com/feed"
}

def get_clean_article(url):
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        text = trafilatura.extract(
            downloaded, 
            include_images=True, 
            include_links=False, 
            output_format="txt"
        )
        return text or "Impossible d'extraire le contenu texte de cet article."
    return "Erreur lors de la récupération de la page source."

@app.route("/")
def index():
    all_articles = []
    
    for source_label, feed_url in FEEDS.items():
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:3]: # 3 derniers articles par source
            published_date = entry.get("published", entry.get("updated", "Date inconnue"))
            all_articles.append({
                "title": entry.title,
                "source": source_label,
                "date": published_date,
                "link": entry.link
            })

    html_template = """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Mon Agrégateur</title>
        <style>
            * { box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 15px; background: #f2f2f7; color: #1c1c1e; }
            h1 { font-size: 1.5rem; text-align: center; margin-bottom: 20px; }
            .card { background: #ffffff; padding: 16px; margin-bottom: 12px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
            .tag { display: inline-block; background: #e5e5ea; font-size: 0.75rem; padding: 3px 8px; border-radius: 6px; font-weight: 600; margin-bottom: 8px; color: #3a3a3c; }
            .title { font-size: 1.05rem; font-weight: 600; margin: 0 0 8px 0; line-height: 1.35; }
            .date { font-size: 0.78rem; color: #8e8e93; margin-bottom: 12px; }
            .btn { display: block; text-align: center; padding: 10px; background: #007aff; color: #fff; text-decoration: none; border-radius: 8px; font-weight: 500; font-size: 0.9rem; }
        </style>
    </head>
    <body>
        <h1>Mon Agrégateur</h1>
        {% for a in articles %}
            <div class="card">
                <span class="tag">{{ a.source }}</span>
                <div class="title">{{ a.title }}</div>
                <div class="date">Publié le : {{ a.date }}</div>
                <a class="btn" href="/article?url={{ a.link }}&title={{ a.title }}&date={{ a.date }}&source={{ a.source }}">Lire l'article nettoyé</a>
            </div>
        {% endfor %}
    </body>
    </html>
    """
    return render_template_string(html_template, articles=all_articles)

@app.route("/article")
def article():
    url = request.args.get("url")
    title = request.args.get("title", "Article")
    date = request.args.get("date", "")
    source = request.args.get("source", "")
    
    content = get_clean_article(url)
    
    html_template = """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ title }}</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 15px; background: #fff; color: #1c1c1e; line-height: 1.6; }
            .back { display: inline-block; margin-bottom: 15px; color: #007aff; text-decoration: none; font-weight: 600; font-size: 0.95rem; }
            h1 { font-size: 1.4rem; margin-bottom: 6px; line-height: 1.3; }
            .meta { font-size: 0.8rem; color: #8e8e93; border-bottom: 1px solid #e5e5ea; padding-bottom: 12px; margin-bottom: 16px; }
            .content { font-size: 1rem; white-space: pre-line; }
        </style>
    </head>
    <body>
        <a class="back" href="/">&larr; Retour au flux</a>
        <h1>{{ title }}</h1>
        <div class="meta">Source : <strong>{{ source }}</strong> | {{ date }}</div>
        <div class="content">{{ content }}</div>
    </body>
    </html>
    """
    return render_template_string(html_template, title=title, source=source, date=date, content=content)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
