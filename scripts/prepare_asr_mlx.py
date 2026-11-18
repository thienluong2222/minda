"""Convert the pinned local PhoWhisper snapshot; never download model weights."""

import argparse
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path


def main():
    import mlx.core as mx
    import yaml
    from mlx.utils import tree_flatten

    parser = argparse.ArgumentParser()
    parser.add_argument("--download-converter", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    config = yaml.safe_load((root / "configs/default.yaml").read_text())
    asr = config["asr"]
    source = (
        root
        / config["paths"]["model_cache_dir"]
        / ("models--" + asr["model_id"].replace("/", "--"))
        / "snapshots"
        / asr["model_revision"]
    )
    converter = root / "data/runtime/asr_mlx/convert_upstream.py"
    if not converter.is_file() and args.download_converter:
        import urllib.request

        url = "https://raw.githubusercontent.com/ml-explore/mlx-examples/main/whisper/convert.py"
        converter.parent.mkdir(parents=True, exist_ok=True)
        converter.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    expected = "1f1de41ac5d3faeb241bcea97a3f99c760b802cd92e02715699c17b5658f5cb2"
    if hashlib.sha256(converter.read_bytes()).hexdigest() != expected:
        raise ValueError("Converter SHA256 mismatch; review the upstream converter first.")
    spec = importlib.util.spec_from_file_location("reviewed_mlx_converter", converter)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.convert(str(source), mx.float16)
    output = (
        root
        / config["paths"]["model_cache_dir"]
        / "asr_mlx"
        / asr["model_id"].replace("/", "--")
        / asr["model_revision"]
    )
    output.mkdir(parents=True, exist_ok=True)
    mx.save_safetensors(str(output / "weights.safetensors"), dict(tree_flatten(model.parameters())))
    (output / "config.json").write_text(json.dumps(dataclasses.asdict(model.dims)))
    generation = json.loads((source / "generation_config.json").read_text())
    manifest = {
        "model_id": asr["model_id"],
        "revision": asr["model_revision"],
        "dtype": "float16",
        "converter_sha256": expected,
        "alignment_heads": generation["alignment_heads"],
        "weights_sha256": hashlib.sha256((output / "weights.safetensors").read_bytes()).hexdigest(),
    }
    (output / "conversion.json").write_text(json.dumps(manifest, indent=2))
    print(output, flush=True)


if __name__ == "__main__":
    main()
