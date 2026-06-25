"""
Phase 4 — Sharded knowledge graph router.

Splits the entity space across N Neo4j instances by consistent hashing and
presents a single logical graph to the rest of the codebase. The Cypher and the
data model are unchanged from the single-node path; only the physical layout
changes. The simple single-Neo4j path in backend/db/neo4j.py remains the default
and the fallback — sharding is opt-in via USE_SHARDING=true (see is_enabled()).

Routing rule (identical everywhere, no routing table needed):
    shard = int(sha256(entity_name.lower()).hexdigest(), 16) % num_shards

Cross-shard edges are stored on the shard that owns the SOURCE entity, with a
lightweight stub node (is_stub=true, name+type only) standing in for the target
so the relationship is traversable locally. The owning shard holds the full
target node; the router resolves stubs on read.
"""
import os
import hashlib
import asyncio
from typing import Optional

from neo4j import AsyncGraphDatabase
from dotenv import load_dotenv

load_dotenv()


# Idempotent source attribution, identical to backend/db/neo4j.py so the sharded
# and single-node paths track contributing sources the same way (a node/edge can
# be asserted by several sources; this lets a source be detached precisely).
_ADD_SOURCE = """
    n.source_ids = CASE
        WHEN $source_id IS NULL THEN coalesce(n.source_ids, [])
        WHEN $source_id IN coalesce(n.source_ids, []) THEN n.source_ids
        ELSE coalesce(n.source_ids, []) + $source_id
    END,
    n.source_count = size(
        CASE
            WHEN $source_id IS NULL THEN coalesce(n.source_ids, [])
            WHEN $source_id IN coalesce(n.source_ids, []) THEN n.source_ids
            ELSE coalesce(n.source_ids, []) + $source_id
        END)
"""


def _row_key(row: dict) -> str:
    """Stable identity for a result row, used to de-dupe across shards. Falls
    back to repr for unhashable/odd shapes so de-duplication never throws."""
    try:
        return repr(sorted((k, repr(v)) for k, v in row.items()))
    except Exception:
        return repr(row)


def num_shards() -> int:
    return int(os.environ.get("NUM_SHARDS", 3))


def is_enabled() -> bool:
    """Sharding is opt-in. When false, callers use the single-node neo4j driver."""
    return os.environ.get("USE_SHARDING", "false").lower() in ("1", "true", "yes")


def shard_for(entity_name: str, shards: Optional[int] = None) -> int:
    """Deterministic shard index for an entity name. Stable across processes."""
    n = shards if shards is not None else num_shards()
    digest = hashlib.sha256(entity_name.strip().lower().encode()).hexdigest()
    return int(digest, 16) % n


def _shard_uri(i: int) -> str:
    """Per-shard bolt URI. Explicit env override wins; otherwise localhost ports
    7687/7688/7689 (the local-dev container mapping)."""
    env = os.environ.get(f"NEO4J_SHARD_{i}_URI")
    if env:
        return env
    return f"bolt://localhost:{7687 + i}"


def _auth():
    return (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])


class ShardRouter:
    """Holds an async driver per shard and routes reads/writes by entity name."""

    def __init__(self, shards: Optional[int] = None):
        self.n = shards if shards is not None else num_shards()
        self._drivers = [
            AsyncGraphDatabase.driver(
                _shard_uri(i), auth=_auth(),
                max_connection_pool_size=20,
                connection_acquisition_timeout=5,
            )
            for i in range(self.n)
        ]

    def shard_for(self, entity_name: str) -> int:
        return shard_for(entity_name, self.n)

    async def close(self) -> None:
        await asyncio.gather(*(d.close() for d in self._drivers), return_exceptions=True)

    # ── Writes ─────────────────────────────────────────────────────────────────

    async def merge_node(
        self, label: str, name: str, workspace_id: str,
        properties: dict = None, source_id: str = None,
    ):
        idx = self.shard_for(name)
        props = {**(properties or {}), "workspace_id": workspace_id, "shard_id": idx}
        async with self._drivers[idx].session() as s:
            await s.run(
                f"""
                MERGE (n:{label} {{name: $name, workspace_id: $ws}})
                ON CREATE SET n += $props, n.created_at = timestamp(), n.is_stub = false
                ON MATCH SET n.last_updated = timestamp(), n.is_stub = false
                SET {_ADD_SOURCE}
                """,
                name=name, ws=workspace_id, props=props, source_id=source_id,
            )

    async def merge_paper(
        self, paper_id: str, title: str, workspace_id: str,
        properties: dict = None, source_id: str = None,
    ):
        # Papers are keyed by arxiv_id; route by the id so lookups by id are O(1).
        idx = self.shard_for(paper_id)
        props = {**(properties or {}), "name": title, "workspace_id": workspace_id, "shard_id": idx}
        async with self._drivers[idx].session() as s:
            await s.run(
                f"""
                MERGE (n:Paper {{arxiv_id: $paper_id, workspace_id: $ws}})
                ON CREATE SET n += $props, n.created_at = timestamp(), n.is_stub = false
                ON MATCH SET n += $props, n.last_updated = timestamp(), n.is_stub = false
                SET {_ADD_SOURCE}
                """,
                paper_id=paper_id, ws=workspace_id, props=props, source_id=source_id,
            )

    async def merge_edge(
        self, source_name: str, source_label: str,
        target_name: str, target_label: str,
        edge_type: str, workspace_id: str, properties: dict = None,
        source_id: str = None,
    ):
        """Store the edge on the SOURCE entity's shard.

        Routing key is the node's identity: Paper by arxiv_id, everything else by
        name. If the target lives on a different shard, a stub target node is
        created locally so the relationship is traversable on the source shard.
        """
        src_key = source_name  # for Paper this is arxiv_id passed in as source_name
        idx = self.shard_for(src_key)
        tgt_idx = self.shard_for(target_name)
        props = {**(properties or {}), "workspace_id": workspace_id}

        # Endpoints are workspace-scoped so an edge never bridges two workspaces'
        # same-named nodes (mirrors the single-node multi-tenancy fix).
        src_match = (
            "(a:%s {arxiv_id: $src, workspace_id: $ws})" % source_label if source_label == "Paper"
            else "(a:%s {name: $src, workspace_id: $ws})" % source_label
        )
        tgt_id_field = "arxiv_id" if target_label == "Paper" else "name"
        tgt_match = "(b:%s {%s: $tgt, workspace_id: $ws})" % (target_label, tgt_id_field)

        async with self._drivers[idx].session() as s:
            # Ensure a (possibly stub) target node exists on the source shard,
            # keyed by (identity, workspace_id) just like a real node.
            await s.run(
                f"""
                MERGE (b:{target_label} {{{tgt_id_field}: $tgt, workspace_id: $ws}})
                ON CREATE SET b.created_at = timestamp(),
                              b.is_stub = $is_stub, b.shard_id = $tgt_idx
                """,
                tgt=target_name, ws=workspace_id,
                is_stub=(tgt_idx != idx), tgt_idx=tgt_idx,
            )
            await s.run(
                f"""
                MATCH {src_match}
                MATCH {tgt_match}
                MERGE (a)-[r:{edge_type}]->(b)
                ON CREATE SET r += $props, r.created_at = timestamp()
                ON MATCH SET r.last_updated = timestamp()
                SET {_ADD_SOURCE.replace('n.', 'r.')}
                """,
                src=source_name, tgt=target_name, ws=workspace_id,
                props=props, source_id=source_id,
            )

    # ── Reads ──────────────────────────────────────────────────────────────────

    async def is_paper_processed(self, paper_id: str, workspace_id: str) -> bool:
        idx = self.shard_for(paper_id)
        async with self._drivers[idx].session() as s:
            r = await s.run(
                "MATCH (n:Paper {arxiv_id: $pid, workspace_id: $ws}) "
                "RETURN n.entities_extracted AS done",
                pid=paper_id, ws=workspace_id,
            )
            rec = await r.single()
            return bool(rec and rec["done"])

    async def mark_paper_processed(self, paper_id: str, workspace_id: str) -> None:
        idx = self.shard_for(paper_id)
        async with self._drivers[idx].session() as s:
            await s.run(
                "MATCH (n:Paper {arxiv_id: $pid, workspace_id: $ws}) "
                "SET n.entities_extracted = true",
                pid=paper_id, ws=workspace_id,
            )

    async def get_entity(self, name: str) -> Optional[dict]:
        """Single-entity lookup: hits exactly one shard. Resolves a stub to the
        full node on its owning shard."""
        idx = self.shard_for(name)
        async with self._drivers[idx].session() as s:
            r = await s.run(
                "MATCH (n {name: $name}) RETURN n, labels(n) AS labels LIMIT 1", name=name)
            rec = await r.single()
        if not rec:
            return None
        node = dict(rec["n"])
        node["labels"] = rec["labels"]
        return node

    async def _neighbors(self, idx: int, name: str) -> set[str]:
        async with self._drivers[idx].session() as s:
            r = await s.run(
                """
                MATCH (n {name: $name})--(m)
                WHERE m.name IS NOT NULL
                RETURN collect(DISTINCT m.name) AS names
                """,
                name=name,
            )
            rec = await r.single()
            return set(rec["names"]) if rec and rec["names"] else set()

    async def find_connection(self, a: str, b: str) -> dict:
        """How is A connected to B? Single-shard fast path or scatter-gather.

        Returns {'shared_neighbors': [...], 'direct': bool, 'cross_shard': bool}.
        """
        sa, sb = self.shard_for(a), self.shard_for(b)

        if sa == sb:
            # Both on one shard — a normal local query handles any path length.
            async with self._drivers[sa].session() as s:
                r = await s.run(
                    """
                    MATCH (x {name:$a}), (y {name:$b})
                    OPTIONAL MATCH (x)--(z)--(y) WHERE z.name IS NOT NULL
                    WITH x, y, collect(DISTINCT z.name) AS shared
                    RETURN exists{ (x)--(y) } AS direct, shared
                    """,
                    a=a, b=b,
                )
                rec = await r.single()
            return {
                "cross_shard": False,
                "direct": bool(rec and rec["direct"]),
                "shared_neighbors": [n for n in (rec["shared"] if rec else []) if n],
            }

        # Cross-shard scatter-gather: pull each endpoint's neighbor set in
        # parallel from its own shard, then intersect for two-hop paths.
        na, nb = await asyncio.gather(self._neighbors(sa, a), self._neighbors(sb, b))
        shared = sorted(na & nb)
        direct = b in na or a in nb
        return {"cross_shard": True, "direct": direct, "shared_neighbors": shared}

    # ── Scatter-gather reads (used by graph_retriever under USE_SHARDING) ────────

    async def run_read(
        self, cypher: str, params: Optional[dict] = None, timeout: float = 15.0,
    ) -> list[dict]:
        """Execute a read-only Cypher on every shard in parallel and merge.

        This is the scatter-gather read path. Each shard holds a slice of the
        entity space plus stub nodes for cross-shard edge targets, so running the
        same workspace-scoped query on all shards and unioning the rows
        reconstructs the logical result the single-node graph would have returned.

        Identical-row de-duplication collapses a record that legitimately appears
        on more than one shard (e.g. a stub of an entity referenced from several
        shards). The Cypher itself is unchanged from the single-node path — only
        the physical fan-out differs (per CLAUDE.md: "keeps the Cypher identical").

        Caveat: a query that aggregates across the whole graph (e.g. a bare
        ``RETURN count(*)``) returns one partial row per shard rather than a
        global total; entity- and relationship-shaped queries — the overwhelming
        majority the router LLM emits — merge cleanly because their identifying
        columns (names, ids) survive the union.
        """
        params = params or {}

        async def _one(idx: int) -> list[dict]:
            try:
                async with self._drivers[idx].session() as s:
                    res = await asyncio.wait_for(s.run(cypher, **params), timeout)
                    return await res.data()
            except Exception:
                # A single shard being slow or down degrades gracefully to a
                # partial result rather than failing the whole query.
                return []

        per_shard = await asyncio.gather(*(_one(i) for i in range(self.n)))

        merged: list[dict] = []
        seen: set[str] = set()
        for rows in per_shard:
            for row in rows:
                key = _row_key(row)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(row)
        return merged

    async def entity_degree_context(
        self, workspace_id: str, names: list[str], timeout: float = 8.0,
    ) -> list[dict]:
        """Per-entity degree summed across shards.

        An entity's edges are split: outgoing cross-shard edges live on its own
        shard, while edges where it is the *target* live on the source entity's
        shard (pointing at a local stub of this entity). Each physical edge is
        counted on exactly one shard, so summing per-name degrees across shards
        yields the true total with no double counting.
        """
        if not names:
            return []
        cypher = """
            UNWIND $names AS nm
            MATCH (n {name: nm, workspace_id: $ws})
            OPTIONAL MATCH (n)-[r]-()
            WITH n.name AS name, labels(n)[0] AS lbl, count(r) AS deg
            RETURN name, lbl AS type, deg AS degree
        """
        params = {"names": names[:20], "ws": workspace_id}

        async def _one(idx: int) -> list[dict]:
            try:
                async with self._drivers[idx].session() as s:
                    res = await asyncio.wait_for(s.run(cypher, **params), timeout)
                    return await res.data()
            except Exception:
                return []

        per_shard = await asyncio.gather(*(_one(i) for i in range(self.n)))

        summed: dict[str, dict] = {}
        for rows in per_shard:
            for row in rows:
                name = row.get("name")
                if name is None:
                    continue
                agg = summed.setdefault(
                    name, {"name": name, "type": row.get("type"), "degree": 0})
                agg["degree"] += row.get("degree") or 0
                # Prefer a concrete (non-stub) label if a later shard supplies one.
                if agg["type"] is None and row.get("type") is not None:
                    agg["type"] = row["type"]

        return sorted(summed.values(), key=lambda r: r["degree"], reverse=True)[:20]

    # ── Maintenance / stats ─────────────────────────────────────────────────────

    async def node_counts(self) -> list[int]:
        async def _count(d):
            async with d.session() as s:
                r = await s.run("MATCH (n) WHERE coalesce(n.is_stub,false)=false RETURN count(n) AS c")
                return (await r.single())["c"]
        return list(await asyncio.gather(*(_count(d) for d in self._drivers)))

    async def setup_constraints(self) -> None:
        # Mirror the single-node schema: drop the obsolete global-name
        # constraints and key entities by (name|arxiv_id, workspace_id) so each
        # workspace owns its own nodes on every shard.
        from backend.db.neo4j import _OBSOLETE_CONSTRAINTS, ENTITY_LABELS
        drops = [f"DROP CONSTRAINT {name} IF EXISTS" for name in _OBSOLETE_CONSTRAINTS]
        creates = [
            f"CREATE CONSTRAINT {label.lower()}_name_ws IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE (n.name, n.workspace_id) IS UNIQUE"
            for label in ENTITY_LABELS
        ] + [
            "CREATE CONSTRAINT paper_arxiv_id_ws IF NOT EXISTS "
            "FOR (n:Paper) REQUIRE (n.arxiv_id, n.workspace_id) IS UNIQUE"
        ]
        for d in self._drivers:
            async with d.session() as s:
                for stmt in drops + creates:
                    await s.run(stmt)


# Module-global router (lazy), mirroring neo4j.py's driver lifecycle.
_router: Optional[ShardRouter] = None


def get_router() -> ShardRouter:
    global _router
    if _router is None:
        _router = ShardRouter()
    return _router


async def close_router() -> None:
    global _router
    if _router is not None:
        try:
            await _router.close()
        finally:
            _router = None
