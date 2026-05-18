from __future__ import annotations

from scripts.export_local_data import _apply_export_profile


def test_export_profiles_filter_training_ready_views():
    records = [
        {
            "source_type": "qa",
            "weak_retrieval": True,
            "review_flags": {"labeled_good": True, "labeled_bad": False, "teacher_reviewed": True},
            "accessibility_flags": {"screen_reader_requested": False, "screen_reader_friendly_label": False},
        },
        {
            "source_type": "code",
            "weak_retrieval": False,
            "review_flags": {"labeled_good": False, "labeled_bad": True, "teacher_reviewed": False},
            "accessibility_flags": {"screen_reader_requested": False, "screen_reader_friendly_label": True},
        },
    ]

    assert len(_apply_export_profile(records, "labeled-good")) == 1
    assert len(_apply_export_profile(records, "labeled-bad")) == 1
    assert len(_apply_export_profile(records, "weak-retrieval")) == 1
    assert len(_apply_export_profile(records, "screen-reader-friendly")) == 1
    assert len(_apply_export_profile(records, "teacher-reviewed")) == 1
    assert len(_apply_export_profile(records, "qa")) == 1
    assert len(_apply_export_profile(records, "code")) == 1
