"""Client MCP de démonstration : lance notre serveur et appelle ses outils.

C'est un vrai client MCP (SDK ``mcp``) : il démarre ``python -m fri.mcp_server.server``
comme sous-processus, dialogue avec lui en JSON-RPC sur stdio, liste les outils puis
appelle ``search_filings``, ``get_financial_metric`` et ``compare_years``.

Usage :
    python -m fri.mcp_server.client --demo                 # sans index ni clé API
    python -m fri.mcp_server.client                        # vrai index (+ LLM du .env)
    python -m fri.mcp_server.client --company 3M --metric "total revenue" \\
        --year-a 2018 --year-b 2022 --query "capital expenditures"
    python -m fri.mcp_server.client --demo --markdown docs/mcp_demo.md   # trace pour le rapport
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

DEMO_DEFAULTS = {"company": "3M", "metric": "total revenue", "year_a": 2017, "year_b": 2018}
INDEX_DEFAULTS = {"company": "3M", "metric": "total revenue", "year_a": 2018, "year_b": 2022}


@dataclass
class Call:
    tool: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    seconds: float = 0.0


@dataclass
class Transcript:
    server: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    server_logs: list[str] = field(default_factory=list)


def _payload(result: Any) -> tuple[Any, str | None]:
    """Contenu d'un ``CallToolResult`` : la donnée structurée, ou le texte d'erreur."""
    texts = [getattr(c, "text", "") for c in result.content or []]
    if result.isError:
        return None, " ".join(t for t in texts if t) or "erreur inconnue"
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # FastMCP enveloppe les listes dans {"result": [...]}.
        if set(structured) == {"result"}:
            return structured["result"], None
        return structured, None
    if len(texts) == 1:
        try:
            return json.loads(texts[0]), None
        except json.JSONDecodeError:
            return texts[0], None
    return [json.loads(t) for t in texts], None


async def run_demo(
    plan: list[tuple[str, dict[str, Any]]], demo: bool, server_args: list[str] | None = None
) -> Transcript:
    """Démarre le serveur, liste les outils, exécute ``plan`` et renvoie la trace."""
    from mcp import StdioServerParameters

    args = ["-m", "fri.mcp_server.server", *(["--demo"] if demo else []), *(server_args or [])]
    # env : on transmet l'environnement (INDEX_DIR, clés API...) ; le SDK n'en passe qu'une partie.
    params = StdioServerParameters(
        command=sys.executable,
        args=args,
        cwd=str(ROOT),
        # PYTHONIOENCODING : sous Windows, les logs du serveur sont sinon en cp1252.
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    transcript = Transcript(server=" ".join(["python", *args]))

    # Les logs du serveur (stderr) vont dans un fichier : seules ses lignes [fri] sont montrées.
    # Fichier binaire : on décode nous-mêmes, sans planter sur un accent mal encodé.
    with tempfile.TemporaryFile("w+b") as errlog:
        try:
            await _session(params, plan, transcript, errlog)
        finally:
            errlog.seek(0)
            logs = errlog.read().decode("utf-8", errors="replace")
            transcript.server_logs = [ln for ln in logs.splitlines() if ln.startswith("[fri]")]
            if not transcript.tools:  # le serveur n'a pas démarré : montrer pourquoi
                print(logs[-2000:], file=sys.stderr)
    return transcript


async def _session(params, plan, transcript: Transcript, errlog) -> None:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with (
        stdio_client(params, errlog=errlog) as (read, write),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        transcript.server += f"  ({init.serverInfo.name})"
        listed = await session.list_tools()
        transcript.tools = [
            {
                "name": t.name,
                "description": (t.description or "").strip().splitlines()[0],
                "parameters": list((t.inputSchema or {}).get("properties", {})),
            }
            for t in listed.tools
        ]
        for tool, arguments in plan:
            start = time.perf_counter()
            result = await session.call_tool(tool, arguments)
            data, error = _payload(result)
            transcript.calls.append(
                Call(tool, arguments, data, error, round(time.perf_counter() - start, 2))
            )


def default_plan(
    company: str, metric: str, year_a: int, year_b: int, query: str | None
) -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "search_filings",
            {"query": query or metric, "company": company, "year": year_b, "k": 3},
        ),
        ("get_financial_metric", {"company": company, "year": year_b, "metric": metric}),
        (
            "compare_years",
            {"company": company, "metric": metric, "year_a": year_a, "year_b": year_b},
        ),
    ]


# --------------------------------------------------------------------------- #
# Affichage
# --------------------------------------------------------------------------- #
def _cite(c: dict[str, Any]) -> str:
    return f"[{c['company']}, {c['year']}, p. {c['page']}]"


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " M$"


def summarize(call: Call) -> list[str]:
    """Quelques lignes lisibles pour un appel d'outil."""
    if call.error:
        return [f"Erreur renvoyée par l'outil : {call.error}"]
    data = call.result
    if call.tool == "search_filings":
        lines = [f"{len(data)} passage(s)"]
        for r in data:
            m = r["chunk"]["metadata"]
            text = " ".join(r["chunk"]["text"].split())
            lines.append(f"  {_cite(m)} score {r['score']:.3f} : {text[:110]}...")
        return lines
    if call.tool == "get_financial_metric":
        return [f"{data['metric']} = {_money(data['value'])}  {_cite(data['citation'])}"]
    if call.tool == "compare_years":
        a, b = data["year_a"], data["year_b"]
        pct = data.get("pct_change")
        return [
            f"{a['year']} : {_money(a['value'])}  {_cite(a['citation'])}",
            f"{b['year']} : {_money(b['value'])}  {_cite(b['citation'])}",
            f"écart : {data['delta']:+,.0f} M$".replace(",", " ")
            + (f"  ({pct:+.1f} %)" if pct is not None else ""),
        ]
    return [json.dumps(data, ensure_ascii=False)[:300]]


def to_text(t: Transcript) -> str:
    lines = [f"Serveur MCP : {t.server}", *t.server_logs, "", f"Outils exposés ({len(t.tools)}) :"]
    for tool in t.tools:
        lines.append(f"  - {tool['name']}({', '.join(tool['parameters'])}) : {tool['description']}")
    for i, call in enumerate(t.calls, start=1):
        args = json.dumps(call.arguments, ensure_ascii=False)
        lines += ["", f"[{i}] {call.tool} {args}  ({call.seconds} s)"]
        lines += [f"    {line}" for line in summarize(call)]
    ok = sum(1 for c in t.calls if not c.error)
    lines += ["", f"{ok}/{len(t.calls)} appels réussis."]
    return "\n".join(lines)


def to_markdown(t: Transcript) -> str:
    out = [
        "# Démonstration du serveur MCP",
        "",
        "Trace produite par `python -m fri.mcp_server.client` : un client MCP (SDK `mcp`) lance "
        "le serveur sur stdio, liste ses outils et les appelle.",
        "",
        f"Serveur : `{t.server}`",
        "",
        "| Outil | Paramètres | Description |",
        "|---|---|---|",
    ]
    out += [
        f"| `{x['name']}` | {', '.join(x['parameters'])} | {x['description']} |" for x in t.tools
    ]
    for i, call in enumerate(t.calls, start=1):
        out += [
            "",
            f"## {i}. `{call.tool}` ({call.seconds} s)",
            "",
            "```json",
            json.dumps(call.arguments, ensure_ascii=False, indent=2),
            "```",
            "",
            "```text",
            *summarize(call),
            "```",
        ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Client MCP de démonstration.")
    parser.add_argument("--demo", action="store_true", help="serveur en mode démo (sans index)")
    parser.add_argument("--company")
    parser.add_argument("--metric")
    parser.add_argument("--year-a", type=int)
    parser.add_argument("--year-b", type=int)
    parser.add_argument("--query", help="requête de search_filings (défaut : la métrique)")
    parser.add_argument("--markdown", type=Path, help="écrit aussi la trace en Markdown")
    args = parser.parse_args(argv)

    defaults = DEMO_DEFAULTS if args.demo else INDEX_DEFAULTS
    company = args.company or defaults["company"]
    metric = args.metric or defaults["metric"]
    year_a = args.year_a or defaults["year_a"]
    year_b = args.year_b or defaults["year_b"]
    plan = default_plan(company, metric, year_a, year_b, args.query)

    transcript = asyncio.run(run_demo(plan, demo=args.demo))
    print(to_text(transcript))
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(to_markdown(transcript), encoding="utf-8")
        print(f"Trace écrite dans {args.markdown}")
    return 0 if transcript.calls and not any(c.error for c in transcript.calls[:1]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
