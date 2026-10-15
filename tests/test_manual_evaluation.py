import runpy
from pathlib import Path


def test_manual_evaluation_rejects_other_manual_even_when_page_number_matches() -> None:
    evaluator = runpy.run_path(str(Path(__file__).parents[1] / 'scripts' / 'evaluate_manual_cases.py'))
    matches = evaluator['documents_match']
    assert matches(['manual-b'], ['manual-b'])
    assert not matches(['manual-a'], ['manual-b'])
    assert not matches(['manual-b', 'manual-a'], ['manual-b'])
    assert not matches([], ['manual-b'])
    assert matches(['manual-a'], [])  # Compatibilità con i criteri storici senza vincolo.


def test_cross_manual_answer_must_include_all_required_documents():
    evaluator = runpy.run_path(str(Path(__file__).parents[1] / 'scripts' / 'evaluate_manual_cases.py'))
    matches = evaluator['documents_match']
    assert matches(['a', 'b'], ['a', 'b'], ['a', 'b'])
    assert not matches(['a'], ['a', 'b'], ['a', 'b'])
