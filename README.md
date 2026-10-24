# SmartHomes

A property search and recommendation platform that understands natural-language queries and lets you search by photo, without routing either through a paid LLM or cloud vision API at query time.

Most listing sites only offer structured filters (price range, locality, bedroom count). SmartHomes adds two things on top of that: a deterministic, rule-based parser that reads a query like *"2 BHK near a school under 25000"* and turns it into structured filters, and a self-hosted visual similarity search so you can find homes that look like a reference photo instead of only describing one in words.

## Features

- **Natural-language search** — a rule-based parser (no LLM in the request path) extracts budget, BHK, locality, and nearby-facility intent from free text, with a bounded cosine-similarity fallback for facility phrases that don't match the known vocabulary exactly.
- **Visual similarity search** — upload a photo or generate a reference image (Gemini for prompt optimization, Cloudflare Workers AI for image generation), and a self-hosted SigLIP2 encoder ranks catalog listings by visual similarity.
- **Nearby-facility enrichment** — a background worker queries the Mappls API across 17 facility categories per listing (schools, hospitals, transit, etc.), with a periodic retry sweep so a transient failure never leaves a listing stuck.
- **Cross-source property comparison** — compare up to 4 properties side by side, including live external listings pulled from Square Yards over the Model Context Protocol (MCP), scored across 6 categories (price, location, facilities, availability, connectivity, property features) with transparent, documented formulas that renormalize weights when data is missing rather than scoring a gap as zero.
- **Account management** — signup/login (Flask-Login + bcrypt), password change, and account deletion (which unlists rather than hard-deletes a user's properties).
- **Voice search** support for the search box.

## Tech stack

- **Backend:** Flask, Flask-Login, Flask-SQLAlchemy, Flask-WTF
- **Data:** MongoDB Atlas (property listings, embeddings, enrichment data), SQLite (user auth, via SQLAlchemy)
- **ML/NLP:** PyTorch + Hugging Face Transformers (SigLIP2 for image similarity, a local sentence-transformer for the facility-matching fallback), a custom rule-based NLP parser (no LLM at query time)
- **External integrations:** Mappls (geocoding + nearby facilities), Ola Maps (location fallback), Square Yards (external listings via MCP), Gemini (prompt optimization), Cloudflare Workers AI (image generation)
- **Testing:** pytest (983 passing tests, with every external network dependency mocked at the HTTP boundary)

## Getting started

### Prerequisites

- Python 3.11+
- A MongoDB Atlas cluster (or any MongoDB instance)
- API keys for the services you want enabled (see below — most features degrade gracefully without every key)

### Setup

```bash
git clone https://github.com/KrishnaKoushikElluru/Smart-Homes.git
cd Smart-Homes

python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

Create a `secret.env` file in the project root with the following variables:

```
FLASK_SECRET_KEY=
MONGO_URI=
GEOAPIFY_API_KEY=
MAPPLS_API_KEY=
OLA_MAPS_API_KEY=
GEMINI_API_KEY=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
```

`MONGO_URI` is a standard `mongodb+srv://` connection string. If you're on MongoDB Atlas, make sure your current IP is added under Network Access, otherwise connections will fail at the TLS handshake.

### Run

```bash
flask run
```

The app serves on `http://localhost:5000` by default. Local SQLite tables (users) are created automatically on first run via Flask-Migrate; MongoDB collections and indexes are created on demand.

### Run tests

```bash
pytest
```

The suite runs fully offline — every external service (Mappls, Square Yards, Ola Maps, Gemini, Cloudflare) is mocked at its call boundary, so no API keys or network access are needed to run it.

## Project structure

```
app.py                  # App factory, extension wiring, background worker startup
routes/                 # Flask blueprints (auth, property, search, design, comparison)
services/                # Business logic: NLP parsing, image similarity, enrichment, MCP client
  nlp/                   # Rule-based query parser + semantic fallback
  image_similarity/      # SigLIP2 encoding, indexing, retrieval
models.py                # SQLAlchemy User model
templates/, static/      # Frontend (server-rendered Jinja + vanilla JS)
docs/                    # Phase-by-phase design/implementation notes
test_*.py                # pytest suite (one file per module/feature)
```
