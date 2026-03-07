import os
from pathlib import Path

import requests


BASE_URL = "https://oise.fr/fileadmin/user_upload/docs/oise-magazine/oise-magazine-{num}-web.pdf"
START_NUM = 1
END_NUM = 38  # inclusive


def download_oise_magazines(output_dir: Path | str = "static") -> None:
    """
    Télécharge les PDF des magazines Oise de START_NUM à END_NUM
    et les enregistre dans le dossier `output_dir`.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for i in range(START_NUM, END_NUM + 1):
        url = BASE_URL.format(num=i)
        filename = f"oise-magazine-{i}-web.pdf"
        dest_file = output_path / filename

        print(f"Téléchargement du numéro {i} depuis {url} ...")

        try:
            response = requests.get(url, stream=True, timeout=30)
        except requests.RequestException as e:
            print(f"  ÉCHEC (erreur réseau) pour {i}: {e}")
            continue

        if response.status_code != 200:
            print(f"  ÉCHEC (HTTP {response.status_code}) pour {i}")
            continue

        try:
            with open(dest_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        except OSError as e:
            print(f"  ÉCHEC (écriture fichier) pour {i}: {e}")
            continue

        print(f"  OK → {dest_file}")


if __name__ == "__main__":
    # Télécharge dans ./static par défaut
    download_oise_magazines()

