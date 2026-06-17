from backend.core.llm_client import generate_json

DISCOVERY_PROMPT = """You are configuring a research knowledge graph.
Given the workspace description below, suggest 2-4 ArXiv category slugs
that best cover the research area.

Return ONLY JSON: {{"categories": ["cs.AI", "stat.ML"]}}

Common slugs (use only real ones):
cs.AI  cs.LG  cs.CL  cs.CV  cs.RO  cs.NE  cs.SE  cs.CR  cs.IR  cs.DB
stat.ML  stat.AP  econ.GN  econ.EM  q-fin.GN  q-bio.NC  q-bio.GN
physics.soc-ph  cond-mat.mes-hall  math.OC  astro-ph.IM

Workspace description: {description}"""


async def suggest_arxiv_categories(description: str) -> list[str]:
    data = await generate_json(DISCOVERY_PROMPT.format(description=description))
    cats = data.get("categories", [])
    valid = [
        c for c in cats
        if isinstance(c, str) and "." in c and 3 <= len(c) <= 20
    ]
    return valid[:4]
