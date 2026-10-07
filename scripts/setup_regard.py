"""Telecharge le modele officiel MediaPipe utilise par le test du regard."""
from pathlib import Path
import urllib.request


RACINE = Path(__file__).resolve().parent.parent
MODELE = RACINE / "gestes" / "models" / "face_landmarker.task"
URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
       "face_landmarker/float16/1/face_landmarker.task")


def main():
    MODELE.parent.mkdir(parents=True, exist_ok=True)
    if MODELE.exists():
        print(f"Modele deja present : {MODELE}")
        return
    print("Telechargement du modele facial officiel MediaPipe (~4 Mo)...")
    urllib.request.urlretrieve(URL, MODELE)
    print(f"OK : {MODELE}")


if __name__ == "__main__":
    main()
