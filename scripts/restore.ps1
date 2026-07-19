# Corpus — disaster recovery restore.
# Usage: .\scripts\restore.ps1 [path\to\corpus_YYYYMMDD_HHMM.dump]
# Restores Postgres (source of truth), then rebuilds the OpenSearch index.
# PDFs in .\data\arxiv_pdfs are host files — copy them back manually if lost
# (arXiv papers re-download automatically on first view; uploads do not).

param([string]$DumpFile = "")

$ErrorActionPreference = "Stop"

if (-not $DumpFile) {
    $latest = Get-ChildItem ".\backups\corpus_*.dump" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { Write-Error "No dumps found in .\backups"; exit 1 }
    $DumpFile = $latest.FullName
}

Write-Host "Restoring from: $DumpFile"
Write-Host "This DROPS and recreates corpus_db. Press Ctrl+C within 5s to abort..."
Start-Sleep -Seconds 5

docker compose up -d postgres
docker exec corpus-postgres psql -U rag_user -d postgres -c "DROP DATABASE IF EXISTS corpus_db WITH (FORCE);"
docker exec corpus-postgres psql -U rag_user -d postgres -c "CREATE DATABASE corpus_db OWNER rag_user;"
Get-Content $DumpFile -Raw -AsByteStream | docker exec -i corpus-postgres pg_restore -U rag_user -d corpus_db --no-owner
if ($LASTEXITCODE -ne 0) { Write-Error "pg_restore failed"; exit 1 }
Write-Host "Postgres restored. Rebuilding the search index (this re-embeds all chunks)..."

docker compose up -d opensearch redis
uv run python -m src.run_reindex
Write-Host "Restore complete. Start the full stack with: docker compose up -d"
