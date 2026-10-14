import os
import re


def source_code(request):
    revision = os.getenv("SENTINELLE_SOURCE_REVISION", "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        return {"source_code_url": ""}
    return {
        "source_code_url": (
            "https://github.com/XavierMombimbo/projet_maison_intelligente/"
            f"archive/{revision}.zip"
        )
    }
