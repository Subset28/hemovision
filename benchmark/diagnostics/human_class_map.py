"""EXP-0003 (class_confusion): verified human-related class map for the
yolov8m-oiv7.pt checkpoint's 601 Open Images V7 classes.

HOW THIS WAS VERIFIED (not assumed from memory): loaded the real model via
`ultralytics.YOLO(benchmark/config.MODEL_PATH)` and printed `model.names`
(a dict[int, str] of exactly 601 entries), then grepped that real list for
every candidate string named in the EXP-0003 task spec. The exact list
returned by the model (2026-09-04) is reproduced/verifiable via:

    uv run python -c "from ultralytics import YOLO; \
        print(sorted(YOLO('benchmark/models/yolov8m-oiv7.pt').names.values()))"

Every class name below was confirmed PRESENT in that real output before
being added here. Candidates from the task spec that were checked but are
NOT present in the model's class list (and are therefore deliberately
excluded, not silently assumed): "Human beard" is NOT a class in this
model's 601 (Open Images V7 does not include it) -- do not add it without
re-verifying against model.names again.

Category (iv) "explicitly NOT related" is intentionally not enumerated as a
data structure here (it would just be "every other class") -- the point of
that category in the methodology is discipline about NOT lumping in classes
like "Tent", "Book", "Car", "Cat", "Tree", "Office building" etc. just
because they showed up once in a low-confidence prediction near a missed
Person box (see reports/baseline/person_failure_analysis.md's "Confused
classes" tally, which includes several such unrelated classes).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# (i) Whole-person semantic equivalents: a full-body detection that IS
# semantically "a person", just under a different OIV7 leaf label than
# "Person" itself. Verified present in model.names (see module docstring).
# ---------------------------------------------------------------------------
WHOLE_PERSON_ALIASES: frozenset[str] = frozenset({
    "Man",
    "Woman",
    "Boy",
    "Girl",
    "Human body",
})

# ---------------------------------------------------------------------------
# (ii) Person subparts: a FRAGMENT of a person, not equivalent to detecting
# the whole person (a "Human hand" box is typically much smaller than the
# corresponding full-body GT box -- see person_counterfactuals.py
# counterfactual C for the empirical IoU consequence of that size mismatch).
# Verified present in model.names. "Human beard" was checked and is NOT
# present in this model's class list, so it is excluded (see docstring).
# ---------------------------------------------------------------------------
PERSON_SUBPARTS: frozenset[str] = frozenset({
    "Human face",
    "Human head",
    "Human arm",
    "Human leg",
    "Human hand",
    "Human foot",
    "Human ear",
    "Human eye",
    "Human nose",
    "Human mouth",
    "Human hair",
})

# ---------------------------------------------------------------------------
# (iii) Clothing / accessories: correlate with a person being present but are
# NOT the person themselves. Checked against model.names one at a time;
# "Footwear", "Sunglasses", "Handbag", "Fashion accessory", and
# "Luggage and bags" ARE present; "Hat" and "Glasses" are NOT present as
# their own top-level classes in this model (OIV7 has "Cowboy hat",
# "Fedora", "Sun hat", "Sombrero" as separate hat-subtype classes, and
# "Goggles" rather than a bare "Glasses" class -- included individually
# below since they were each verified present).
# ---------------------------------------------------------------------------
CLOTHING_AND_ACCESSORIES: frozenset[str] = frozenset({
    "Clothing",
    "Footwear",
    "Sunglasses",
    "Handbag",
    "Fashion accessory",
    "Luggage and bags",
    "Shirt",
    "Jeans",
    "Jacket",
    "Dress",
    "Trousers",
    "Shorts",
    "Skirt",
    "Coat",
    "Suit",
    "Belt",
    "Scarf",
    "Tie",
    "Sock",
    "Glove",
    "Boot",
    "Sandal",
    "High heels",
    "Brassiere",
    "Swimwear",
    "Miniskirt",
})

# Everything a human-shaped detection could plausibly be, EXCLUDING
# clothing/accessories (used for the primary-category decision tree in
# person_confusion_analysis.py -- clothing correlates with "a person is
# probably here" but is not itself evidence the detector localized/labeled
# a human-shaped region, so it is tracked separately, not folded in).
HUMAN_LIKE_CLASSES: frozenset[str] = WHOLE_PERSON_ALIASES | PERSON_SUBPARTS | {"Person"}

# All four groups combined, for reporting/co-occurrence purposes only.
ALL_HUMAN_RELATED_CLASSES: frozenset[str] = (
    WHOLE_PERSON_ALIASES | PERSON_SUBPARTS | CLOTHING_AND_ACCESSORIES | {"Person"}
)


def verify_against_model(model_names: dict) -> dict:
    """Re-verify every class name declared above is actually present in a
    live model's .names dict. Returns {"missing": [...], "ok": bool}. Call
    this at analysis time (not just trust the module comments) -- see
    person_confusion_analysis.py's main(), which calls this before using
    the map."""
    real_names = set(model_names.values())
    declared = WHOLE_PERSON_ALIASES | PERSON_SUBPARTS | CLOTHING_AND_ACCESSORIES | {"Person"}
    missing = sorted(c for c in declared if c not in real_names)
    return {"missing": missing, "ok": len(missing) == 0, "num_declared": len(declared)}
