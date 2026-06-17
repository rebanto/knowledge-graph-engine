import uuid
from datetime import datetime, timezone

from backend.db.postgres import SessionLocal
from backend.db.models import Source, IngestionJob
from backend.ingestion.dispatcher import fetch_documents_for_source
from backend.ingestion.worker import process_document
from backend.ingestion.entity_resolver import EntityResolver


def run_ingestion_job(source_id: str) -> None:
    """Entry point executed by the RQ worker process for one source."""
    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            return

        source.status = "running"
        db.commit()

        try:
            documents = fetch_documents_for_source(source)
        except Exception as e:
            source.status = "error"
            source.error_count += 1
            source.last_error = str(e)[:500]
            db.commit()
            return

        resolver = EntityResolver()
        for doc in documents:
            job = IngestionJob(
                id=str(uuid.uuid4()),
                source_id=source.id,
                document_url=doc.get("url"),
                status="running",
                created_at=datetime.now(timezone.utc),
            )
            db.add(job)
            db.commit()

            try:
                process_document(doc, source.workspace_id, resolver)
                job.status = "success"
            except Exception as e:
                job.status = "failed"
                job.error = str(e)[:500]

            job.completed_at = datetime.now(timezone.utc)
            db.commit()

        source.status = "success"
        source.last_fetched = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
