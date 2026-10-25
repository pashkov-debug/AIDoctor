"""Проверка трёх вкладок врача и сохранения прежних контрактов UI."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "backend/app/web/index.html").read_text(encoding="utf-8")
JS = (ROOT / "backend/app/web/assets/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "backend/app/web/assets/style.css").read_text(encoding="utf-8")


def test_patient_workspace_has_three_accessible_tabs() -> None:
    for name in ("patient", "records", "ai"):
        assert f'id="doctor-tab-{name}"' in HTML
        assert f'data-doctor-tab="{name}"' in HTML
    assert 'role="tablist"' in HTML
    assert "function selectDoctorTab(tab, focus = false)" in JS
    assert '"ArrowLeft", "ArrowRight", "Home", "End"' in JS
    assert "#patient-workspace-grid { display: block;" in CSS


def test_controls_preserve_ids_and_doctor_permissions() -> None:
    for key in (
        "ai-request-form",
        "ai-review-workspace",
        "clinical-encounter-form",
        "clinical-history-form",
        "clinical-observation-form",
        "order-form",
        "clinical-tests-list",
        "doctor-ai-column",
    ):
        assert f'id="{key}"' in HTML
    assert 'state.user?.role !== "doctor"' in JS
    assert "initDoctorWorkspace();" in JS
    assert '$("doctor-order-editor-details").open = true;' in JS


def test_reading_tab_has_no_confirmation_buttons() -> None:
    assert "approvals.append(review);" in JS
    assert "review.append(button);" in JS
    assert "state.clinicalPublications = publications || [];" in JS
