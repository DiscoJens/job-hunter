from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from io import BytesIO
from typing import Any
import asyncio
import json
import re
import anthropic
from pypdf import PdfReader
from scrape import get_filters, scrape_finn, fetch_descriptions

app = FastAPI()

# In-memory profile store
_profile: dict[str, str | None] = {"cv": None, "cover_letter": None}


# ── helpers ────────────────────────────────────────────────────────────────────

def _extract_text(content: bytes, filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(BytesIO(content))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    return content.decode("utf-8", errors="replace")


def _build_prompt(cv: str, cover_letter: str | None, jobs: list[dict], descriptions: list[str]) -> str:
    lines = ["Her er min CV:", "---", cv, "---", ""]

    if cover_letter:
        lines += ["Her er mitt søknadsbrev (gir kontekst om hva jeg ser etter):", "---", cover_letter, "---", ""]

    lines += [
        f"Analyser følgende {len(jobs)} stillinger og ranger dem etter hvor godt de passer min profil.",
        "For hver stilling, gi:",
        "  1. En match-score fra 0 til 100",
        "  2. En kort forklaring på maks 1 setning om hvorfor stillingen passer (eller ikke passer)",
        "",
        "Stillinger:",
    ]

    for i, (job, desc) in enumerate(zip(jobs, descriptions)):
        lines.append(f"\n[{i}] {job['title']} – {job['employer']} ({job.get('location', '')})")
        if desc:
            lines.append(desc[:800])
        lines.append("---")

    lines += [
        "",
        "Returner KUN et JSON-array sortert fra best til dårligst match, uten noe annet tekst:",
        '[{"job_index": <0-basert indeks>, "match_score": <0-100>, "summary": "<forklaring>"}, ...]',
    ]

    return "\n".join(lines)


def _parse_ranked(text: str) -> list[dict]:
    """Extract JSON array from Claude's response, even if there's surrounding text."""
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text)
    # Try complete array first
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    # Response was truncated - recover by closing after the last complete object
    start = text.find("[")
    if start != -1:
        last = text.rfind("},")
        if last != -1:
            try:
                return json.loads(text[start:last + 1] + "]")
            except json.JSONDecodeError:
                pass
    preview = text[:300].replace("\n", " ")
    raise ValueError(f"No JSON array found in response. Claude said: {preview}")


# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("static/index.html").read_text()


@app.get("/api/filters")
async def filters():
    return get_filters()


@app.post("/api/search")
async def search(params: dict[str, Any]):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, scrape_finn, params)


@app.post("/api/upload-cv")
async def upload_cv(file: UploadFile = File(...)):
    content = await file.read()
    _profile["cv"] = _extract_text(content, file.filename or "")
    return {"ok": True, "filename": file.filename, "chars": len(_profile["cv"])}


@app.post("/api/upload-cover-letter")
async def upload_cover_letter(file: UploadFile = File(...)):
    content = await file.read()
    _profile["cover_letter"] = _extract_text(content, file.filename or "")
    return {"ok": True, "filename": file.filename, "chars": len(_profile["cover_letter"])}


@app.delete("/api/upload-cv")
async def delete_cv():
    _profile["cv"] = None
    return {"ok": True}


@app.delete("/api/upload-cover-letter")
async def delete_cover_letter():
    _profile["cover_letter"] = None
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(jobs: list[dict]):
    if not _profile["cv"]:
        raise HTTPException(status_code=400, detail="Ingen CV lastet opp")
    if not jobs:
        raise HTTPException(status_code=400, detail="Ingen stillinger å analysere")

    MAX_JOBS = 150
    if len(jobs) > MAX_JOBS:
        raise HTTPException(
            status_code=400,
            detail=f"For mange stillinger ({len(jobs)}). Begrens søket til maks {MAX_JOBS} stillinger.",
        )

    try:
        descriptions = await fetch_descriptions([j["url"] for j in jobs])

        prompt = _build_prompt(_profile["cv"], _profile["cover_letter"], jobs, descriptions)

        client = anthropic.AsyncAnthropic()
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )

        ranked = _parse_ranked(message.content[0].text)

        result = []
        for item in ranked:
            idx = item["job_index"]
            if 0 <= idx < len(jobs):
                result.append({
                    **jobs[idx],
                    "match_score": item["match_score"],
                    "summary": item["summary"],
                })

        return sorted(result, key=lambda x: x["match_score"], reverse=True)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
