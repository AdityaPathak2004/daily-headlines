# The Daily Headlines: a newspaper-style news app built with Dash
# Run:  python3 app.py   then open http://127.0.0.1:8050 in your browser
# Online: static_site/build.py turns this into a static page for GitHub Pages

import os
import json
from datetime import datetime, timezone
from dash import Dash, dcc, html, Input, Output, State, ALL, ctx, no_update
from newsapi import NewsApiClient
from wordcloud import WordCloud, STOPWORDS
from google import genai
from google.genai import types

# Load NEWSAPI_KEY from the .env file next to this script (keeps the key out of the code)
_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env):
    for _line in open(_env):
        if '=' in _line:
            _k, _v = _line.strip().split('=', 1)
            os.environ.setdefault(_k, _v)

newsapi = NewsApiClient(api_key=os.environ.get('NEWSAPI_KEY'))

# Google Gemini (generative AI). If there's no GEMINI_API_KEY, the AI parts are simply hidden.
GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-2.5-flash"]   # tried in order (backup if one is busy)
gemini = None
if os.environ.get("GEMINI_API_KEY"):
    gemini = genai.Client(api_key = os.environ["GEMINI_API_KEY"],
                          http_options = types.HttpOptions(timeout = 60_000))   # milliseconds

categories = ['business', 'entertainment', 'health', 'science', 'sports', 'technology', 'general']


# ---------- Data: get headlines from NewsAPI ----------
def fetch_news():
    articles = []
    seen_urls = set()
    for cat in categories:
        for article in newsapi.get_top_headlines(category = cat, country = "us")["articles"]:
            # Skip duplicates (the same story is often in "general" and another category)
            if article["url"] in seen_urls:
                continue
            seen_urls.add(article["url"])
            articles.append({
                "category": cat,
                "title": article["title"].rsplit(" - ", 1)[0],   # remove publisher name at the end
                "description": article["description"] or "",
                "source": article["source"]["name"],
                "author": (article["author"] or "").split(",")[0],
                "url": article["url"],
                "image": article["urlToImage"] or "",
                "publishedAt": article["publishedAt"],
            })
    articles.sort(key = lambda a: a["publishedAt"], reverse = True)   # newest first
    make_wordcloud(articles)
    return {"fetchedAt": datetime.now().strftime("%b %d, %Y %I:%M %p"),
            "briefing": ai_briefing(articles),
            "version": int(datetime.now().timestamp()),   # changes on every fetch so the browser reloads the image
            "articles": articles}


# ---------- Generative AI (Gemini) ----------
def headlines_for_ai(articles):
    # Number every story so Gemini can point back to the ones it used
    return "\n".join(f"[{i}] ({a['category']}, {a['source']}) {a['title']}. {a['description']}"
                     for i, a in enumerate(articles))


def ask_gemini(prompt, schema):
    # Ask Gemini for JSON in a fixed shape, so the answer is easy to use in Python
    for model in GEMINI_MODELS:
        try:
            response = gemini.models.generate_content(
                model = model,
                contents = prompt,
                config = types.GenerateContentConfig(response_mime_type = "application/json", response_schema = schema),
            )
            return json.loads(response.text)
        except Exception as error:
            last_error = error
            print(f"Gemini model {model} failed, trying the next one:", str(error)[:120])
    raise last_error


def ai_briefing(articles):
    # Front-page summary written by Gemini. Returns None if AI is off or fails.
    if gemini is None:
        return None
    prompt = ("You are the editor of a newspaper. Using ONLY these headlines, write today's front-page briefing.\n"
              "- title: a punchy newspaper-style headline (max 10 words) naming the day's biggest story\n"
              "- overview: 3-4 sentences covering the most important stories, with specific names, companies "
              "and numbers from the headlines. No vague filler like 'various developments' or 'headwinds'.\n"
              "- key_points: 4 one-sentence points, each about a different specific story from a different section.\n"
              "Be factual and neutral; don't invent details that aren't in the headlines.\n\n" + headlines_for_ai(articles))
    schema = {"type": "OBJECT",
              "properties": {"title": {"type": "STRING"},
                             "overview": {"type": "STRING"},
                             "key_points": {"type": "ARRAY", "items": {"type": "STRING"}}},
              "required": ["title", "overview", "key_points"]}
    try:
        return ask_gemini(prompt, schema)
    except Exception as error:
        print("Gemini briefing failed:", error)
        return None


def ai_answer(question, articles):
    # Answer a reader's question using only today's stories
    prompt = ("Answer the reader's question using ONLY the news stories below. Keep it to 2-4 sentences. "
              "If the stories don't cover it, say so. List the numbers of the stories you used.\n\n"
              f"Question: {question}\n\nStories:\n{headlines_for_ai(articles)}")
    schema = {"type": "OBJECT",
              "properties": {"answer": {"type": "STRING"},
                             "sources": {"type": "ARRAY", "items": {"type": "INTEGER"}}},
              "required": ["answer", "sources"]}
    return ask_gemini(prompt, schema)


# ---------- Word cloud of all headlines, saved to assets/wordcloud.png ----------
# (Dash automatically serves anything inside the "assets" folder)
assets_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

stopwords = set(STOPWORDS) | {
    "says", "new", "will", "one", "first", "may", "us", "s", "vs", "get", "year", "years",
    "now", "live", "time", "day", "week", "month", "today", "show", "made", "much", "way",
    "big", "best", "take", "set", "two", "four", "five", "second", "latest", "ahead", "face",
    "real", "thing", "kind", "whether", "went", "need", "full", "help", "mean", "update",
    "see", "coming", "top", "amid", "days", "open", "bring",
}

# Newspaper ink colours: mostly black and grey, with the odd word in red
def ink_color(word, font_size, position, orientation, random_state = None, **kwargs):
    if random_state.random() < 0.15:
        return "#9b1c1c"
    return random_state.choice(["#1b1a17", "#2e2b26", "#4a463e", "#625c51"])


# Newspaper-style font: Georgia on macOS, DejaVu Serif on Linux (GitHub Actions)
serif_font = next((f for f in ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
                               "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"] if os.path.exists(f)), None)

def make_wordcloud(articles):
    os.makedirs(assets_folder, exist_ok = True)
    text = " ".join(a["title"] for a in articles)
    WordCloud(
        width = 1200,
        height = 380,
        background_color = "#f4eee2",        # same as the paper colour
        color_func = ink_color,
        font_path = serif_font,
        prefer_horizontal = 0.95,
        stopwords = stopwords,
        max_words = 90,
        collocations = False,
        regexp = r"[A-Za-z][A-Za-z0-9&]*",   # keeps words like "AT&T" in one piece
        min_word_length = 2,
    ).generate(text).to_file(os.path.join(assets_folder, "wordcloud.png"))


def time_ago(published_at):
    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    hours = int((datetime.now(timezone.utc) - published).total_seconds() // 3600)
    if hours < 1:
        return "just now"
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


# ---------- Building blocks for one story ----------
# (All colours, fonts and animations live in assets/style.css)
def story_photo(article):
    if article["image"]:
        return html.Div(html.Img(src = article["image"], alt = article["source"]), className = "photo")
    return html.Div(html.Div(article["source"], className = "no-photo"), className = "photo")


def byline(article):
    author = f"By {article['author']} · " if article["author"] else ""
    return html.Div([
        html.Span([author, html.B(article["source"])]),
        html.Span(time_ago(article["publishedAt"])),
    ], className = "byline")


def lead_story(article):
    return html.A([
        html.Div([
            story_photo(article),
            html.Div(f"Photo via {article['source']}", className = "caption"),
        ]),
        html.Div([
            html.Span(f"Top Story · {article['category']}", className = "kicker"),
            html.H2(article["title"]),
            html.P(article["description"], className = "desc"),
            byline(article),
        ]),
    ], href = article["url"], target = "_blank", className = "lead")


def story_card(article):
    return html.A([
        story_photo(article),
        html.Span(article["category"], className = "kicker"),
        html.H3(article["title"]),
        html.P(article["description"][:150], className = "desc"),
        byline(article),
    ], href = article["url"], target = "_blank", className = "story")


def ticker_items(articles):
    # The list is repeated twice so the scrolling loop looks seamless
    items = [html.A(a["title"], href = a["url"], target = "_blank", className = "ticker-item")
             for a in articles[:12]]
    return items + items


# ---------- Page layout ----------
fonts = "https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&family=UnifrakturMaguntia&display=swap"
app = Dash(__name__, title = "The Daily Headlines", external_stylesheets = [fonts])

today = datetime.now().strftime("%A, %B %d, %Y")
initial_news = fetch_news()   # also used by static_site/build.py for the GitHub Pages version

app.layout = html.Div([
    dcc.Store(id = "news", data = initial_news),     # all the articles
    dcc.Store(id = "category", data = "all"),        # which section is selected

    html.Div([
        html.Span(today),
        dcc.Input(id = "search", type = "text", placeholder = "Search the paper...", className = "search"),
        html.Button("↻ Latest edition", id = "refresh", className = "refresh"),
    ], className = "top-strip"),

    html.Header([
        html.H1("The Daily Headlines"),
        html.Div("“All the news that's fit to print, fetched with Python.”", className = "motto"),
        html.Div([
            html.Span("EAS503 Edition"),
            html.Span(id = "updated"),
            html.Span("Price: Free"),
        ], className = "edition-bar"),
    ], className = "masthead"),

    html.Nav(id = "tabs", className = "nav"),

    html.Div([
        html.Span("Latest", className = "ticker-label"),
        html.Div(html.Div(id = "ticker", className = "ticker-track"), className = "ticker-window"),
    ], className = "ticker"),

    html.Div(id = "featured", style = {"marginTop": "24px"}),

    html.Div(id = "briefing"),

    html.Div([
        html.Div("Ask the Editor", className = "section-title"),
        html.Div([
            dcc.Input(id = "question", type = "text", className = "ask-input", debounce = False,
                      placeholder = "Ask about today's news, e.g. \"What's happening with AI?\""),
            html.Button("Ask", id = "ask", className = "refresh"),
        ], className = "ask-row"),
        dcc.Loading(html.Div(id = "answer"), type = "dot", color = "#9b1c1c"),
    ], style = {"display": "block" if gemini else "none"}),

    html.Div("In the Headlines", className = "section-title"),
    html.Div(html.Img(id = "wordcloud", src = "assets/wordcloud.png", alt = "Word cloud of headlines"),
             className = "wordcloud-box"),

    html.Div("More Stories", className = "section-title"),
    html.Div(id = "grid", className = "columns"),

    html.Footer("EAS503 · News app prototype built with Dash · Data from NewsAPI.org", className = "footer"),
], className = "page")


# ---------- Callbacks (what happens when you click or type) ----------

# Refresh button: download the latest headlines (uses 7 of your 100 free requests a day)
@app.callback(Output("news", "data"), Input("refresh", "n_clicks"), prevent_initial_call = True)
def refresh_news(n_clicks):
    return fetch_news()


# Category buttons: remember which one was clicked
@app.callback(Output("category", "data"),
              Input({"type": "tab", "index": ALL}, "n_clicks"), prevent_initial_call = True)
def pick_category(clicks):
    if not any(clicks):
        return no_update
    return ctx.triggered_id["index"]


# Editor's Briefing (written by Gemini when the news is fetched)
@app.callback(Output("briefing", "children"), Input("news", "data"))
def show_briefing(news):
    briefing = news.get("briefing")
    if not briefing:
        return None
    return html.Div([
        html.Div("Editor's Briefing", className = "kicker"),
        html.H3(briefing["title"]),
        html.P(briefing["overview"], className = "briefing-overview"),
        html.Div("What to know", className = "briefing-label"),
        html.Ul([html.Li(point) for point in briefing["key_points"]]),
        html.Div("Summarised by Google Gemini from today's headlines. AI can make mistakes.",
                 className = "ai-note"),
    ], className = "briefing")


# Ask the Editor: Gemini answers questions about today's stories
@app.callback(Output("answer", "children"),
              Input("ask", "n_clicks"), Input("question", "n_submit"),
              State("question", "value"), State("news", "data"), prevent_initial_call = True)
def answer_question(n_clicks, n_submit, question, news):
    if not question or not question.strip():
        return html.P("Type a question first.", className = "ai-note")
    try:
        result = ai_answer(question.strip(), news["articles"])
    except Exception as error:
        return html.P(f"Gemini couldn't answer right now ({type(error).__name__}). Try again in a moment.",
                      className = "ai-note")
    sources = [news["articles"][i] for i in result["sources"] if 0 <= i < len(news["articles"])]
    return html.Div([
        html.P(result["answer"], className = "answer-text"),
        html.Div([html.Span("Sources: ", className = "briefing-label")] +
                 [html.A(a["title"], href = a["url"], target = "_blank", className = "answer-source")
                  for a in sources[:5]]) if sources else None,
        html.Div("Answered by Google Gemini using only today's headlines. AI can make mistakes.", className = "ai-note"),
    ], className = "answer")


# Word cloud: point the image at the new file after each fetch
@app.callback(Output("wordcloud", "src"), Input("news", "data"))
def update_wordcloud(news):
    return f"assets/wordcloud.png?v={news['version']}"


# Redraw the page whenever the news, the section or the search text changes
@app.callback(Output("tabs", "children"), Output("featured", "children"),
              Output("grid", "children"), Output("updated", "children"), Output("ticker", "children"),
              Input("news", "data"), Input("category", "data"), Input("search", "value"))
def show_news(news, category, search):
    articles = news["articles"]
    search = (search or "").lower()

    # Section links with counts, the selected one underlined in red
    tabs = []
    for cat in ["all"] + categories:
        count = len(articles) if cat == "all" else sum(a["category"] == cat for a in articles)
        label = "Front Page" if cat == "all" else cat.capitalize()
        tabs.append(html.Button([label, html.Span(count, className = "count")],
                                id = {"type": "tab", "index": cat},
                                className = "nav-item active" if cat == category else "nav-item"))

    # Keep only stories in the chosen section that match the search
    visible = [a for a in articles
               if (category == "all" or a["category"] == category)
               and search in (a["title"] + " " + a["description"] + " " + a["source"] + " " + a["author"]).lower()]

    updated = f"{len(visible)} stories · Printed {news['fetchedAt']}"
    ticker = ticker_items(articles)

    if not visible:
        return tabs, html.P("No stories match your search.", className = "empty"), [], updated, ticker

    return tabs, lead_story(visible[0]), [story_card(a) for a in visible[1:]], updated, ticker


if __name__ == "__main__":
    app.run(debug = True, dev_tools_ui = False)   # auto-reload on save, without the debug toolbar
