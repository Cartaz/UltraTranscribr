"""Measure unmasked RGB differences and package the real UI captures."""

import argparse
import html
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument(
    "--root", type=Path, default=Path(__file__).resolve().parents[1] / "tests/visual"
)
args = parser.parse_args()
root = args.root
results = []
rows = []
for before, after, case in [
    ("before", "after", "empty"),
    ("populated-before", "populated-after", "populated"),
]:
    for path in sorted((root / before).glob("*.png")):
        target = root / after / path.name
        if not target.is_file():
            raise FileNotFoundError(target)
        a = Image.open(path).convert("RGB")
        b = Image.open(target).convert("RGB")
        if a.size != b.size:
            raise ValueError(f"Size mismatch: {path.name}: {a.size} != {b.size}")
        aa = np.asarray(a, dtype=np.float64)
        bb = np.asarray(b, dtype=np.float64)
        delta = np.abs(aa - bb)
        result = {
            "case": case,
            "name": path.stem,
            "size": a.size,
            "mae_rgb_0_255": round(float(delta.mean()), 4),
            "rmse_rgb_0_255": round(float(np.sqrt((delta**2).mean())), 4),
            "identical_pixels_percent": round(
                float(np.all(aa == bb, axis=2).mean() * 100), 4
            ),
        }
        results.append(result)
        rows.append(
            f'<section><h2>{html.escape(case + ": " + path.stem)}</h2><p>MAE {result["mae_rgb_0_255"]}; pixel identici {result["identical_pixels_percent"]}%</p><div><figure><img src="{before}/{path.name}"><figcaption>Originale</figcaption></figure><figure><img src="{after}/{path.name}"><figcaption>QML</figcaption></figure></div></section>'
        )
(root / "metrics.json").write_text(
    json.dumps(
        {
            "method": "All pixels, RGB channels, no masks, no registration, no threshold; timestamps/IDs can vary in populated captures. MAE/RMSE are descriptive and are not acceptance thresholds.",
            "comparisons": results,
        },
        indent=2,
    )
)
(root / "comparison.html").write_text(
    '<!doctype html><meta charset="utf-8"><title>UltraTranscribr: Originale / QML</title><style>body{background:#141414;color:#e1e1e1;font:16px sans-serif;margin:24px}section{margin-bottom:40px}section div{display:flex;gap:16px}figure{margin:0;width:50%}img{width:100%;height:auto}figcaption{padding:8px}</style><h1>Originale / QML — catture reali</h1><p>Stesso viewport 1200×800, DPR 1 e 2. Dati isolati, rilevamento GPU sostituito solo nel fixture. Questi confronti mostrano differenze residue: non certificano una parità pixel perfect.</p>'
    + "".join(rows)
)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
pages = ["live", "file", "meeting", "history", "settings", "settings-advanced", "logs"]
contact = Image.new("RGB", (1200, len(pages) * 430), "#141414")
draw = ImageDraw.Draw(contact)
for y, page in enumerate(pages):
    draw.text(
        (12, y * 430 + 4),
        f"{page} — originale (sinistra) / QML (destra)",
        font=font,
        fill="#ff6600",
    )
    for x, folder in enumerate(("before", "after")):
        contact.paste(
            Image.open(root / folder / f"{page}-1200x800.png")
            .convert("RGB")
            .resize((600, 400), Image.Resampling.LANCZOS),
            (x * 600, y * 430 + 30),
        )
contact.save(root / "qml-comparison.png")
archive = root / "qml-verification.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for folder in ("before", "after", "populated-before", "populated-after"):
        for path in sorted((root / folder).iterdir()):
            z.write(path, path.relative_to(root))
    for name in (
        "comparison.html",
        "metrics.json",
        "runtime-smoke.json",
        "runtime-smoke.png",
        "dependency-audit.json",
    ):
        z.write(root / name, name)
print(
    json.dumps(
        {
            "comparisons": len(results),
            "archive_bytes": archive.stat().st_size,
            "metrics": [
                (r["name"], r["mae_rgb_0_255"], r["identical_pixels_percent"])
                for r in results
                if r["case"] == "empty" and "dpr2" not in r["name"]
            ],
        }
    )
)
