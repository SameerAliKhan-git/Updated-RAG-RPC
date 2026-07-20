"""Corpus — audio overviews (NotebookLM-style) via local Piper TTS.

Fully offline: a fast-LLM writes a conversational overview of a collection,
Piper synthesizes it to WAV on CPU. Voice model (~60MB) is fetched once from
HuggingFace into the shared cache volume.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from src.services.llm_adapter import call_fast_llm

logger = logging.getLogger(__name__)

AUDIO_DIR = Path("./data/audio")
STATUS_KEY = "corpus:audio:{cid}"

VOICE_REPO = "rhasspy/piper-voices"
VOICE_PATH = "en/en_US/lessac/medium/en_US-lessac-medium.onnx"

SCRIPT_PROMPT = """Write a spoken-style overview of this research paper collection, as if a
friendly narrator is briefing a researcher. Rules:
- 150-220 words, flowing prose. No headers, no bullet points, no citations markers.
- Name the key papers naturally ("a paper by Vaswani and colleagues...").
- End with one sentence on why this collection matters.

Collection: {name}
Papers:
{papers}"""


def _voice_model_path() -> Path:
    """Download the Piper voice into the HF cache once; return the local path."""
    from huggingface_hub import hf_hub_download

    onnx = hf_hub_download(VOICE_REPO, VOICE_PATH)
    hf_hub_download(VOICE_REPO, VOICE_PATH + ".json")
    return Path(onnx)


async def generate_audio_overview(collection_id: str, app_state) -> None:
    """Background job: script → synthesize → store WAV; progress in Redis."""
    redis = app_state.redis
    key = STATUS_KEY.format(cid=collection_id)

    async def set_status(status: str, detail: str = "") -> None:
        await redis.set(key, json.dumps({"status": status, "detail": detail, "ts": time.time()}), ex=86400)

    try:
        await set_status("writing_script")
        from src.models.paper import Collection, CollectionPaper, Paper

        db = app_state.db_session_factory()
        try:
            collection = db.query(Collection).filter(Collection.id == collection_id).first()
            if collection is None:
                await set_status("failed", "collection not found")
                return
            papers = (
                db.query(Paper)
                .join(CollectionPaper, CollectionPaper.paper_id == Paper.id)
                .filter(CollectionPaper.collection_id == collection_id)
                .limit(6)
                .all()
            )
            name = collection.name
            paper_block = "\n".join(
                f"- {p.title} ({', '.join((p.authors or [])[:2])}): {(p.abstract or '')[:300]}" for p in papers
            )
        finally:
            db.close()

        if not paper_block:
            await set_status("failed", "collection has no papers")
            return

        script = await call_fast_llm(
            messages=[{"role": "user", "content": SCRIPT_PROMPT.format(name=name, papers=paper_block)}],
            temperature=0.4,
            max_tokens=512,
        )
        if not script.strip() or script.startswith("[LLM Error"):
            await set_status("failed", "script generation failed — is Ollama running?")
            return

        await set_status("synthesizing")
        import wave

        from piper import PiperVoice

        voice = PiperVoice.load(str(_voice_model_path()))
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        out_path = AUDIO_DIR / f"{collection_id}.wav"
        with wave.open(str(out_path), "wb") as wav_file:
            voice.synthesize(script.strip(), wav_file)

        await set_status("done")
        logger.info(f"Audio overview ready for collection {collection_id}: {out_path}")
    except Exception as e:
        logger.error(f"Audio overview failed for {collection_id}: {e}", exc_info=True)
        await set_status("failed", str(e)[:200])


async def get_audio_status(redis, collection_id: str) -> dict:
    raw = await redis.get(STATUS_KEY.format(cid=collection_id))
    status = json.loads(raw) if raw else {"status": "not_generated"}
    status["file_exists"] = (AUDIO_DIR / f"{collection_id}.wav").exists()
    return status


def audio_file(collection_id: str) -> Path | None:
    path = AUDIO_DIR / f"{collection_id}.wav"
    return path if path.exists() else None
