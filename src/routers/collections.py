"""Corpus — Collections API (notebook-scoped paper groups)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.dependencies import get_db_session
from src.middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["collections"],
    dependencies=[Depends(verify_api_key)],
)


class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)


class CollectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)


def _summary(collection, paper_count: int) -> dict:
    return {
        "id": str(collection.id),
        "name": collection.name,
        "description": collection.description,
        "paper_count": paper_count,
        "created_at": collection.created_at.isoformat() if collection.created_at else None,
        "updated_at": collection.updated_at.isoformat() if collection.updated_at else None,
    }


@router.post("/collections", summary="Create a collection")
async def create_collection(body: CollectionCreate, db=Depends(get_db_session)):
    from src.models.paper import Collection

    if db.query(Collection).filter(Collection.name == body.name).first():
        raise HTTPException(status_code=409, detail=f"Collection '{body.name}' already exists.")
    collection = Collection(name=body.name, description=body.description)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return _summary(collection, 0)


@router.get("/collections", summary="List collections with paper counts")
async def list_collections(db=Depends(get_db_session)):
    from sqlalchemy import func

    from src.models.paper import Collection, CollectionPaper

    rows = (
        db.query(Collection, func.count(CollectionPaper.paper_id))
        .outerjoin(CollectionPaper, CollectionPaper.collection_id == Collection.id)
        .group_by(Collection.id)
        .order_by(Collection.updated_at.desc())
        .all()
    )
    return {"collections": [_summary(c, count) for c, count in rows]}


@router.get("/collections/{collection_id}", summary="Collection detail with papers")
async def get_collection(collection_id: str, db=Depends(get_db_session)):
    from src.models.paper import Collection, CollectionPaper, Paper

    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found.")

    papers = (
        db.query(Paper)
        .join(CollectionPaper, CollectionPaper.paper_id == Paper.id)
        .filter(CollectionPaper.collection_id == collection.id)
        .order_by(Paper.published_date.desc())
        .all()
    )
    return {
        **_summary(collection, len(papers)),
        "papers": [
            {
                "arxiv_id": p.arxiv_id,
                "title": p.title,
                "authors": p.authors or [],
                "published_date": str(p.published_date) if p.published_date else "",
            }
            for p in papers
        ],
    }


@router.patch("/collections/{collection_id}", summary="Rename / edit a collection")
async def update_collection(collection_id: str, body: CollectionUpdate, db=Depends(get_db_session)):
    from src.models.paper import Collection, CollectionPaper

    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found.")
    if body.name:
        collection.name = body.name
    if body.description is not None:
        collection.description = body.description
    db.commit()
    db.refresh(collection)
    count = db.query(CollectionPaper).filter(CollectionPaper.collection_id == collection.id).count()
    return _summary(collection, count)


@router.delete("/collections/{collection_id}", summary="Delete a collection")
async def delete_collection(collection_id: str, db=Depends(get_db_session)):
    from src.models.paper import Collection

    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found.")
    db.delete(collection)
    db.commit()
    return {"status": "deleted"}


@router.put("/collections/{collection_id}/papers/{arxiv_id}", summary="Add a paper to a collection")
async def add_paper(collection_id: str, arxiv_id: str, db=Depends(get_db_session)):
    from src.models.paper import Collection, CollectionPaper, Paper

    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found.")
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper {arxiv_id} is not ingested.")

    exists = (
        db.query(CollectionPaper)
        .filter(CollectionPaper.collection_id == collection.id, CollectionPaper.paper_id == paper.id)
        .first()
    )
    if not exists:
        db.add(CollectionPaper(collection_id=collection.id, paper_id=paper.id))
        collection.updated_at = collection.updated_at  # touch via onupdate
        db.commit()
    return {"status": "added", "arxiv_id": arxiv_id}


@router.delete("/collections/{collection_id}/papers/{arxiv_id}", summary="Remove a paper from a collection")
async def remove_paper(collection_id: str, arxiv_id: str, db=Depends(get_db_session)):
    from src.models.paper import CollectionPaper, Paper

    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper {arxiv_id} is not ingested.")
    deleted = (
        db.query(CollectionPaper)
        .filter(CollectionPaper.collection_id == collection_id, CollectionPaper.paper_id == paper.id)
        .delete()
    )
    db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Paper is not in this collection.")
    return {"status": "removed", "arxiv_id": arxiv_id}
