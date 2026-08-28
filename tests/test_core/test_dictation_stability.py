from core.dictation_stability import StablePrefixCommitter


def test_stable_prefix_requires_repeated_hypothesis_prefix():
    committer = StablePrefixCommitter()
    first = committer.update("Domani mattina devo andare al")
    assert first.committed_delta == ""
    second = committer.update("Domani mattina devo andare al supermercato")
    assert second.committed_delta == "Domani mattina devo andare al"
    assert second.pending_text == "supermercato"


def test_rolling_overlap_is_not_emitted_twice():
    committer = StablePrefixCommitter()
    committer.update("hello world")
    second = committer.update("hello world today")
    assert second.committed_delta == "hello world"
    third = committer.update("world today again")
    assert third.committed_delta == "today"
    assert third.pending_text == "again"


def test_finalize_commits_unstable_tail():
    committer = StablePrefixCommitter()
    committer.update("hello world")
    final = committer.finalize()
    assert final.committed_delta == "hello world"
    assert final.committed_text == "hello world"
