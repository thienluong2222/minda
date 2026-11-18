"""JSON-lines bridge from mlx-whisper to the existing ASR quality/timestamp contract."""

import argparse
import contextlib
import json
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        from pathlib import Path

        import mlx.core as mx
        import numpy as np
        from mlx_whisper.audio import HOP_LENGTH, N_FRAMES, log_mel_spectrogram, pad_or_trim
        from mlx_whisper.decoding import DecodingOptions, decode
        from mlx_whisper.timing import add_word_timestamps
        from mlx_whisper.tokenizer import get_tokenizer
        from mlx_whisper.transcribe import ModelHolder

        manifest = json.loads((Path(args.model) / "conversion.json").read_text())
        model = ModelHolder.get_model(args.model, mx.float16)
        model.set_alignment_heads(np.asarray(manifest["alignment_heads"], dtype=int))
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                audio = np.load(request["audio"], allow_pickle=False)
                if audio.ndim != 1 or len(audio) > 30 * 16000:
                    raise ValueError("MLX worker chỉ nhận một cửa sổ mono tối đa 30 giây.")
                mel = pad_or_trim(
                    log_mel_spectrogram(audio, n_mels=model.dims.n_mels), N_FRAMES, axis=0
                )
                result = decode(
                    model,
                    mel,
                    DecodingOptions(
                        language=request["language"],
                        task="transcribe",
                        temperature=request["temperature"],
                        sample_len=request["max_tokens"],
                        without_timestamps=True,
                        fp16=True,
                    ),
                )
                segments = [
                    {
                        "seek": 0,
                        "start": 0,
                        "end": len(audio) / 16000,
                        "tokens": result.tokens,
                        "text": result.text,
                    }
                ]
                tokenizer = get_tokenizer(
                    model.is_multilingual,
                    num_languages=model.num_languages,
                    language=request["language"],
                    task="transcribe",
                )
                add_word_timestamps(
                    segments=segments,
                    model=model,
                    tokenizer=tokenizer,
                    mel=mel,
                    num_frames=min(N_FRAMES, len(audio) // HOP_LENGTH),
                    last_speech_timestamp=0,
                )
            chunks = [
                {"text": w["word"], "timestamp": [w["start"], w["end"]]}
                for s in segments
                for w in s.get("words", [])
            ]
            print(
                json.dumps({"text": result.text, "chunks": chunks}, ensure_ascii=False),
                flush=True,
            )
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), flush=True)


if __name__ == "__main__":
    main()
