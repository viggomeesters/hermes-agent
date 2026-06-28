from agent.eval_trajectory import EvalCheck, TrajectoryEventKind, append_event, grade_checks


def test_append_event_preserves_linear_history():
    trajectory = ()
    trajectory = append_event(trajectory, TrajectoryEventKind.USER, "fix bug")
    trajectory = append_event(trajectory, TrajectoryEventKind.TOOL, "pytest failed")

    assert [event.kind for event in trajectory] == [TrajectoryEventKind.USER, TrajectoryEventKind.TOOL]
    assert [event.message for event in trajectory] == ["fix bug", "pytest failed"]


def test_grade_checks_passes_only_when_all_checks_pass():
    verdict = grade_checks(
        [
            EvalCheck("tests", True, "3 passed"),
            EvalCheck("diff", True, "clean"),
        ]
    )

    assert verdict.passed is True
    assert verdict.score == 1.0
    assert verdict.failed_checks == ()


def test_grade_checks_reports_failed_checks_and_ratio():
    verdict = grade_checks(
        [
            EvalCheck("tests", True, "3 passed"),
            EvalCheck("browser", False, "not run"),
        ]
    )

    assert verdict.passed is False
    assert verdict.score == 0.5
    assert verdict.failed_checks == ("browser",)


def test_grade_checks_without_checks_fails():
    verdict = grade_checks([])

    assert verdict.passed is False
    assert verdict.score == 0.0
    assert verdict.failed_checks == ("no checks",)
