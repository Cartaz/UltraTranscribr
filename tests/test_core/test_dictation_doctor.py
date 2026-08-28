from tools.dictation_doctor import Check, exit_code


def test_doctor_exit_code_fails_only_on_fail():
    assert exit_code([Check("a", "ok", ""), Check("b", "warn", "")]) == 0
    assert exit_code([Check("a", "fail", "")]) == 1
