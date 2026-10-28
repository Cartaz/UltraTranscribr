"""CPU acoustic alignment stages of the frozen English meeting pipeline.

Algorithms are transferred from the full public validation. Only automatically
recognized words are supplied to the models; no reference text is accepted.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import re
import unicodedata
from pathlib import Path

import numpy as np

from core.english_models import EnglishPipelineCancelled
from core.meeting_engine import ALIGNMENT_LANGUAGES, meeting_language


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise EnglishPipelineCancelled()


def _audio(path):
    import soundfile as sf

    pcm, sample_rate = sf.read(path, dtype="int16", always_2d=True)
    if sample_rate != 16000 or pcm.ndim != 2 or pcm.shape[1] != 1:
        raise ValueError("English alignment requires mono PCM at 16 kHz")
    return pcm, sample_rate


def ctc_path(emission, tokens, blank):
    """CTC Viterbi alignment, with free leading and trailing context."""
    if not tokens:
        return []
    labels = np.full(2 * len(tokens) + 1, blank, dtype=np.int64)
    labels[1::2] = tokens
    size = len(labels)
    dp = np.full(size, -np.inf, dtype=np.float32)
    dp[0] = 0.0
    trace = np.zeros((len(emission), size), dtype=np.uint8)
    skip = np.zeros(size, dtype=bool)
    skip[2:] = (labels[2:] != blank) & (labels[2:] != labels[:-2])
    best = -np.inf
    last = None
    for t in range(len(emission)):
        one = np.full_like(dp, -np.inf)
        one[1:] = dp[:-1]
        two = np.full_like(dp, -np.inf)
        two[2:] = dp[:-2]
        two[~skip] = -np.inf
        choices = np.vstack((dp, one, two))
        moves = np.argmax(choices, axis=0)
        dp = choices[moves, np.arange(size)] + emission[t, labels]
        dp[0] = 0.0
        trace[t] = moves
        state = size - 2 if dp[-2] >= dp[-1] else size - 1
        if dp[state] > best:
            best = float(dp[state])
            last = (t, state)
    if last is None or not np.isfinite(best):
        return None
    frames = [[] for _ in tokens]
    t, state = last
    while t >= 0 and state > 0:
        if state % 2:
            frames[(state - 1) // 2].append(t)
        state -= int(trace[t, state])
        t -= 1
    if state != 0 or any(not f for f in frames):
        return None
    return [sorted(f) for f in frames]


def group_segments(rows, maximum=20.0, gap=2.0):
    groups = []
    current = []
    for i, row in enumerate(rows):
        if current and (
            row["end"] - rows[current[0]]["start"] > maximum
            or row["start"] - rows[current[-1]]["end"] > gap
        ):
            groups.append(current)
            current = []
        current.append(i)
    if current:
        groups.append(current)
    return groups


def align_ctc_rows(
    audio_path: Path, rows, model_path: Path, *, cancel=None, progress=None
):
    """Run the validated CTC alignment on CPU, preserving recognized text."""
    import torch

    torch.set_num_threads(2)
    _check_cancel(cancel)
    pcm, sr = _audio(audio_path)
    result_rows = copy.deepcopy(rows)
    groups = group_segments(rows)
    calls = []
    fallback = 0
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    processor = Wav2Vec2Processor.from_pretrained(model_path, local_files_only=True)
    model = (
        Wav2Vec2ForCTC.from_pretrained(
            model_path,
            local_files_only=True,
            dtype=torch.float32,
            device_map=None,
            attn_implementation="sdpa",
        )
        .to("cpu")
        .eval()
    )
    vocab = processor.tokenizer.get_vocab()
    blank = processor.tokenizer.pad_token_id
    assert blank == model.config.pad_token_id
    for index, group in enumerate(groups, 1):
        _check_cancel(cancel)
        lo = max(0, round((min(rows[i]["start"] for i in group) - 0.5) * sr))
        hi = min(len(pcm), round((max(rows[i]["end"] for i in group) + 0.5) * sr))
        if hi - lo < 800:
            hi = min(len(pcm), lo + 800)
        assert hi > lo
        words = []
        tokens = []
        token_words = []
        for sid in group:
            pieces = re.findall(r"\s*\S+", rows[sid]["text"])
            assert "".join(pieces) == rows[sid]["text"]
            for wi, piece in enumerate(pieces):
                clean = "".join(
                    c
                    for c in unicodedata.normalize("NFKC", piece.upper())
                    if c in vocab and (c.isalpha() or c == "'")
                )
                word_index = len(words)
                words.append(
                    {
                        "segment": sid,
                        "piece": piece,
                        "index": wi,
                        "total": len(pieces),
                        "frames": [],
                        "scores": [],
                    }
                )
                if clean:
                    if tokens:
                        tokens.append(vocab["|"])
                        token_words.append(-1)
                    for character in clean:
                        tokens.append(vocab[character])
                        token_words.append(word_index)
        waveform = pcm[lo:hi, 0].astype(np.float32) / 32768.0
        features = processor(
            waveform, sampling_rate=sr, return_tensors="pt"
        ).input_values.to("cpu")
        with torch.inference_mode():
            emission = model(features).logits.float().log_softmax(-1)[0].cpu().numpy()
        assert np.isfinite(emission).all()
        path = ctc_path(emission, tokens, blank)
        if path is not None:
            for token, word_id, frames in zip(tokens, token_words, path):
                if word_id < 0:
                    continue
                words[word_id]["frames"].extend(frames)
                words[word_id]["scores"].extend(
                    np.exp(emission[frames, token]).tolist()
                )
        ratio = (hi - lo) / sr / len(emission)
        aligned = {sid: [] for sid in group}
        for word in words:
            source = rows[word["segment"]]
            if word["frames"]:
                a = lo / sr + min(word["frames"]) * ratio
                b = lo / sr + (max(word["frames"]) + 1) * ratio
            else:
                fallback += 1
                a = (
                    source["start"]
                    + (source["end"] - source["start"]) * word["index"] / word["total"]
                )
                b = (
                    source["start"]
                    + (source["end"] - source["start"])
                    * (word["index"] + 1)
                    / word["total"]
                )
            aligned[word["segment"]].append(
                {
                    "word": word["piece"],
                    "start": a,
                    "end": max(a, b),
                    "alignment_probability": float(np.mean(word["scores"]))
                    if word["scores"]
                    else None,
                    "alignment_fallback": not bool(word["frames"]),
                }
            )
        for sid, word_list in aligned.items():
            # Unalignable symbols (for example written numbers) retain
            # their text and occupy the gap between neighboring anchors.
            # They must not reorder the recognized sentence when the app
            # sorts word timestamps.
            position = 0
            while position < len(word_list):
                if not word_list[position]["alignment_fallback"]:
                    position += 1
                    continue
                end = position + 1
                while end < len(word_list) and word_list[end]["alignment_fallback"]:
                    end += 1
                left = (
                    word_list[position - 1]["end"]
                    if position
                    else min(
                        rows[sid]["start"],
                        word_list[end]["start"]
                        if end < len(word_list)
                        else rows[sid]["end"],
                    )
                )
                right = (
                    word_list[end]["start"]
                    if end < len(word_list)
                    else max(rows[sid]["end"], left)
                )
                right = max(left, right)
                for offset, k in enumerate(range(position, end)):
                    word_list[k]["start"] = left + (right - left) * offset / (
                        end - position
                    )
                    word_list[k]["end"] = left + (right - left) * (offset + 1) / (
                        end - position
                    )
                position = end
            assert "".join(w["word"] for w in word_list) == rows[sid]["text"]
            assert all(
                a["start"] <= b["start"] for a, b in itertools.pairwise(word_list)
            )
            result_rows[sid]["words"] = word_list
            result_rows[sid]["original_segment_interval"] = [
                rows[sid]["start"],
                rows[sid]["end"],
            ]
            result_rows[sid]["start"] = min(
                rows[sid]["start"], min(w["start"] for w in word_list)
            )
            result_rows[sid]["end"] = max(
                rows[sid]["end"], max(w["end"] for w in word_list)
            )
        calls.append(
            {
                "group": index,
                "segments": group,
                "source_start_frame": lo,
                "source_end_frame": hi,
                "pcm_sha256": hashlib.sha256(pcm[lo:hi, 0].tobytes()).hexdigest(),
                "emission_frames": len(emission),
                "target_characters": len(tokens),
                "ctc_path_found": path is not None,
            }
        )

        _check_cancel(cancel)
        if progress:
            progress(index, len(groups), result_rows, calls[-1])
    assert [row["text"] for row in result_rows] == [row["text"] for row in rows]
    return result_rows, calls


def align_qwen_rows(
    audio_path: Path, rows, model_path: Path, *, cancel=None, progress=None,
    language="en",
):
    """Run the independently validated Qwen forced alignment on CPU."""
    import torch

    torch.set_num_threads(2)
    _check_cancel(cancel)
    pcm, sr = _audio(audio_path)
    result_rows = copy.deepcopy(rows)
    groups = group_segments(rows)
    calls = []
    fallback = 0
    from transformers import AutoModelForTokenClassification, AutoProcessor

    language = ALIGNMENT_LANGUAGES[meeting_language(language)]
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    model = (
        AutoModelForTokenClassification.from_pretrained(
            model_path,
            local_files_only=True,
            dtype=torch.float32,
            device_map=None,
            attn_implementation="sdpa",
        )
        .to("cpu")
        .eval()
    )
    for index, group in enumerate(groups, 1):
        _check_cancel(cancel)
        lo = max(0, round((min(rows[i]["start"] for i in group) - 0.5) * sr))
        hi = min(len(pcm), round((max(rows[i]["end"] for i in group) + 0.5) * sr))
        waveform = pcm[lo:hi, 0].astype(np.float32) / 32768.0
        text = " ".join(rows[i]["text"] for i in group)
        inputs, word_lists = processor.prepare_forced_aligner_inputs(
            audio=waveform, transcript=text, language=language
        )
        inputs = inputs.to("cpu", torch.float32)
        with torch.inference_mode():
            output = model(**inputs)
        predictions = processor.decode_forced_alignment(
            logits=output.logits,
            input_ids=inputs["input_ids"],
            word_lists=word_lists,
            timestamp_token_id=model.config.timestamp_token_id,
        )[0]
        assert len(predictions) == len(word_lists[0])
        position = 0
        expected = []
        clamped = 0
        empty = 0
        for sid in group:
            word_list = []
            pieces = re.findall(r"\s*\S+", rows[sid]["text"])
            assert "".join(pieces) == rows[sid]["text"]
            for wi, piece in enumerate(pieces):
                tokens = processor.split_words_for_alignment(piece, language)
                expected.extend(tokens)
                selected = predictions[position : position + len(tokens)]
                position += len(tokens)
                if selected:
                    a = min(float(v["start_time"]) for v in selected)
                    b = max(float(v["end_time"]) for v in selected)
                    duration = (hi - lo) / sr
                    if a < 0 or b > duration:
                        clamped += 1
                    a = max(0.0, min(a, duration))
                    b = max(a, min(b, duration))
                    # Some timestamp classes can coincide. Use one native
                    # timestamp tick, and retain the original prediction.
                    if b <= a:
                        tick = float(processor.timestamp_segment_time) / 1000.0
                        a = min(a, max(0.0, duration - tick))
                        b = min(duration, a + tick)
                        empty += 1
                    a += lo / sr
                    b += lo / sr
                else:
                    fallback += 1
                    a = rows[sid]["start"] + (
                        rows[sid]["end"] - rows[sid]["start"]
                    ) * wi / len(pieces)
                    b = rows[sid]["start"] + (rows[sid]["end"] - rows[sid]["start"]) * (
                        wi + 1
                    ) / len(pieces)
                word_list.append(
                    {
                        "word": piece,
                        "start": a,
                        "end": b,
                        "alignment_fallback": not bool(selected),
                    }
                )
            # Punctuation-only pieces retain their text and fill the gap
            # between adjacent aligned anchors, preserving word order.
            position_in_segment = 0
            while position_in_segment < len(word_list):
                if not word_list[position_in_segment]["alignment_fallback"]:
                    position_in_segment += 1
                    continue
                end = position_in_segment + 1
                while end < len(word_list) and word_list[end]["alignment_fallback"]:
                    end += 1
                left = (
                    word_list[position_in_segment - 1]["end"]
                    if position_in_segment
                    else min(
                        rows[sid]["start"],
                        word_list[end]["start"]
                        if end < len(word_list)
                        else rows[sid]["end"],
                    )
                )
                right = (
                    word_list[end]["start"]
                    if end < len(word_list)
                    else max(rows[sid]["end"], left)
                )
                right = max(left, right)
                for off, k in enumerate(range(position_in_segment, end)):
                    word_list[k]["start"] = left + (right - left) * off / (
                        end - position_in_segment
                    )
                    word_list[k]["end"] = left + (right - left) * (off + 1) / (
                        end - position_in_segment
                    )
                position_in_segment = end
            assert "".join(w["word"] for w in word_list) == rows[sid]["text"]
            result_rows[sid]["words"] = word_list
            result_rows[sid]["original_segment_interval"] = [
                rows[sid]["start"],
                rows[sid]["end"],
            ]
            result_rows[sid]["start"] = min(
                rows[sid]["start"], min(w["start"] for w in word_list)
            )
            result_rows[sid]["end"] = max(
                rows[sid]["end"], max(w["end"] for w in word_list)
            )
        assert expected == word_lists[0] and position == len(predictions)
        calls.append(
            {
                "group": index,
                "segments": group,
                "source_start_frame": lo,
                "source_end_frame": hi,
                "pcm_sha256": hashlib.sha256(pcm[lo:hi, 0].tobytes()).hexdigest(),
                "words": word_lists[0],
                "native_predictions": predictions,
                "clamped_words": clamped,
                "zero_duration_words": empty,
            }
        )

        _check_cancel(cancel)
        if progress:
            progress(index, len(groups), result_rows, calls[-1])
    assert [row["text"] for row in result_rows] == [row["text"] for row in rows]
    return result_rows, calls
