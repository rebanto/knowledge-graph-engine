import importlib.util
import os
import sys
from pathlib import Path

import grpc
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rq import Queue, Worker

from backend.db.models import Workspace
from backend.db.postgres import get_async_db
from backend.db.redis import get_sync_client
from backend.coordinator import coordinator_pb2 as pb
from backend.coordinator import coordinator_pb2_grpc as pb_grpc

router = APIRouter()

# Repo root: backend/api/routes/system.py -> parents[3] is the project directory.
# The MCP server is launched as `python -m backend.mcp.server`, which needs this
# directory importable; we pin it via PYTHONPATH so the config works even when the
# MCP client (Claude Desktop, Cursor) launches the process from an unrelated cwd.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# The env vars the MCP server needs to reach the same databases/LLM as the API.
# We copy whatever the running API process already has set (so the generated
# config is self-contained and doesn't rely on the client finding .env). Only
# these keys are ever exported, never the full environment.
_MCP_ENV_KEYS = (
    "GEMINI_API_KEY", "LLM_MODEL",
    "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD",
    "CHROMA_HOST", "CHROMA_PORT", "CHROMA_PERSIST_DIR",
    "USE_SHARDING", "NUM_SHARDS",
    "NEO4J_SHARD_0_URI", "NEO4J_SHARD_1_URI", "NEO4J_SHARD_2_URI",
    "USE_RERANKER",
)


def _coordinator_addresses() -> list[str]:
    """Where to look for the coordinator's gRPC port.

    In Docker the coordinator is reachable by its service name; a host-run API
    (dev.ps1) reaches the same container on the published localhost port. Try the
    configured host first, then localhost, so the dashboard works in both setups.
    """
    host = os.environ.get("COORDINATOR_HOST", "localhost")
    port = os.environ.get("COORDINATOR_PORT", "50051")
    candidates = [f"{host}:{port}"]
    if host not in ("localhost", "127.0.0.1"):
        candidates.append(f"localhost:{port}")
    return candidates


async def _fetch_cluster_status(timeout: float = 2.0):
    """Call GetStatus on the first reachable coordinator address, or None."""
    for addr in _coordinator_addresses():
        try:
            async with grpc.aio.insecure_channel(addr) as channel:
                stub = pb_grpc.CoordinatorStub(channel)
                return await stub.GetStatus(pb.StatusRequest(), timeout=timeout)
        except Exception:
            continue
    return None


@router.get("/system/queue")
def queue_status():
    """RQ worker health and queue depths — used by the Sources UI to show worker state."""
    conn = get_sync_client()

    workers = Worker.all(connection=conn)
    worker_info = [
        {
            "name": w.name,
            "state": w.get_state(),
            "queues": [q.name for q in w.queues],
            "current_job_id": w.get_current_job_id(),
        }
        for w in workers
    ]

    queue_info = {}
    for name in ["ingestion", "ingestion_bulk", "ingestion_dlq"]:
        q = Queue(name, connection=conn)
        queue_info[name] = {
            "queued": q.count,
            "started": q.started_job_registry.count,
            "failed": q.failed_job_registry.count,
        }

    return {
        "worker_count": len(worker_info),
        "workers": worker_info,
        "queues": queue_info,
    }


@router.get("/system/coordinator")
async def coordinator_status():
    """Live status of the Phase 3 distributed worker pool, for the dashboard.

    Returns {available: false} when the coordinator isn't running (the default
    local setup uses the single RQ worker) so the UI can show a calm 'not
    enabled' state instead of an error.
    """
    status = await _fetch_cluster_status()
    if status is None:
        return {"available": False}

    workers = [
        {
            "worker_id": w.worker_id,
            "host": w.host,
            "state": w.state,
            "batch_id": w.batch_id or None,
            "completed": w.completed,
            "total": w.total,
            "seconds_since_heartbeat": round(w.seconds_since_heartbeat, 1),
        }
        for w in status.workers
    ]
    live = sum(1 for w in workers if w["state"] != "dead")
    return {
        "available": True,
        "pending": status.pending,
        "reassignments": status.reassignments,
        "dead_workers": status.dead_workers,
        "heartbeat_timeout_secs": status.heartbeat_timeout_secs,
        "worker_count": len(workers),
        "live_worker_count": live,
        "workers": workers,
    }


def _app_support_dir() -> Path:
    """The OS-appropriate per-user app-data directory. Derived at request time
    from the CURRENT user's environment/home, so every path we hand out is
    correct for whoever is running the backend, never hard-coded to one user."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
    return Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))


def _mcp_clients(server_name: str, entry: dict) -> list[dict]:
    """The major MCP clients, each with its OWN config schema and file location.

    The schema genuinely differs between clients: Claude Desktop / Cursor /
    Windsurf / Cline use the `mcpServers` object; VS Code uses a top-level
    `servers` map and requires `type: "stdio"`. We therefore emit a per-client,
    ready-to-paste `config` in exactly that client's shape, not one block the
    user has to hand-translate.

    Every path is computed from the current user's home/env, so it resolves for
    any user on macOS, Windows, or Linux. Paths that depend on the user's own
    working project (Claude Code, "any other client") are returned as null and
    the UI falls back to instructions.
    """
    home = Path.home()
    app = _app_support_dir()

    # Standard `mcpServers` block (Claude Desktop, Cursor, Windsurf, Cline, etc.).
    mcp_servers = {"mcpServers": {server_name: entry}}
    # VS Code wants a top-level `servers` map with an explicit stdio type.
    vscode = {"servers": {server_name: {"type": "stdio", **entry}}}

    return [
        {
            "key": "claude_desktop",
            "label": "Claude Desktop",
            "config_path": str(app / "Claude" / "claude_desktop_config.json"),
            "path_scope": "global",
            "filename": "claude_desktop_config.json",
            "docs": "Settings > Developer > Edit Config",
            "format": "mcpServers",
            "config": mcp_servers,
        },
        {
            "key": "claude_code",
            "label": "Claude Code",
            # Lives in whatever project the user runs `claude` in, so there is no
            # single path; the UI shows the block + the CLI one-liner instead.
            "config_path": None,
            "path_scope": "project",
            "filename": ".mcp.json",
            "docs": "Add to your project's .mcp.json, or run: claude mcp add-json",
            "format": "mcpServers",
            "config": mcp_servers,
        },
        {
            "key": "cursor",
            "label": "Cursor",
            "config_path": str(home / ".cursor" / "mcp.json"),
            "path_scope": "global",
            "filename": "mcp.json",
            "docs": "Settings > MCP > Add new global MCP server (or a per-project .cursor/mcp.json)",
            "format": "mcpServers",
            "config": mcp_servers,
        },
        {
            "key": "windsurf",
            "label": "Windsurf",
            "config_path": str(home / ".codeium" / "windsurf" / "mcp_config.json"),
            "path_scope": "global",
            "filename": "mcp_config.json",
            "docs": "Cascade > MCP servers > Manage > View raw config",
            "format": "mcpServers",
            "config": mcp_servers,
        },
        {
            "key": "vscode",
            "label": "VS Code",
            "config_path": str(_PROJECT_ROOT / ".vscode" / "mcp.json"),
            "path_scope": "workspace",
            "filename": "mcp.json",
            "docs": "Command Palette > MCP: Add Server, or create .vscode/mcp.json",
            "format": "vscode",
            "config": vscode,
        },
        {
            "key": "other",
            "label": "Other client",
            "config_path": None,
            "path_scope": "",
            "filename": "",
            "docs": "Any MCP-compatible client: add this stdio server to its config.",
            "format": "mcpServers",
            "config": mcp_servers,
        },
    ]


@router.get("/system/mcp-config")
async def mcp_config(
    workspace_id: str = "arxiv_seed",
    db: AsyncSession = Depends(get_async_db),
):
    """A ready-to-paste MCP config that turns this engine into grounded memory
    for the user's other AI tools (Claude Desktop, Claude Code, Cursor, Windsurf,
    VS Code, etc.).

    Everything is computed for THIS machine and user at request time: the Python
    interpreter running the API (`sys.executable`), the project directory, the
    current user's home/app-data dirs, and the database/LLM settings the API is
    already using. Nothing is hard-coded to a particular user or install path, so
    the user copies one block, restarts their AI tool, and it works. The values
    come from the running server; nothing here is a new secret, but the block
    contains the API key, so the UI warns the user to keep it private.
    """
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found")

    server_name = "knowledge-graph-engine"

    env = {"MCP_DEFAULT_WORKSPACE": workspace_id}
    for key in _MCP_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = val
    # Pin the import root so `python -m backend.mcp.server` resolves regardless of
    # the working directory the AI tool launches it from. `command`/`args` are
    # kept as separate array elements (never a shell string) so paths containing
    # spaces, e.g. C:\Users\John Doe\..., work without quoting.
    env["PYTHONPATH"] = str(_PROJECT_ROOT)

    entry = {
        "command": sys.executable,
        "args": ["-m", "backend.mcp.server"],
        "cwd": str(_PROJECT_ROOT),
        "env": env,
    }

    # Heuristic: if the API reaches its databases by Docker service name, the
    # user's host-launched MCP process can't resolve those hostnames. Flag it so
    # the UI can tell the user to swap in localhost.
    docker_hosts = any(
        (os.environ.get(k) or "").startswith(("bolt://neo4j", "bolt://kgre"))
        for k in ("NEO4J_URI", "NEO4J_SHARD_0_URI")
    ) or (os.environ.get("CHROMA_HOST", "") or "").startswith(("neo4j", "kgre", "chroma"))

    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace.name,
        "server_name": server_name,
        "mcp_installed": importlib.util.find_spec("mcp") is not None,
        "python": sys.executable,
        "project_root": str(_PROJECT_ROOT),
        "platform": sys.platform,
        "docker_hosts": docker_hosts,
        "gemini_key_present": bool(os.environ.get("GEMINI_API_KEY")),
        "clients": _mcp_clients(server_name, entry),
    }
