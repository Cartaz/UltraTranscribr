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


def test_new_segment_does_not_match_words_from_the_previous_one():
    committer = StablePrefixCommitter()
    committer.update("vai a casa")
    committer.update("vai a casa")
    committer.close_segment("vai a casa")
    # The new segment starts with words equal to the old tail; they are new
    # speech, not a re-transcription of committed audio.
    committer.update("casa nuova")
    second = committer.update("casa nuova oggi")
    assert second.committed_delta == "casa nuova"
    assert committer.committed_text == "vai a casa casa nuova"


def test_rewritten_committed_word_does_not_repeat_the_sentence():
    committer = StablePrefixCommitter()
    committer.update("oggi parliamo di analisi perché serve")
    committer.update("oggi parliamo di analisi perché serve")
    # The next hypothesis re-transcribes the committed audio with one word
    # spelled differently before adding new words.
    committer.update("oggi parliamo di analisi perchè serve molto")
    final = committer.update("oggi parliamo di analisi perchè serve molto tempo")
    assert final.committed_delta == "molto"
    assert committer.committed_text == "oggi parliamo di analisi perché serve molto"


def test_repeated_word_at_segment_edges_does_not_repeat_a_phrase():
    committer = StablePrefixCommitter()
    committer.update("io penso perché io")
    committer.update("io penso perché io")
    update = committer.update("io penso perchè io credo")
    assert update.pending_text == "credo"
    assert committer.committed_text == "io penso perché io"


def test_common_word_in_new_speech_does_not_swallow_the_words_before_it():
    committer = StablePrefixCommitter()
    committer.update("io penso che")
    committer.update("io penso che")
    update = committer.update("io penso che sia quello che voglio")
    assert update.pending_text == "sia quello che voglio"


def test_words_committed_after_a_segment_cut_are_not_typed_again():
    committer = StablePrefixCommitter()
    committer.update("a b c d e")
    committer.update("a b c d e")
    # The cut falls after "c": the head heard only "a b c", so "d e" came
    # from audio the next segment transcribes again.
    closed = committer.close_segment("a b c")
    assert closed.committed_delta == ""
    committer.update("d e f g")
    update = committer.update("d e f g h")
    assert update.committed_delta == "f g"
    assert committer.finalize().committed_text == "a b c d e f g h"


def test_segment_cut_commits_the_head_words_not_yet_typed():
    committer = StablePrefixCommitter()
    committer.update("a b c")
    committer.update("a b c d")
    closed = committer.close_segment("a b c d e")
    assert closed.committed_delta == "d e"
    assert committer.context_text == "a b c d e"


def test_hypothesis_unrelated_to_committed_words_keeps_all_its_words():
    committer = StablePrefixCommitter()
    committer.update("ciao a tutti")
    committer.update("ciao a tutti")
    update = committer.update("oggi parliamo di mercati")
    assert update.pending_text == "oggi parliamo di mercati"
