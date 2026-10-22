# Builds a static copy of The Daily Headlines for GitHub Pages.
# GitHub Pages can't run Python, so a GitHub Action runs this every 6 hours:
# it fetches the news (using the same code as app.py) and writes plain files
# into the _site folder, which GitHub then publishes.
#
# Run locally:  python3 static_site/build.py   then open _site/index.html

import os
import sys
import json
import shutil
from datetime import datetime, timezone

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
sys.path.insert(0, root)

import app   # importing fetches the news and creates assets/wordcloud.png

site = os.path.join(root, "_site")
os.makedirs(site, exist_ok = True)

data = {
    "printedAt": datetime.now(timezone.utc).isoformat(),
    "categories": app.categories,
    "articles": app.initial_news["articles"],
}

with open(os.path.join(site, "news_data.js"), "w") as f:
    f.write("const NEWS = " + json.dumps(data) + ";\n")

shutil.copy(os.path.join(root, "assets", "style.css"), os.path.join(site, "style.css"))
shutil.copy(os.path.join(root, "assets", "wordcloud.png"), os.path.join(site, "wordcloud.png"))
shutil.copy(os.path.join(here, "index.html"), os.path.join(site, "index.html"))

print(f"Built _site/ with {len(data['articles'])} articles")
