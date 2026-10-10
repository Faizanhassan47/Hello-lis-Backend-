from io import BytesIO
from pathlib import Path
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main


class FakeUnsupportedError(Exception):
    pass


class FakeSlide:
    dimensions = (4096, 2048)
    properties = {"vendor": "aperio"}

    def __init__(self, path):
        if Path(path).read_bytes() != b"valid-svs-data":
            raise FakeUnsupportedError("unsupported")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        pass

    def get_thumbnail(self, size):
        return Image.new("RGB", (512, 256), "pink")


class FakeDeepZoom:
    level_count = 13
    level_tiles = tuple((1, 1) for _ in range(13))

    def __init__(self, slide, tile_size, overlap):
        assert tile_size == 254 and overlap == 1

    def get_dzi(self, image_format):
        return ('<Image TileSize="254" Overlap="1" Format="jpeg" '
                'xmlns="http://schemas.microsoft.com/deepzoom/2008">'
                '<Size Width="4096" Height="2048"/></Image>')

    def get_tile(self, level, address):
        return Image.new("RGB", (254, 254), "purple")


class FakeOpenSlideModule:
    OpenSlide = FakeSlide
    OpenSlideUnsupportedFormatError = FakeUnsupportedError
    PROPERTY_NAME_VENDOR = "vendor"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(main, "UPLOADS", uploads)
    monkeypatch.setattr(main, "DB", tmp_path / "cases.db")
    monkeypatch.setattr(main, "openslide", FakeOpenSlideModule)
    monkeypatch.setattr(main, "DeepZoomGenerator", FakeDeepZoom)
    monkeypatch.setattr(main, "OPENSLIDE_IMPORT_ERROR", None)
    main.slide_cache.clear()
    main.init_db()
    
    # Create test admin user
    with main.closing(main.connect()) as db:
        hashed_pw = main.pwd_context.hash("testpass")
        db.execute(
            "INSERT INTO users (username, display_name, role, password_hash, is_active) VALUES (?, ?, ?, ?, ?)",
            ("admin", "Administrator", "Admin", hashed_pw, True)
        )
        db.commit()
    
    c = TestClient(main.app)
    # create access token manually
    token = main.create_access_token(data={"sub": "admin", "role": "Admin"})
    c.cookies.set("access_token", token)
    c.cookies.set("csrf_token", "test-csrf-token")
    c.headers.update({"X-CSRF-Token": "test-csrf-token"})
    
    return c

def png_bytes():
    out = BytesIO()
    Image.new("RGB", (10, 10), "red").save(out, format="png")
    return out.getvalue()

def create_empty_case(client, case_id="CASE-001"):
    response = client.post("/api/cases", data={"case_id": case_id, "description": "One specimen"})
    assert response.status_code == 201, response.text
    return response.json()

def add_wsi(client, case_pk, label="Slide A"):
    return create_slide(client, case_pk, label)

def create_slide(client, case_pk, label="Slide A"):
    return client.post(
        f"/api/cases/{case_pk}/slides",
        data={"label": label, "stain": "H&E", "specimen_description": "Block A"},
        files={"image": (f"{label}.svs", b"valid-svs-data", "application/octet-stream")},
    )


def test_csrf_rejects_missing_header(client):
    csrf_header = client.headers.pop("X-CSRF-Token")
    try:
        response = client.post("/api/cases", data={"case_id": "CSRF-FAIL", "description": "blocked"})
        assert response.status_code == 403
    finally:
        client.headers["X-CSRF-Token"] = csrf_header


def test_created_user_password_is_hash_only(client):
    response = client.post("/api/users", json={
        "username": "secure-user", "display_name": "Secure User",
        "role": "Viewer", "password": "long-password",
    })
    assert response.status_code == 200, response.text
    with main.closing(main.connect()) as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        user = db.execute("SELECT password_hash FROM users WHERE username = ?", ("secure-user",)).fetchone()
    assert "password" not in columns
    assert user["password_hash"] != "long-password"



def test_legacy_case_migration_is_idempotent_and_preserves_file(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "legacy.png").write_bytes(png_bytes())
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL, filename TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            file_type TEXT NOT NULL DEFAULT 'raster', format TEXT,
            width INTEGER, height INTEGER, file_size INTEGER)""")
        db.execute("""INSERT INTO cases
            (case_id, description, filename, file_type, format, width, height, file_size)
            VALUES ('OLD-001', 'Legacy specimen', 'legacy.png', 'raster', 'PNG', 80, 60, ?)""",
            (len(png_bytes()),))
        db.commit()
    monkeypatch.setattr(main, "DB", database)
    monkeypatch.setattr(main, "UPLOADS", uploads)
    main.init_db()
    main.init_db()
    with main.connect() as db:
        case = db.execute("SELECT * FROM cases WHERE case_id='OLD-001'").fetchone()
        slides = db.execute("SELECT * FROM slides WHERE case_id=?", (case["id"],)).fetchall()
    assert len(slides) == 1
    assert slides[0]["filename"] == "legacy.png"
    assert slides[0]["label"] == "Slide 1"
    assert (uploads / "legacy.png").is_file()


def test_empty_case_and_multiple_slides_persist(client):
    case = create_empty_case(client)
    assert case["slides"] == []

    first = add_wsi(client, case["id"], "Slide A H&E")
    second = add_wsi(client, case["id"], "Slide B IHC")
    assert first.status_code == second.status_code == 201

    persisted = client.get(f"/api/cases/{case['id']}").json()
    assert persisted["slide_count"] == 2
    assert [slide["label"] for slide in persisted["slides"]] == ["Slide A H&E", "Slide B IHC"]
    assert all(slide["case_id"] == case["id"] for slide in persisted["slides"])


def test_slide_metadata_edit_and_viewer_endpoints(client):
    case = create_empty_case(client)
    slide = add_wsi(client, case["id"]).json()
    updated = client.patch(
        f"/api/slides/{slide['id']}",
        json={"label": "Slide A revised", "stain": "PAS", "specimen_description": "Level 2"},
    )
    assert updated.status_code == 200
    assert updated.json()["stain"] == "PAS"

    metadata = client.get(f"/api/slides/{slide['id']}/slide")
    descriptor = client.get(f"/api/slides/{slide['id']}/slide.dzi")
    tile = client.get(f"/api/slides/{slide['id']}/slide_files/0/0_0.jpeg")
    thumbnail = client.get(f"/api/slides/{slide['id']}/thumbnail")
    assert metadata.json()["level_count"] == 13
    assert descriptor.status_code == 200 and 'Width="4096"' in descriptor.text
    assert tile.status_code == 200 and tile.headers["content-type"] == "image/jpeg"
    assert thumbnail.status_code == 200 and thumbnail.headers["content-type"] == "image/jpeg"


def test_quick_create_png_and_legacy_viewer_url_are_preserved(client):
    response = client.post(
        "/api/cases",
        data={"case_id": "PNG-001", "description": "Raster", "slide_label": "Gross image"},
        files={"image": ("sample.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 201
    case = response.json()
    assert case["slide_count"] == 1
    assert case["slides"][0]["format"] == "PNG"
    assert client.get(f"/api/slides/{case['slides'][0]['id']}/image").status_code == 200
    assert client.get(f"/api/cases/{case['id']}/image").status_code == 200


def test_invalid_upload_cleans_file_and_does_not_add_slide(client):
    case = create_empty_case(client)
    response = client.post(
        f"/api/cases/{case['id']}/slides",
        data={"label": "Bad slide"},
        files={"image": ("bad.svs", b"invalid", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert client.get(f"/api/cases/{case['id']}").json()["slides"] == []
    assert list(main.UPLOADS.iterdir()) == []


def annotation_payload(**overrides):
    payload = {
        "label": "Tumor region",
        "note": "Review this focus",
        "color": "#e85d75",
        "x": 100.5,
        "y": 200.25,
        "width": 500.0,
        "height": 300.0,
    }
    payload.update(overrides)
    return payload


def test_annotation_create_list_edit_delete(client):
    case = create_empty_case(client)
    slide = add_wsi(client, case["id"]).json()
    created = client.post(
        f"/api/slides/{slide['id']}/annotations",
        json=annotation_payload(),
    )
    assert created.status_code == 201
    annotation = created.json()
    assert annotation["slide_id"] == slide["id"]
    assert annotation["annotation_type"] == "rectangle"
    assert annotation["x"] == 100.5

    listed = client.get(f"/api/slides/{slide['id']}/annotations")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [annotation["id"]]

    updated = client.patch(
        f"/api/slides/{slide['id']}/annotations/{annotation['id']}",
        json={"label": "Edited region", "note": "Updated note", "color": "#00aa88"},
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "Edited region"
    assert updated.json()["color"] == "#00aa88"

    deleted = client.delete(f"/api/slides/{slide['id']}/annotations/{annotation['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/slides/{slide['id']}/annotations").json() == []


@pytest.mark.parametrize("changes", [
    {"x": -1},
    {"width": 0},
    {"x": 4000, "width": 200},
    {"y": 2000, "height": 100},
    {"x": float("nan")},
    {"height": float("inf")},
])
def test_annotation_rejects_invalid_coordinates(client, changes):
    case = create_empty_case(client)
    slide = add_wsi(client, case["id"]).json()
    payload = annotation_payload(**changes)
    response = client.post(
        f"/api/slides/{slide['id']}/annotations",
        content=json.dumps(payload, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in {400, 422}
    assert client.get(f"/api/slides/{slide['id']}/annotations").json() == []


def test_annotations_are_isolated_by_slide(client):
    case = create_empty_case(client)
    first = add_wsi(client, case["id"], "Slide A").json()
    second = add_wsi(client, case["id"], "Slide B").json()
    annotation = client.post(
        f"/api/slides/{first['id']}/annotations", json=annotation_payload()
    ).json()

    assert client.get(f"/api/slides/{second['id']}/annotations").json() == []
    wrong_edit = client.patch(
        f"/api/slides/{second['id']}/annotations/{annotation['id']}",
        json={"label": "Wrong slide", "note": "", "color": "#112233"},
    )
    wrong_delete = client.delete(
        f"/api/slides/{second['id']}/annotations/{annotation['id']}"
    )
    assert wrong_edit.status_code == 404
    assert wrong_delete.status_code == 404
    assert len(client.get(f"/api/slides/{first['id']}/annotations").json()) == 1


def test_annotation_persists_after_database_reopen(client):
    case = create_empty_case(client)
    slide = add_wsi(client, case["id"]).json()
    annotation = client.post(
        f"/api/slides/{slide['id']}/annotations", json=annotation_payload()
    ).json()

    main.init_db()  # Safe rerun simulates application initialization after restart.
    with TestClient(main.app) as reopened:
        with main.closing(main.connect()) as db:
            db.execute(
                "INSERT OR IGNORE INTO users (username, display_name, role, password_hash, is_active) VALUES (?, ?, ?, ?, ?)",
                ("admin", "Administrator", "Admin", main.pwd_context.hash("testpass"), True)
            )
            db.commit()
        token = main.create_access_token(data={"sub": "admin", "role": "Admin"})
        reopened.cookies.set("access_token", token)
        persisted = reopened.get(f"/api/slides/{slide['id']}/annotations")
    assert persisted.status_code == 200
    assert persisted.json()[0]["id"] == annotation["id"]
    assert persisted.json()[0]["label"] == "Tumor region"


def test_review_migration_defaults_existing_cases_to_new(tmp_path, monkeypatch):
    database = tmp_path / "review-migration.db"
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL, filename TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("INSERT INTO cases (case_id, description, filename) VALUES ('OLD-REVIEW', '', '')")
        db.commit()
    monkeypatch.setattr(main, "DB", database)
    main.init_db()
    main.init_db()
    with main.connect() as db:
        case = db.execute("SELECT status, reviewer FROM cases WHERE case_id='OLD-REVIEW'").fetchone()
        note_tables = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='case_review_notes'").fetchone()["COUNT(*)"]
        history_tables = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='case_review_history'").fetchone()["COUNT(*)"]
    assert dict(case) == {"status": "New", "reviewer": ""}
    assert note_tables == history_tables == 1


def test_reviewer_assignment_notes_and_append_only_history(client):
    case = create_empty_case(client, "REVIEW-001")
    assigned = client.patch(
        f"/api/cases/{case['id']}/reviewer",
        json={"reviewer": "Dr. Rivera"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["reviewer"] == "Dr. Rivera"

    note = client.post(
        f"/api/cases/{case['id']}/review-notes",
        json={"note": "Reviewed the available H&E slide."},
    )
    assert note.status_code == 201
    assert note.json()["author"] == "Administrator"

    reassigned = client.patch(
        f"/api/cases/{case['id']}/reviewer",
        json={"reviewer": "Dr. Chen"},
    )
    assert reassigned.status_code == 200
    history = client.get(f"/api/cases/{case['id']}/review-history").json()
    assert len(history) == 2
    assert history[0]["previous_value"] == "Dr. Rivera"
    assert history[0]["new_value"] == "Dr. Chen"
    assert history[1]["previous_value"] == ""
    assert client.get(f"/api/cases/{case['id']}/review-notes").json()[0]["note"].startswith("Reviewed")


def test_valid_status_progression_and_reopen_records_history(client):
    case = create_empty_case(client, "REVIEW-STATUS")
    for expected in ("In Review", "Reviewed", "In Review"):
        response = client.patch(
            f"/api/cases/{case['id']}/status",
            json={"status": expected},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected
    history = client.get(f"/api/cases/{case['id']}/review-history").json()
    assert [(item["previous_value"], item["new_value"]) for item in history] == [
        ("Reviewed", "In Review"),
        ("In Review", "Reviewed"),
        ("New", "In Review"),
    ]


@pytest.mark.parametrize("start,target", [
    ("New", "Reviewed"),
    ("In Review", "New"),
    ("Reviewed", "New"),
    ("New", "New"),
])
def test_invalid_status_transitions_are_rejected(client, start, target):
    case = create_empty_case(client, f"BAD-{start}-{target}")
    if start == "In Review":
        client.patch(f"/api/cases/{case['id']}/status", json={"status": "In Review"})
    elif start == "Reviewed":
        client.patch(f"/api/cases/{case['id']}/status", json={"status": "In Review"})
        client.patch(f"/api/cases/{case['id']}/status", json={"status": "Reviewed"})
    before = len(client.get(f"/api/cases/{case['id']}/review-history").json())
    response = client.patch(
        f"/api/cases/{case['id']}/status", json={"status": target}
    )
    assert response.status_code == 409
    assert "Unsupported status transition" in response.json()["detail"]
    assert len(client.get(f"/api/cases/{case['id']}/review-history").json()) == before


def test_review_persistence_and_archive_filters(client):
    first = create_empty_case(client, "FILTER-ONE")
    second = create_empty_case(client, "FILTER-TWO")
    client.patch(f"/api/cases/{first['id']}/reviewer", json={"reviewer": "Dr. Chen"})
    client.patch(f"/api/cases/{first['id']}/status", json={"status": "In Review"})
    client.post(f"/api/cases/{first['id']}/review-notes", json={"note": "Persistent note"})

    assert [item["case_id"] for item in client.get("/api/cases?status=In%20Review").json()] == ["FILTER-ONE"]
    assert [item["case_id"] for item in client.get("/api/cases?reviewer=dr.%20chen").json()] == ["FILTER-ONE"]
    assert [item["case_id"] for item in client.get("/api/cases?status=New").json()] == ["FILTER-TWO"]

    main.init_db()
    with TestClient(main.app) as reopened:
        with main.closing(main.connect()) as db:
            db.execute(
                "INSERT OR IGNORE INTO users (username, display_name, role, password_hash, is_active) VALUES (?, ?, ?, ?, ?)",
                ("admin", "Administrator", "Admin", main.pwd_context.hash("testpass"), True)
            )
            db.commit()
        token = main.create_access_token(data={"sub": "admin", "role": "Admin"})
        reopened.cookies.set("access_token", token)
        persisted = reopened.get(f"/api/cases/{first['id']}").json()
    assert persisted["reviewer"] == "Dr. Chen"
    assert persisted["status"] == "In Review"
    assert persisted["review_notes"][0]["note"] == "Persistent note"
    assert len(persisted["review_history"]) == 2


@pytest.mark.skipif(
    not Path(__file__).with_name("testdata").joinpath("CMU-1-Small-Region.svs").is_file(),
    reason="real SVS sample not downloaded",
)
def test_real_svs_quick_create_and_tile(tmp_path, monkeypatch):
    if main.openslide is None or main.openslide is FakeOpenSlideModule:
        pytest.skip("native OpenSlide is unavailable")
    sample = Path(__file__).with_name("testdata") / "CMU-1-Small-Region.svs"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(main, "UPLOADS", uploads)
    monkeypatch.setattr(main, "DB", tmp_path / "cases.db")
    main.slide_cache.clear()
    main.init_db()
    with TestClient(main.app) as real_client, sample.open("rb") as source:
        with main.closing(main.connect()) as db:
            db.execute(
                "INSERT OR IGNORE INTO users (username, display_name, role, password_hash, is_active) VALUES (?, ?, ?, ?, ?)",
                ("admin", "Administrator", "Admin", main.pwd_context.hash("testpass"), True)
            )
            db.commit()
        token = main.create_access_token(data={"sub": "admin", "role": "Admin"})
        real_client.cookies.set("access_token", token)
        response = real_client.post(
            "/api/cases",
            data={"case_id": "REAL-SVS", "slide_label": "Aperio H&E"},
            files={"image": (sample.name, source, "application/octet-stream")},
        )
        assert response.status_code == 201, response.text
        slide = response.json()["slides"][0]
        metadata = real_client.get(f"/api/slides/{slide['id']}/slide").json()
        tile = real_client.get(
            f"/api/slides/{slide['id']}/slide_files/{metadata['level_count'] - 1}/0_0.jpeg"
        )
        assert slide["format"] == "aperio"
        assert tile.status_code == 200 and len(tile.content) > 100
    main.slide_cache.clear()


# --- Reports Tests ---
def test_create_and_edit_draft_report(client):
    case = create_empty_case(client)
    # Create draft
    res = client.post(f"/api/cases/{case['id']}/reports")
    assert res.status_code == 201
    draft = res.json()
    assert draft['status'] == 'Draft'
    assert draft['version'] == 1
    
    # Edit draft
    update_res = client.patch(
        f"/api/reports/{draft['id']}",
        json={
            "specimen_clinical": "Left arm biopsy",
            "gross_description": "Small tissue",
            "microscopic_findings": "Malignant",
            "diagnosis": "Melanoma",
            "comments": "Urgent",
            "reviewer_name": "Dr. Smith",
            "findings": []
        }
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated['diagnosis'] == 'Melanoma'
    assert updated['reviewer_name'] == 'Administrator'

def test_findings_and_invalid_cross_case_references(client):
    case1 = create_empty_case(client, "CASE-01")
    slide1 = add_wsi(client, case1['id']).json()
    
    case2 = create_empty_case(client, "CASE-02")
    slide2 = add_wsi(client, case2['id']).json()
    
    draft = client.post(f"/api/cases/{case1['id']}/reports").json()
    
    # Valid finding
    res = client.patch(f"/api/reports/{draft['id']}", json={
        "findings": [{"slide_id": slide1['id'], "text": "Good", "sort_order": 0}]
    })
    assert res.status_code == 200
    
    # Invalid cross-case reference
    res_invalid = client.patch(f"/api/reports/{draft['id']}", json={
        "findings": [{"slide_id": slide2['id'], "text": "Bad", "sort_order": 0}]
    })
    assert res_invalid.status_code == 400

def test_finalization_immutable_version_and_revision(client):
    case = create_empty_case(client)
    draft = client.post(f"/api/cases/{case['id']}/reports").json()
    client.patch(f"/api/reports/{draft['id']}", json={"diagnosis": "Cancer"})
    
    # Finalize
    res = client.post(f"/api/reports/{draft['id']}/finalize")
    assert res.status_code == 200
    finalized = res.json()
    assert finalized['status'] == 'Finalized'
    
    # Edit after finalized should fail
    edit_fail = client.patch(f"/api/reports/{draft['id']}", json={"diagnosis": "Benign"})
    assert edit_fail.status_code == 400
    
    # Create revision
    rev_res = client.post(f"/api/cases/{case['id']}/reports")
    assert rev_res.status_code == 201
    rev = rev_res.json()
    assert rev['status'] == 'Draft'
    assert rev['version'] == 2
    assert rev['diagnosis'] == 'Cancer'

def test_report_pdf_response(client):
    case = create_empty_case(client)
    draft = client.post(f"/api/cases/{case['id']}/reports").json()
    client.patch(f"/api/reports/{draft['id']}", json={"diagnosis": "Test PDF"})
    
    res = client.get(f"/api/reports/{draft['id']}/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert "attachment" in res.headers["content-disposition"]
import pytest
from starlette.testclient import TestClient

def test_worklist_filters(client, tmp_path, monkeypatch):
    import main
    
    # Create test cases
    c1 = client.post("/api/cases", data={"case_id": "WL-001", "description": "Desc 1"}).json()
    c2 = client.post("/api/cases", data={"case_id": "WL-002", "description": "Desc 2"}).json()
    c3 = client.post("/api/cases", data={"case_id": "WL-003", "description": "Desc 3"}).json()
    c4 = client.post("/api/cases", data={"case_id": "WL-004", "description": "Desc 4"}).json()
    
    # c1: Unassigned, New (default)
    # c2: Assigned to Administrator, In Review
    client.patch(f"/api/cases/{c2['id']}/reviewer", json={"reviewer": "Administrator"})
    client.patch(f"/api/cases/{c2['id']}/status", json={"status": "In Review"})
    # c3: Assigned to Other, In Review
    client.patch(f"/api/cases/{c3['id']}/reviewer", json={"reviewer": "Other"})
    client.patch(f"/api/cases/{c3['id']}/status", json={"status": "In Review"})
    # c4: Assigned to Administrator, Reviewed
    client.patch(f"/api/cases/{c4['id']}/reviewer", json={"reviewer": "Administrator"})
    client.patch(f"/api/cases/{c4['id']}/status", json={"status": "In Review"})
    client.patch(f"/api/cases/{c4['id']}/status", json={"status": "Reviewed"})
    
    # Test Unassigned
    unassigned = client.get("/api/cases?reviewer=").json()
    assert "WL-001" in [c["case_id"] for c in unassigned]
    assert "WL-002" not in [c["case_id"] for c in unassigned]
    
    # Test My Cases
    my_cases = client.get("/api/cases?reviewer=Administrator").json()
    assert "WL-002" in [c["case_id"] for c in my_cases]
    assert "WL-004" in [c["case_id"] for c in my_cases]
    assert "WL-001" not in [c["case_id"] for c in my_cases]
    assert "WL-003" not in [c["case_id"] for c in my_cases]
    
    # Test Awaiting Review
    awaiting = client.get("/api/cases?status=In%20Review").json()
    assert "WL-002" in [c["case_id"] for c in awaiting]
    assert "WL-003" in [c["case_id"] for c in awaiting]
    assert "WL-001" not in [c["case_id"] for c in awaiting]
    assert "WL-004" not in [c["case_id"] for c in awaiting]
    
    # Test Completed
    completed = client.get("/api/cases?status=Reviewed").json()
    assert "WL-004" in [c["case_id"] for c in completed]
    assert "WL-002" not in [c["case_id"] for c in completed]

    # Test Search
    searched = client.get("/api/cases?search=Desc%203").json()
    assert "WL-003" in [c["case_id"] for c in searched]
    assert "WL-001" not in [c["case_id"] for c in searched]
