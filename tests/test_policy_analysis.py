import pytest

from content_eval.models import Evaluation
from content_eval.policy_analysis import filter_decision


@pytest.mark.parametrize(
    ("scores", "threshold", "expected"),
    [
        ({"a": 0.97, "b": 0.86}, 0.9, "withhold"),
        ({"a": 0.97, "b": 0.86}, 0.5, "pass"),
        ({"a": 0.05, "b": 0.86}, 0.5, "withhold"),
        ({"a": 0.5, "b": 1.0}, 0.5, "withhold"),
        ({"a": 0.9, "b": 0.9}, 0.9, "pass"),
        ({"a": 1.0}, 0.5, "unresolved"),
    ],
)
def test_filter_rules(scores: dict[str, float], threshold: float, expected: str) -> None:
    evaluation = Evaluation(checks=scores, uncertain=True)
    assert filter_decision(evaluation, ("a", "b"), threshold, "jev")[0] == expected
    assert evaluation.uncertain  # Never erase the saved uncertainty signal.


def test_explicit_llm_uncertainty_and_critical_failure_cannot_pass() -> None:
    uncertain = Evaluation(checks={"a": 1.0}, uncertain=True)
    assert filter_decision(uncertain, ("a",), 0.5, "llm") == ("withhold", "categorical_uncertainty")
    critical = Evaluation(checks={"a": 1.0}, critical_failures=("unsafe",))
    assert filter_decision(critical, ("a",), 0.5, "jev") == ("withhold", "critical_failure")


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), 0, 0.49, 1.1])
def test_invalid_threshold(threshold: float) -> None:
    with pytest.raises(ValueError, match="threshold"):
        filter_decision(Evaluation(checks={"a": 1}), ("a",), threshold, "jev")
