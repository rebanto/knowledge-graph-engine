"""Best-effort ChromaDB snapshots for ephemeral Hugging Face Spaces.

The API and RQ worker still talk to one Chroma server via HttpClient. This
module only snapshots the server's on-disk data directory so a Space restart can
restore the latest vector state before Chroma starts.
"""
from __future__ import annotations

import argparse
import logging
import os
import tarfile
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SNAPSHOT_FILENAME = "latest/chroma.tar.gz"
DEFAULT_CHROMA_PATH = "/data/chroma"

_timer: threading.Timer | None = None
_last_backup_at = 0.0
_lock = threading.Lock()


def _settings() -> tuple[str | None, str | None]:
    token = os.environ.get("HF_TOKEN")
    repo = os.environ.get("CHROMA_BACKUP_REPO")
    if not token or not repo:
        return None, None
    return token, repo


def _chroma_path(path: str | Path | None = None) -> Path:
    configured = path or os.environ.get("CHROMA_BACKUP_PATH") or os.environ.get(
        "CHROMA_PERSIST_DIR", DEFAULT_CHROMA_PATH
    )
    return Path(configured)


def _get_hf_api():
    try:
        from huggingface_hub import HfApi, hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError, RepositoryNotFoundError
    except Exception as exc:  # pragma: no cover - depends on optional package install
        logger.warning("chroma_backup_unavailable", extra={"error": str(exc)})
        return None
    return HfApi, hf_hub_download, EntryNotFoundError, RepositoryNotFoundError


def _ensure_repo(api, repo_id: str, token: str) -> None:
    api.create_repo(
        repo_id=repo_id,
        repo_type="dataset",
        private=True,
        token=token,
        exist_ok=True,
    )


def _safe_extract(tar: tarfile.TarFile, target: Path) -> None:
    root = target.resolve()
    for member in tar.getmembers():
        destination = (target / member.name).resolve()
        if root != destination and root not in destination.parents:
            raise ValueError(f"Unsafe path in Chroma snapshot: {member.name}")
    tar.extractall(target)


def restore(path: str | Path | None = None) -> bool:
    """Restore the latest Chroma snapshot into path.

    Returns True when a snapshot was restored. Missing env/repo/file is a no-op.
    """
    token, repo_id = _settings()
    if not token or not repo_id:
        logger.info("chroma_restore_skipped_no_repo")
        return False

    hf = _get_hf_api()
    if hf is None:
        return False
    HfApi, hf_hub_download, EntryNotFoundError, RepositoryNotFoundError = hf

    target = _chroma_path(path)
    try:
        _ensure_repo(HfApi(), repo_id, token)
        archive = hf_hub_download(
            repo_id=repo_id,
            filename=SNAPSHOT_FILENAME,
            repo_type="dataset",
            token=token,
        )
    except (EntryNotFoundError, RepositoryNotFoundError):
        logger.info("chroma_restore_no_snapshot", extra={"repo": repo_id})
        return False
    except Exception as exc:
        logger.warning("chroma_restore_failed", extra={"error": str(exc)})
        return False

    try:
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            _safe_extract(tar, target)
        logger.info("chroma_restored", extra={"repo": repo_id, "path": str(target)})
        return True
    except Exception as exc:
        logger.warning("chroma_restore_unpack_failed", extra={"error": str(exc)})
        return False


def _make_archive(source: Path) -> Path:
    tmp = tempfile.NamedTemporaryFile(prefix="chroma-", suffix=".tar.gz", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    with tarfile.open(tmp_path, "w:gz") as tar:
        if source.exists():
            for child in source.iterdir():
                tar.add(child, arcname=child.name)
    return tmp_path


def backup(path: str | Path | None = None) -> bool:
    """Upload the latest Chroma snapshot.

    Failures are logged and reported as False; callers should never let backup
    failures break ingestion.
    """
    token, repo_id = _settings()
    if not token or not repo_id:
        logger.info("chroma_backup_skipped_no_repo")
        return False

    hf = _get_hf_api()
    if hf is None:
        return False
    HfApi, _hf_hub_download, _EntryNotFoundError, _RepositoryNotFoundError = hf

    source = _chroma_path(path)
    if not source.exists():
        logger.info("chroma_backup_skipped_missing_path", extra={"path": str(source)})
        return False

    archive: Path | None = None
    try:
        api = HfApi()
        _ensure_repo(api, repo_id, token)
        archive = _make_archive(source)
        api.upload_file(
            path_or_fileobj=str(archive),
            path_in_repo=SNAPSHOT_FILENAME,
            repo_id=repo_id,
            repo_type="dataset",
            token=token,
            commit_message="Update Chroma latest snapshot",
        )
        logger.info("chroma_backup_uploaded", extra={"repo": repo_id, "path": str(source)})
        return True
    except Exception as exc:
        logger.warning("chroma_backup_failed", extra={"error": str(exc)})
        return False
    finally:
        if archive is not None:
            try:
                archive.unlink(missing_ok=True)
            except OSError:
                pass


def trigger_backup_debounced(
    path: str | Path | None = None,
    delay_seconds: float | None = None,
    min_interval_seconds: float | None = None,
) -> None:
    """Schedule one background backup after ingestion succeeds.

    Multiple completed source jobs in quick succession collapse into one upload.
    """
    if not _settings()[0]:
        return

    delay = float(delay_seconds or os.environ.get("CHROMA_BACKUP_DEBOUNCE_SECONDS", "300"))
    min_interval = float(
        min_interval_seconds or os.environ.get("CHROMA_BACKUP_MIN_INTERVAL_SECONDS", "300")
    )

    def _run() -> None:
        global _timer, _last_backup_at
        try:
            now = time.monotonic()
            if now - _last_backup_at >= min_interval:
                if backup(path):
                    _last_backup_at = time.monotonic()
        finally:
            with _lock:
                _timer = None

    global _timer
    with _lock:
        if _timer is not None:
            return
        _timer = threading.Timer(delay, _run)
        _timer.daemon = True
        _timer.start()


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore or back up Chroma snapshots.")
    parser.add_argument("command", choices=("restore", "backup"))
    parser.add_argument("--path", default=None, help="Chroma data directory")
    args = parser.parse_args()

    ok = restore(args.path) if args.command == "restore" else backup(args.path)
    return 0 if ok or args.command == "restore" else 1


if __name__ == "__main__":
    raise SystemExit(main())
