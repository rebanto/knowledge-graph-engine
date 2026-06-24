import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func, delete as sql_delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_async_db
from backend.db.models import Source, IngestionJob
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job
from backend.models.schemas import SourceCreate, SourceResponse, SourceJobsResponse
from backend.db import chroma as chroma_db
from backend.db import neo4j as neo4j_db
from backend.db import redis as redis_db

router = APIRouter()

UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


_STUCK_THRESHOLD = timedelta(minutes=15)


@router.get("/workspaces/{workspace_id}/sources", response_model=list[SourceResponse])
async def list_sources(workspace_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(Source)
        .where(Source.workspace_id == workspace_id)
        .order_by(Source.created_at.desc())
    )
    sources = result.scalars().all()

    # Safety net for long-running server sessions: auto-reset sources that are
    # "running" but have clearly been stuck (first-time ingest only — re-ingest
    # uses created_at which is stale, so those are handled by the startup reset).
    # For first-time ingests, created_at ≈ when the job started.
    now = datetime.now(timezone.utc)
    stuck_reset = False
    for s in sources:
        if s.status == "running" and s.last_fetched is None:
            started = s.created_at
            if started:
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if (now - started) > _STUCK_THRESHOLD:
                    s.status = "error"
                    s.last_error = "Worker process crashed — click Re-ingest to retry."
                    stuck_reset = True
    if stuck_reset:
        await db.commit()

    return sources


@router.post("/workspaces/{workspace_id}/sources", response_model=SourceResponse)
async def create_source(
    workspace_id: str, req: SourceCreate, db: AsyncSession = Depends(get_async_db)
):
    source = Source(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        type=req.type,
        url=req.url,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
    return source


@router.post("/workspaces/{workspace_id}/sources/upload", response_model=SourceResponse)
async def upload_pdf_source(
    workspace_id: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_async_db)
):
    dest = UPLOAD_DIR / f"{uuid.uuid4()}_{file.filename}"
    contents = await file.read()
    dest.write_bytes(contents)

    source = Source(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        type="pdf_upload",
        url=str(dest),
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
    return source


@router.get("/workspaces/{workspace_id}/sources/{source_id}/jobs", response_model=SourceJobsResponse)
async def list_source_jobs(
    workspace_id: str,
    source_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db),
):
    source_result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    if not source_result.scalar_one_or_none():
        raise HTTPException(404, "Source not found")

    counts_result = await db.execute(
        select(IngestionJob.status, func.count(IngestionJob.id))
        .where(IngestionJob.source_id == source_id)
        .group_by(IngestionJob.status)
    )
    counts: dict[str, int] = dict(counts_result.all())

    jobs_result = await db.execute(
        select(IngestionJob)
        .where(IngestionJob.source_id == source_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(limit)
    )
    jobs = jobs_result.scalars().all()

    return {
        "total": sum(counts.values()),
        "success": counts.get("success", 0),
        "failed": counts.get("failed", 0),
        "running": counts.get("running", 0),
        "jobs": jobs,
    }


@router.post("/workspaces/{workspace_id}/sources/{source_id}/retry")
async def retry_source(
    workspace_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    source.status = "pending"
    source.last_error = None
    await db.commit()
    await db.refresh(source)

    get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
    return {"status": "queued", "source": source}


@router.post("/workspaces/{workspace_id}/sources/{source_id}/reingest")
async def reingest_source(
    workspace_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    """Force a full re-ingest of one source.

    Unlike /retry, this re-extracts and re-embeds documents that were already
    processed (force=True bypasses the 'already processed' checkpoint). Use after
    a pipeline change so existing sources pick up the new extraction. Safe to
    replay: Neo4j MERGE + ChromaDB upsert mean no duplicates.
    """
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    source.status = "pending"
    source.last_error = None
    await db.commit()

    get_queue().enqueue(run_ingestion_job, source.id, force=True, job_timeout=1800)
    return {"status": "queued", "source_id": source.id}


@router.post("/workspaces/{workspace_id}/sources/reingest")
async def reingest_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    """Force a full re-ingest of every source in the workspace."""
    result = await db.execute(
        select(Source).where(Source.workspace_id == workspace_id)
    )
    sources = result.scalars().all()
    if not sources:
        raise HTTPException(404, "No sources in workspace")

    for source in sources:
        source.status = "pending"
        source.last_error = None
    await db.commit()

    for source in sources:
        get_queue().enqueue(run_ingestion_job, source.id, force=True, job_timeout=1800)

    return {"status": "queued", "count": len(sources), "source_ids": [s.id for s in sources]}


@router.delete("/workspaces/{workspace_id}/sources/{source_id}")
async def delete_source(
    workspace_id: str, source_id: str, db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    # Document URLs this source produced — used to purge chunks written before
    # source_id tagging existed (belt-and-suspenders alongside the source_id path).
    jobs_result = await db.execute(
        select(IngestionJob.document_url).where(
            IngestionJob.source_id == source_id,
            IngestionJob.document_url.isnot(None),
        )
    )
    document_urls = list({row[0] for row in jobs_result.all()})
    if source.url:
        document_urls = list({*document_urls, source.url})

    # Graph: detach this source's contribution PRECISELY by source_id. Nodes/edges
    # that other live sources still assert are preserved; only this source's
    # exclusive ones are removed (remove_source_from_graph drops the source_id from
    # each source_ids list and deletes whatever is left orphaned).
    graph_result = await neo4j_db.remove_source_from_graph(workspace_id, source_id)

    # Fallback for legacy data: nodes ingested before source_id tagging carry no
    # source_ids list, so the precise pass above can't see them. Remove only those
    # UNTAGGED Papers (and their now-orphaned untagged entities) by document URL.
    # This deliberately never touches a source-tagged node, so a paper shared by
    # multiple sources (e.g. an arXiv paper cross-listed across feeds) survives
    # deleting just one of them. No-op for new sources (already removed precisely).
    try:
        legacy_papers = await neo4j_db.remove_untagged_documents(workspace_id, document_urls)
        graph_result["legacy_papers_removed"] = legacy_papers
    except Exception:
        pass

    # Vector: delete by source_id (precise) and by URL (covers legacy chunks that
    # predate source_id tagging). Best-effort — graph + Postgres are source of truth.
    try:
        await chroma_db.delete_chunks_for_source_id(workspace_id, source_id)
        if document_urls:
            await chroma_db.delete_chunks_for_sources(workspace_id, document_urls)
    except Exception:
        pass

    # For PDF uploads, remove the file from disk
    if source.type == "pdf_upload":
        try:
            Path(source.url).unlink(missing_ok=True)
        except OSError:
            pass

    # Remove Redis ingestion checkpoint so a re-add of this source starts fresh
    await redis_db.clear_checkpoint(source_id)

    # Remove ingestion job records, then the source itself
    await db.execute(sql_delete(IngestionJob).where(IngestionJob.source_id == source_id))
    await db.delete(source)
    await db.commit()

    # Invalidate route + Cypher caches — their results may reference deleted content
    await redis_db.invalidate_workspace_caches(workspace_id)

    return {"status": "deleted", "graph": graph_result}


@router.post("/workspaces/{workspace_id}/cleanup")
async def cleanup_workspace_data(
    workspace_id: str, db: AsyncSession = Depends(get_async_db)
):
    """Remove stale vector/graph data left behind by deleted sources.

    Compares what is currently in ChromaDB and Neo4j against the set of
    document URLs from active (non-deleted) sources in this workspace. Any
    data that doesn't belong to an active source is purged.

    Also resets any source stuck in "running" for longer than the stuck
    threshold — covers crashed workers without requiring a backend restart.

    Safe to call at any time — it only deletes data that has no corresponding
    active source record.
    """
    # Reset sources stuck in "running" for longer than the threshold.
    # list_sources handles first-time ingests (last_fetched is None).
    # Here we also cover re-ingests by checking created_at as a lower bound
    # (if created_at is > threshold ago, the source has existed long enough
    # that a re-ingest started at any point should have finished by now).
    now = datetime.now(timezone.utc)
    stuck_result = await db.execute(
        select(Source).where(Source.workspace_id == workspace_id, Source.status == "running")
    )
    stuck_sources = stuck_result.scalars().all()
    stuck_reset_count = 0
    for s in stuck_sources:
        started = s.created_at
        if started:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if (now - started) > _STUCK_THRESHOLD:
                s.status = "error"
                s.last_error = "Worker process crashed — click Re-ingest to retry."
                stuck_reset_count += 1
    if stuck_reset_count:
        await db.commit()

    # URLs that belong to active sources in this workspace
    active_result = await db.execute(
        select(IngestionJob.document_url)
        .join(Source, IngestionJob.source_id == Source.id)
        .where(
            Source.workspace_id == workspace_id,
            IngestionJob.document_url.isnot(None),
        )
    )
    active_urls: set[str] = {row[0] for row in active_result.all()}

    # ── ChromaDB: delete chunks whose source_url isn't in the active set ────────
    all_chroma_urls = await chroma_db.get_all_source_urls(workspace_id)
    stale_chroma_urls = all_chroma_urls - active_urls
    if stale_chroma_urls:
        await chroma_db.delete_chunks_for_sources(workspace_id, list(stale_chroma_urls))

    # ── Neo4j: delete Paper nodes for globally orphaned IngestionJob records ────
    # "Orphaned" = IngestionJob whose source_id no longer exists in sources
    orphaned_result = await db.execute(
        text("""
            SELECT DISTINCT document_url FROM ingestion_jobs
            WHERE source_id NOT IN (SELECT id FROM sources)
              AND document_url IS NOT NULL
        """)
    )
    orphaned_urls = [row[0] for row in orphaned_result.all()]
    neo4j_deleted = await neo4j_db.delete_source_documents(workspace_id, orphaned_urls)

    # ── PostgreSQL: drop orphaned IngestionJob rows ──────────────────────────────
    del_result = await db.execute(
        text("DELETE FROM ingestion_jobs WHERE source_id NOT IN (SELECT id FROM sources)")
    )
    jobs_deleted = del_result.rowcount
    await db.commit()

    if stale_chroma_urls or orphaned_urls:
        await redis_db.invalidate_workspace_caches(workspace_id)

    return {
        "status": "ok",
        "stale_vector_sources_removed": len(stale_chroma_urls),
        "stale_graph_papers_removed": neo4j_deleted,
        "orphaned_jobs_removed": jobs_deleted,
        "stuck_sources_reset": stuck_reset_count,
    }
