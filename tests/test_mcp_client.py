"""Client MCP de démonstration : vrai dialogue client -> serveur (mode démo, stdio)."""

import asyncio

import pytest

pytest.importorskip("mcp")

from fri.mcp_server.client import (  # noqa: E402
    Call,
    default_plan,
    main,
    run_demo,
    summarize,
    to_markdown,
)


@pytest.fixture(scope="module")
def transcript():
    plan = default_plan("3M", "total revenue", 2017, 2018, None)
    return asyncio.run(run_demo(plan, demo=True))


def test_client_lists_the_three_tools(transcript):
    names = {t["name"] for t in transcript.tools}
    assert names == {"search_filings", "get_financial_metric", "compare_years"}
    compare = next(t for t in transcript.tools if t["name"] == "compare_years")
    assert compare["parameters"] == ["company", "metric", "year_a", "year_b"]


def test_client_calls_every_tool(transcript):
    assert [c.tool for c in transcript.calls] == [
        "search_filings",
        "get_financial_metric",
        "compare_years",
    ]
    assert all(c.error is None for c in transcript.calls)
    search, metric, compare = (c.result for c in transcript.calls)
    assert search[0]["chunk"]["metadata"]["page"] == 42
    assert metric["value"] == 32765
    assert compare["delta"] == pytest.approx(1108)


def test_summary_and_markdown(transcript):
    lines = summarize(transcript.calls[2])
    assert lines[0] == "2017 : 31 657 M$  [3M, 2017, p. 40]"
    assert lines[2].startswith("écart : +1 108 M$")
    md = to_markdown(transcript)
    assert "| `compare_years` |" in md
    assert "[3M, 2018, p. 42]" in md


def test_tool_error_is_reported(transcript):
    call = Call("compare_years", {}, error="Métrique introuvable")
    assert summarize(call) == ["Erreur renvoyée par l'outil : Métrique introuvable"]


def test_cli_writes_markdown(tmp_path, capsys):
    out = tmp_path / "mcp_demo.md"
    assert main(["--demo", "--markdown", str(out)]) == 0
    assert "3/3 appels réussis." in capsys.readouterr().out
    assert out.read_text(encoding="utf-8").startswith("# Démonstration du serveur MCP")
