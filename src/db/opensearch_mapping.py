from __future__ import annotations

# Mappings for layout-aware chunked documents with 1024-dimension KNN Jina v4 embeddings
OPENSEARCH_CHUNKS_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "index.knn": True,
        "index.knn.space_type": "cosinesimil",
        "analysis": {
            "analyzer": {
                "text_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                }
            }
        },
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "chunk_id": {"type": "keyword"},
            "arxiv_id": {"type": "keyword"},
            "paper_id": {"type": "keyword"},
            "section_title": {"type": "keyword"},
            "chunk_type": {"type": "keyword"},  # body, table, figure-caption, equation
            "text": {
                "type": "text",
                "analyzer": "text_analyzer",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "embedding": {
                "type": "knn_vector",
                "dimension": 1024,  # Jina v4 embeddings dimension
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "nmslib",
                    "parameters": {
                        "ef_construction": 512,
                        "m": 16,
                    },
                },
            },
            # Shared Metadata (for combined queries and filters)
            "title": {
                "type": "text",
                "analyzer": "text_analyzer",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "authors": {"type": "keyword"},  # List of author names
            "abstract": {"type": "text", "analyzer": "text_analyzer"},
            "categories": {"type": "keyword"},  # List of categories
            "published_date": {"type": "date"},
            "created_at": {"type": "date"},
            "page_number": {"type": "integer"},  # 1-based PDF page for citation deep-links
        },
    },
}

OPENSEARCH_RRF_PIPELINE = {
    "description": "Post-processor pipeline for hybrid search Reciprocal Rank Fusion",
    "phase_results_processors": [
        {
            "score-ranker-processor": {
                "combination": {
                    "technique": "rrf",
                    "rank_constant": 60,
                }
            }
        }
    ],
}
