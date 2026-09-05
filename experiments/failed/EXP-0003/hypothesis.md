# EXP-0003 — Hypothesis

**Family**: class_confusion
**Validation requirement**: OFFLINE_SIMULATABLE
**Parent experiment**: (none)

## Hypothesis

A meaningful fraction of Person recall loss at the baseline conf=0.4 operating point is attributable to the detector correctly localizing a human-shaped region but labeling it with a semantically related non-Person class (Man/Woman/Boy/Girl/Human body/person-subparts), NOT to the detector failing to notice a person at all. Every Person ground-truth false negative is classified into exactly one of 5 mutually-exclusive primary categories (so percentages sum to 100%): (A) TRUE_DETECTOR_MISS -- no spatially relevant human-like prediction of any class exists near the GT box at any non-noise confidence; (B) LOW_CONFIDENCE_PERSON -- a Person prediction exists at sufficient IoU (>=0.5) but below the 0.4 production confidence threshold; (C) SEMANTIC_CLASS_CONFUSION -- a different human-related class (Man/Woman/Boy/Girl/Human body/a person subpart) is predicted at sufficient IoU (>=0.5) and at/above a diagnostic confidence floor (0.4, matching the production threshold); (D) LOCALIZATION_FAILURE -- a human-related prediction exists nearby but its IoU with the GT box is below the 0.5 match threshold (though still >=0.3, the 'spatially associated' floor); (E) DUPLICATE_MULTI_LABEL is reported as a secondary/overlapping flag (not a primary bucket) when >=2 distinct human-related classes are predicted over the same GT box.

## Motivation

reports/baseline/person_failure_analysis.md (Phase B.5) found that 35.1% (84/239) of missed Person boxes had a DIFFERENT class predicted at the same location (IoU>=0.3), computed WITHOUT any confidence floor on the alternate class and WITHOUT scoping each false-negative's candidate search to that specific GT box when a sample has multiple Person instances. This experiment re-derives that figure rigorously: (1) requiring the alternate class to clear a documented diagnostic confidence floor (0.4, same as production) before counting as genuine semantic confusion, not just localization noise; (2) reusing benchmark/evaluate.py's own bug-fixed (class_name, bbox) matching pattern so a multi-Person image's false negatives cannot cross-contaminate each other's candidate evidence, mirroring the exact historical bug documented in benchmark/evaluate.py::_classify_failure's docstring.

## Rationale

Verified against the actual yolov8m-oiv7.pt class list (601 classes, loaded live via ultralytics, not assumed from memory -- see benchmark/diagnostics/human_class_map.py's verify_against_model()) rather than guessed: whole-person aliases (Man/Woman/Boy/Girl/Human body), person subparts (Human face/head/arm/leg/hand/foot/ear/eye/nose/mouth/hair -- 'Human beard' was checked and is NOT present in this model), and clothing/accessories (Clothing, Footwear, Sunglasses, Handbag, Fashion accessory, Luggage and bags, etc.) are tracked as three separate categories, plus an explicit 'not related' discipline (Cat/Book/Tree/Car/Bus/Window/Tent/Office building, which appeared in the Phase B.5 tally purely by proximity, are never counted as human-related evidence here).

## Expected outcome

Quantifies the 'understated capability' gap; does not itself justify a production change.

## Risks

None — measurement-only, does not change any production label or threshold.
