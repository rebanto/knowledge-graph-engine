import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_owned_workspace, get_readable_workspace
from backend.db.postgres import get_async_db
from backend.db.models import Workspace, WorkspaceDismissal, Source, IngestionJob, User
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job
from backend.models.schemas import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse, SourceResponse
from backend.core.source_discovery import suggest_arxiv_categories
from backend.core.llm_client import generate_json

router = APIRouter()


@router.get("/workspaces", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    dismissed = select(WorkspaceDismissal.workspace_id).where(
        WorkspaceDismissal.user_id == user.id
    )
    result = await db.execute(
        select(Workspace)
        .where(or_(Workspace.owner_user_id == user.id, Workspace.owner_user_id.is_(None)))
        .where(~Workspace.id.in_(dismissed))
        .order_by(Workspace.created_at.asc())
    )
    return result.scalars().all()


@router.post("/workspaces", response_model=WorkspaceResponse)
async def create_workspace(
    req: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name=req.name,
        domain=req.domain,
        description=req.description or None,
        owner_user_id=user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.post("/workspaces/{workspace_id}/dismiss", status_code=204)
async def dismiss_workspace(
    workspace_id: str,
    workspace: Workspace = Depends(get_readable_workspace),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    if workspace.owner_user_id == user.id:
        raise HTTPException(
            400,
            "You own this workspace - delete it instead of dismissing.",
        )

    stmt = (
        insert(WorkspaceDismissal)
        .values(
            user_id=user.id,
            workspace_id=workspace_id,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=[WorkspaceDismissal.user_id, WorkspaceDismissal.workspace_id]
        )
    )
    await db.execute(stmt)
    await db.commit()


@router.post("/workspaces/{workspace_id}/discover", response_model=list[SourceResponse])
async def discover_sources(
    workspace_id: str,
    workspace: Workspace = Depends(get_owned_workspace),
    db: AsyncSession = Depends(get_async_db),
):
    if not workspace.description:
        raise HTTPException(400, "Set a workspace description before auto-discovering sources")

    categories = await suggest_arxiv_categories(workspace.description)
    if not categories:
        raise HTTPException(422, "Could not determine relevant sources from the description")

    created = []
    for cat in categories:
        exists_result = await db.execute(
            select(Source).where(
                Source.workspace_id == workspace_id,
                Source.url == cat,
                Source.type == "arxiv_feed",
            )
        )
        if exists_result.scalar_one_or_none():
            continue
        source = Source(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            type="arxiv_feed",
            url=cat,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
        created.append(source)

    if created:
        await _clear_question_cache(workspace_id, db)

    return created


@router.put("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    req: WorkspaceUpdate,
    workspace: Workspace = Depends(get_owned_workspace),
    db: AsyncSession = Depends(get_async_db),
):
    if req.name is not None:
        workspace.name = req.name
    if req.domain is not None:
        workspace.domain = req.domain
    if req.description is not None:
        workspace.description = req.description
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    workspace: Workspace = Depends(get_owned_workspace),
    db: AsyncSession = Depends(get_async_db),
):
    # Delete related sources and their jobs first
    sources_result = await db.execute(select(Source).where(Source.workspace_id == workspace_id))
    for source in sources_result.scalars().all():
        jobs_result = await db.execute(
            select(IngestionJob).where(IngestionJob.source_id == source.id)
        )
        for job in jobs_result.scalars().all():
            await db.delete(job)
        await db.delete(source)
    # Delete related reports (conversation turns) and the conversation threads
    from backend.db.models import Report, Conversation
    reports_result = await db.execute(select(Report).where(Report.workspace_id == workspace_id))
    for report in reports_result.scalars().all():
        await db.delete(report)
    convos_result = await db.execute(
        select(Conversation).where(Conversation.workspace_id == workspace_id)
    )
    for convo in convos_result.scalars().all():
        await db.delete(convo)
    await db.delete(workspace)
    await db.commit()

    # Purge the workspace's vector + graph data too — deleting only the Postgres
    # rows would orphan the ChromaDB collection and every Neo4j node, leaving
    # stale data that a re-created workspace could surface. Best-effort: Postgres
    # is the source of truth and is already committed.
    from backend.db import chroma as chroma_db
    from backend.db import neo4j as neo4j_db
    from backend.db import redis as redis_db
    try:
        await chroma_db.delete_collection(workspace_id)
    except Exception:
        pass
    try:
        await neo4j_db.delete_workspace_graph(workspace_id)
    except Exception:
        pass
    try:
        await redis_db.invalidate_workspace_caches(workspace_id)
    except Exception:
        pass


_SUGGEST_QUESTIONS_PROMPT = """You are helping a user explore a research knowledge graph.
Given the workspace details below, generate exactly 3 natural-language questions that would
be interesting and answerable using the data in this workspace.

Mix question styles:
- At least one relationship/connection question (graph traversal: "How is X connected to Y?", "Who collaborated with…?")
- At least one knowledge/summary question (vector search: "What are the latest findings on…?", "Summarize the state of…")
- At least one that is specific to the domain/sources listed

Keep each question concise (under 15 words). Do not number them. Do not repeat boilerplate.
Make them specific enough to be useful, not generic filler.

Return ONLY valid JSON: {{"questions": ["question 1", "question 2", "question 3"]}}

Workspace name: {name}
Domain: {domain}
Description: {description}
Sources ({source_count} total): {source_sample}"""


async def _clear_question_cache(workspace_id: str, db: AsyncSession) -> None:
    """Null out the cached suggested questions so the next GET regenerates them.

    Uses a direct UPDATE to avoid the extra SELECT round-trip; the session does
    not need to hold the full Workspace object just to clear one column.
    """
    await db.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(suggested_questions=None)
    )
    await db.commit()


@router.get("/workspaces/{workspace_id}/suggested-questions")
async def suggested_questions(
    workspace_id: str,
    workspace: Workspace = Depends(get_readable_workspace),
    db: AsyncSession = Depends(get_async_db),
):

    # Cache hit: return stored questions without calling Gemini.
    cached = workspace.suggested_questions
    if cached and isinstance(cached, list) and len(cached) > 0:
        return {"questions": cached}

    sources_result = await db.execute(
        select(Source)
        .where(Source.workspace_id == workspace_id)
        .order_by(Source.created_at.desc())
        .limit(6)
    )
    sources = sources_result.scalars().all()

    if not sources:
        return {"questions": []}

    source_sample = ", ".join(s.url for s in sources)
    description = workspace.description or workspace.domain

    prompt = _SUGGEST_QUESTIONS_PROMPT.format(
        name=workspace.name,
        domain=workspace.domain,
        description=description,
        source_count=len(sources),
        source_sample=source_sample,
    )

    try:
        data = await generate_json(prompt)
        questions = data.get("questions", [])
        questions = [q for q in questions if isinstance(q, str) and q.strip()][:3]
    except Exception:
        questions = []

    if questions:
        workspace.suggested_questions = questions
        await db.commit()

    return {"questions": questions}
