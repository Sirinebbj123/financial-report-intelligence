import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "download_financebench", Path(__file__).parents[1] / "data" / "download_financebench.py"
)
dl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dl)


def _write_questions(path: Path) -> Path:
    rows = [
        {"company": "3M", "doc_name": "3M_2018_10K"},
        {"company": "3M", "doc_name": "3M_2022_10K"},
        {"company": "AMD", "doc_name": "AMD_2022_10K"},
        {"company": "3M", "doc_name": "3M_2018_10K"},
        {"company": "Boeing", "doc_name": "BOEING_2022_10K"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def test_select_documents_limits_companies(tmp_path):
    q = _write_questions(tmp_path / "q.jsonl")
    assert dl.select_documents(q, 2) == ["3M_2018_10K", "3M_2022_10K", "AMD_2022_10K"]


def test_select_documents_no_duplicates(tmp_path):
    q = _write_questions(tmp_path / "q.jsonl")
    docs = dl.select_documents(q, 10)
    assert len(docs) == len(set(docs)) == 4
