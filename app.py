import os
import feedparser
import trafilatura
from flask import Flask, render_template_string

app = Flask(__name__)

# Flux RSS de test pour valider le fonctionnement
TEST_FEED_URL = "https://www.clubic.com/feed/news.rss"

@app.route("/")
def index():
    feed = feedparser.parse(TEST_FEED_URL)
    articles = []
    
    # Récupération des 5 premiers articles
    for entry in feed.entries[:5]:
        published_date = entry.get("published", entry.get("updated", "Date inconnue"))
        source_name = feed.feed.get("title", "Source d'actualité")
        
        articles.append({
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
        <title>Mon Agrégateur</title>
        <style>
            body { font-family: sans-serif; max-width: 600px; margin: 20px auto; padding: 0 10px; background: #f9f9f9; }
            .card { background: white; padding: 15px; margin-bottom: 12px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
            h2 { margin-top: 0; font-size: 1.1rem; color: #111; }
            .meta { font-size: 0.85rem; color: #666; }
        </style>
    </head>
    <body>
        <h1>Actualités Tech</h1>
        {% for a in articles %}
            <div class="card">
                <h2>{{ a.title }}</h2>
                <div class="meta">Source: <strong>{{ a.source }}</strong> | {{ a.date }}</div>
            </div>
        {% endfor %}
    </body>
    </html>
    """
    return render_template_string(html_template, articles=articles)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
