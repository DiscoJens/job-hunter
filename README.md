# job-hunter

A personal job search tool that scrapes [finn.no](https://www.finn.no/job/search) and uses Claude AI to rank listings by how well they match your CV.

## Features

- **Scrape finn.no** - search by location (county + municipality), occupation, industry, job type, and more
- **Searchable filter dropdowns** - all finn.no filter options pulled live, with Tom Select dropdowns
- **CV + cover letter upload** - PDF or plain text
- **AI ranking** - Claude reads every job description and scores each listing against your profile, returning a ranked list with a one-sentence explanation per job

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Chromium + ChromeDriver (used by the Selenium scraper)
- An [Anthropic API key](https://console.anthropic.com/)

On Ubuntu/Debian:
```bash
sudo apt install chromium-browser chromium-chromedriver
```

## Setup

```bash
# Clone and install dependencies
git clone https://github.com/DiscoJens/job-hunter.git
cd job-hunter
uv sync

# Add your Anthropic API key
echo 'ANTHROPIC_API_KEY="sk-ant-..."' > .env
```

## Running

```bash
uv run main.py
```

Then open [http://localhost:8000](http://localhost:8000).

## Usage

1. **Upload your CV** (and optionally a cover letter) in the Profile section
2. **Set your filters** - location, occupation, industry, etc.
3. Click **Søk** to scrape matching listings from finn.no
4. Click **Analyser med Claude** to rank them by fit

Results are sorted by match score (0–100) with a short explanation for each.
