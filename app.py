import os
import feedparser
import trafilatura
from flask import Flask, render_template_string, request

app = Flask(__name__)

TEST_FEED_URL = "https://www.clubic.com/feed/news.rss"

def get_clean_article(url):
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        # Extraction du texte brut, sans liens annexes ni pubs
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
    feed = feedparser.parse(TEST_FEED_URL)
    articles = []
    
    for idx, entry in enumerate(feed.entries[:10]):
        # Conservation stricte de la date de publication d'origine
        published_date = entry.get("published", entry.get("updated", "Date inconnue"))
        source_name = feed.feed.get("title", "Source d'actualité")
        
        articles.append({
            "id": idx,
            "title": entry.title,
            "source": source_name,
            "date": published_date,
            "link": entry.link
        })
        
    html_template = """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Flux Tech</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 650px; margin: 20px auto; padding: 0 15px; background: #f4f4f7; color: #222; }
            h1 { text-align: center; font-size: 1.4rem; color: #111; margin-bottom: 20px; }
            .card { background: white; padding: 16px; margin-bottom: 12px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
            .card h2 { margin: 0 0 8px 0; font-size: 1.1rem; line-height: 1.4; }
            .meta { font-size: 0.8rem; color: #666; margin-bottom: 10px; }
            .btn { display: inline-block; padding: 6px 12px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; font-size: 0.85rem; }
        </style>
    </head>
    <body>
        <h1>Flux Actualités Tech</h1>
        {% for a in articles %}
            <div class="card">
                <h2>{{ a.title }}</h2>
                <div class="meta">Source : <strong>{{ a.source }}</strong> | {{ a.date }}</div>
                <a class="btn" href="/article?url={{ a.link }}&title={{ a.title }}&date={{ a.date }}&source={{ a.source }}">Lire l'article nettoyé</a>
            </div>
        {% endfor %}
    </body>
    </html>
    """
    return render_template_string(html_template, articles=articles)

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
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 650px; margin: 20px auto; padding: 0 15px; background: #fff; color: #111; line-height: 1.6; }
            .back { display: inline-block; margin-bottom: 15px; color: #007bff; text-decoration: none; font-weight: 500; }
            h1 { font-size: 1.5rem; margin-bottom: 8px; line-height: 1.3; }
            .meta { font-size: 0.85rem; color: #666; border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 20px; }
            .content { font-size: 1rem; white-space: pre-line; }
        </style>
    </head>
    <body>
        <a class="back" href="/">&larr; Retour au flux</a>
        <h1>{{ title }}</h1>
        <div class="meta">Source : <strong>{{ source }}</strong> | Date d'origine : {{ date }}</div>
        <div class="content">{{ content }}</div>
    </body>
    </html>
    """
    return render_template_string(html_template, title=title, source=source, date=date, content=content)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
