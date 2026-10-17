"""RB1. Derive the anatomical reference sizes from ANSUR II (female, public release).

    python tools/anatomy/derive_reference.py <ANSUR_II_FEMALE_Public.csv> \
        [--out assets/anatomy/reference-sizes.json]

Source: the 2012 U.S. Army Anthropometric Survey (ANSUR II), female public file, 1,986
subjects and 93 body dimensions, published by the Penn State OPEN Lab at
https://www.openlab.psu.edu/ansur2/ . Its technical report (Gordon et al., NATICK/TR-15/007)
carries "Approved for public release; distribution is unlimited". The CSV is not committed:
this tool records its SHA-256 so a rebuild can prove it read the same file.

Why regression-conditioned "virtual subjects" and not percentiles: a body built from every
dimension's own 50th percentile is nobody — the 50th-percentile waist does not belong with the
50th-percentile hips — and its girths, depths and heights disagree with each other. Each size
here is instead four driver values (stature, chest, waist and buttock circumference, each at a
stated percentile) and every other dimension is that dimension's least-squares prediction from
the four, fitted over the whole sample. The prediction is what a woman with those four
measurements has on average, so the set is internally consistent. How typical the driver
combination itself is gets recorded as its Mahalanobis distance; a size far outside the sample
(> 3) is refused rather than shipped.

Only subjects aged 21 or over are used. The survey's youngest are 17; the reference bodies
are adult by construction, not by declaration.

Breast dimensions are not in ANSUR II (its chest measurements are taken over the bust point,
and it has no underbust). The three used — sternal notch to nipple, internipple distance and
nipple to inframammary fold — are from Al-Qattan et al. 2019 (CC BY 4.0, cited in the output),
measured on 20–25-year-old women of BMI 20–25: they anchor the median size directly and are
scaled for the others, and the output says so for each.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "assets" / "anatomy" / "reference-sizes.json"
SOURCE_URL = "https://tools.openlab.psu.edu/publicData/ANSUR_II_FEMALE_Public.csv"
MIN_AGE = 21
MAX_MAHALANOBIS = 3.0

DRIVERS = ("stature", "chestcircumference", "waistcircumference", "buttockcircumference")
#: The dimensions the reference bodies are built and checked against (ANSUR II names, millimetres).
DIMENSIONS = (
    "stature",
    "crotchheight",
    "waistheightomphalion",
    "buttockheight",
    "trochanterionheight",
    "iliocristaleheight",
    "tenthribheight",
    "chestheight",
    "axillaheight",
    "suprasternaleheight",
    "acromialheight",
    "cervicaleheight",
    "kneeheightmidpatella",
    "lateralmalleolusheight",
    "chestcircumference",
    "chestbreadth",
    "chestdepth",
    "waistcircumference",
    "waistbreadth",
    "waistdepth",
    "buttockcircumference",
    "buttockdepth",
    "hipbreadth",
    "bicristalbreadth",
    "thighcircumference",
    "lowerthighcircumference",
    "calfcircumference",
    "anklecircumference",
    "neckcircumferencebase",
    "crotchlengthomphalion",
    "crotchlengthposterioromphalion",
    "biacromialbreadth",
    "bideltoidbreadth",
    "footlength",
    "headcircumference",
    "wristcircumference",
    "bicepscircumferenceflexed",
    "weightkg",
)
#: The reference sizes: the percentile of each driver.
SIZES = {
    "ref-f-median": {
        "label": "Median",
        "stature": 50,
        "chestcircumference": 50,
        "waistcircumference": 50,
        "buttockcircumference": 50,
    },
    "ref-f-petite": {
        "label": "Petite",
        "stature": 10,
        "chestcircumference": 30,
        "waistcircumference": 30,
        "buttockcircumference": 30,
    },
    "ref-f-full": {
        "label": "Full",
        "stature": 50,
        "chestcircumference": 85,
        "waistcircumference": 75,
        "buttockcircumference": 90,
    },
    "ref-f-tall": {
        "label": "Tall",
        "stature": 90,
        "chestcircumference": 40,
        "waistcircumference": 35,
        "buttockcircumference": 45,
    },
}

#: Al-Qattan MM, Aldakhil SS, Al-Hassan TS, Al-Qahtani A. Anthropometric Breast Measurement: Analysis
#: of the Average Breast in Young Nulliparous Saudi Female Population. Plast Reconstr Surg Glob Open.
#: 2019;7(8):e2326. doi:10.1097/GOX.0000000000002326. CC BY 4.0. Table 1, n = 53, means in mm.
BREAST_SOURCE = {
    "citation": "Al-Qattan MM, Aldakhil SS, Al-Hassan TS, Al-Qahtani A. Anthropometric Breast Measurement: "
    "Analysis of the Average Breast in Young Nulliparous Saudi Female Population. Plast Reconstr "
    "Surg Glob Open. 2019;7(8):e2326.",
    "doi": "10.1097/GOX.0000000000002326",
    "licence": "CC BY 4.0",
    "sample": "53 nulliparous women aged 20-25, BMI 20-25, tape measure, standing, arms at sides",
    "sternalNotchToNippleMm": 198.0,
    "internippleDistanceMm": 203.0,
    "nippleToInframammaryFoldMm": 77.0,
}


def read(path: Path) -> tuple[dict[str, np.ndarray], int, int]:
    with path.open(encoding="latin-1", newline="") as handle:
        rows = list(csv.DictReader(handle))
    adults = [r for r in rows if int(r["Age"]) >= MIN_AGE]
    return {name: np.array([float(r[name]) for r in adults]) for name in DIMENSIONS}, len(rows), len(adults)


def derive(columns: dict[str, np.ndarray]) -> dict:
    X = np.column_stack([np.ones(columns["stature"].size)] + [columns[d] for d in DRIVERS])
    drivers = X[:, 1:]
    mean, cov = drivers.mean(axis=0), np.cov(drivers, rowvar=False)
    inverse = np.linalg.inv(cov)
    sizes = {}
    for size_id, spec in SIZES.items():
        x = np.array([np.percentile(columns[d], spec[d]) for d in DRIVERS])
        offset = x - mean
        mahalanobis = float(np.sqrt(offset @ inverse @ offset))
        if mahalanobis > MAX_MAHALANOBIS:
            raise SystemExit(f"{size_id}: driver combination is {mahalanobis:.2f} from the sample mean")
        values, fits = {}, {}
        for name in DIMENSIONS:
            y = columns[name]
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            predicted = float(np.r_[1.0, x] @ coef)
            residual = y - X @ coef
            values[name] = round(predicted, 1)
            fits[name] = {
                "r2": round(float(1 - residual.var() / y.var()), 3),
                "residualSdMm": round(float(residual.std()), 1),
                "percentileInSample": round(float((y < predicted).mean() * 100), 1),
            }
        # ANSUR stores tenths of a kilogram; the residual's spread is converted with the value (it was
        # not, once, and weight's spread read 28.5 kg).
        values["weightkg"] = round(values["weightkg"] / 10.0, 1)
        fits["weightkg"]["residualSdMm"] = round(fits["weightkg"]["residualSdMm"] / 10.0, 2)
        sizes[size_id] = {
            "label": spec["label"],
            "drivers": {
                d: {"percentile": spec[d], "mm": round(float(v), 1)} for d, v in zip(DRIVERS, x, strict=True)
            },
            "driverMahalanobis": round(mahalanobis, 3),
            "dimensionsMm": values,
            "fit": fits,
            "breast": breast_for(values, columns),
        }
    return sizes


def breast_for(values: dict, columns: dict[str, np.ndarray]) -> dict:
    """The three literature dimensions, scaled from the sample they were measured on.

    The source's women are young and slim, nearest the median size; each other size scales them
    by the ANSUR dimension that governs it (stature for a vertical distance, chest breadth for a
    lateral one, chest circumference for the breast's own extent). The scaling is ours, not the
    source's, and is labelled so.
    """
    median = {k: float(np.median(columns[k])) for k in ("stature", "chestbreadth", "chestcircumference")}
    return {
        "sternalNotchToNippleMm": round(
            BREAST_SOURCE["sternalNotchToNippleMm"] * values["stature"] / median["stature"], 1
        ),
        "internippleDistanceMm": round(
            BREAST_SOURCE["internippleDistanceMm"] * values["chestbreadth"] / median["chestbreadth"], 1
        ),
        "nippleToInframammaryFoldMm": round(
            BREAST_SOURCE["nippleToInframammaryFoldMm"]
            * values["chestcircumference"]
            / median["chestcircumference"],
            1,
        ),
        "basis": "Al-Qattan et al. 2019 means, scaled from the ANSUR II median by stature, chest breadth and "
        "chest circumference respectively (scaling by this project, not the source)",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    digest = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    columns, total, adults = read(args.csv)
    out = {
        "schema": "wardrobe.anatomy.referenceSizes.v1",
        "units": "millimetres unless the key says otherwise",
        "source": {
            "name": "ANSUR II (2012 U.S. Army Anthropometric Survey), female public file",
            "url": SOURCE_URL,
            "page": "https://www.openlab.psu.edu/ansur2/",
            "report": "Gordon CC et al. 2012 Anthropometric Survey of U.S. Army Personnel: Methods and "
            "Summary Statistics. NATICK/TR-15/007 (2014).",
            "release": "Approved for public release; distribution is unlimited "
            "(report documentation page, block 12)",
            "sha256": digest,
            "subjects": total,
            "subjectsUsed": adults,
            "filter": f"Age >= {MIN_AGE}",
        },
        "method": "Each size fixes stature, chest, waist (omphalion) and buttock circumference at the stated "
        "percentiles of the filtered sample; every other dimension is its ordinary least-squares "
        "prediction from those four over the same sample.",
        "breastSource": BREAST_SOURCE,
        "sizes": derive(columns),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {args.out} ({adults} of {total} subjects, sha256 {digest[:12]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
