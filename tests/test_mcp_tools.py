from fri.mcp_server.tools import compute_comparison
from fri.schemas import Citation, MetricValue


def _metric(year: int, value: float) -> MetricValue:
    return MetricValue(
        company="3M",
        year=year,
        metric="revenue",
        value=value,
        citation=Citation(company="3M", year=year, page=1),
    )


def test_compute_comparison():
    comp = compute_comparison(_metric(2017, 100.0), _metric(2018, 110.0))
    assert comp.delta == 10.0
    assert round(comp.pct_change, 2) == 10.0


def test_compute_comparison_zero_base():
    assert compute_comparison(_metric(2017, 0.0), _metric(2018, 5.0)).pct_change is None
