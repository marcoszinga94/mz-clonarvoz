"""Worker de VoxCPM2: modelo cargado una vez, pedidos por stdin."""

import argparse
import json
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="models/voxcpm2")
    args = ap.parse_args()

    import soundfile as sf
    from voxcpm import VoxCPM

    modelo = VoxCPM.from_pretrained(args.dir, load_denoiser=False)
    sr = int(modelo.tts_model.sample_rate)
    print(json.dumps({"ready": True, "sr": sr}), flush=True)

    for linea in sys.stdin:
        try:
            pedido = json.loads(linea)
        except ValueError:
            continue
        if pedido.get("cmd") == "exit":
            break
        try:
            wav = modelo.generate(text=pedido["text"],
                                  reference_wav_path=pedido["ref"])
            sf.write(pedido["out"], wav, sr)
            print(json.dumps({"id": pedido["id"], "ok": True, "sr": sr,
                              "dur": round(len(wav) / sr, 2)}), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"id": pedido.get("id"), "ok": False, "error": str(e)}), flush=True)


if __name__ == "__main__":
    main()
