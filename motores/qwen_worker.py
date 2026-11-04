"""Worker de Qwen3-TTS: carga el modelo una vez y atiende pedidos por stdin.

Se ejecuta con el intérprete de .venv-qwen (torch/transformers propios), así no
comparte dependencias con la app. Protocolo: una línea JSON por pedido y otra
por respuesta.
"""

import argparse
import json
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    args = ap.parse_args()

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    modelo = Qwen3TTSModel.from_pretrained(args.model, device_map="cpu", dtype=torch.float32)
    print(json.dumps({"ready": True}), flush=True)

    for linea in sys.stdin:
        try:
            pedido = json.loads(linea)
        except ValueError:
            continue
        if pedido.get("cmd") == "exit":
            break
        try:
            wavs, sr = modelo.generate_voice_clone(
                text=pedido["text"],
                language=pedido.get("language", "Spanish"),
                ref_audio=pedido["ref"],
                ref_text=pedido.get("ref_text", ""),
            )
            sf.write(pedido["out"], wavs[0], sr)
            print(json.dumps({"id": pedido["id"], "ok": True, "sr": sr,
                              "dur": round(len(wavs[0]) / sr, 2)}), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"id": pedido.get("id"), "ok": False, "error": str(e)}), flush=True)


if __name__ == "__main__":
    main()
