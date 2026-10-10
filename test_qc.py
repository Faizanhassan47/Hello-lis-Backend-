from test_api import client, create_empty_case, add_wsi


def test_slide_qc_and_case_status(client):
    """Create a case with a slide, set QC to Needs rescan, verify status block, then pass and transition."""
    case = create_empty_case(client, "QC-STATUS-001")
    slide1 = add_wsi(client, case["id"], "Slide 1").json()

    # Post QC: Needs rescan
    resp = client.post(f"/api/slides/{slide1['id']}/qc", json={
        "qc_status": "Needs rescan",
        "qc_blur": True,
        "qc_note": "Blurry"
    })
    assert resp.status_code == 200
    assert resp.json()["qc_status"] == "Needs rescan"

    # Transition to In Review should be blocked
    resp = client.patch(f"/api/cases/{case['id']}/status", json={"status": "In Review"})
    assert resp.status_code == 409

    # Fix QC to Pass
    resp = client.post(f"/api/slides/{slide1['id']}/qc", json={"qc_status": "Pass"})
    assert resp.status_code == 200

    # Now transition should succeed
    resp = client.patch(f"/api/cases/{case['id']}/status", json={"status": "In Review"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "In Review"


def test_qc_feature(client):
    case = create_empty_case(client, "QC-TEST-001")
    slide1 = add_wsi(client, case["id"], "Slide 1").json()
    slide2 = add_wsi(client, case["id"], "Slide 2").json()

    # Admin can set QC (client fixture is logged in as admin)
    resp = client.post(f"/api/slides/{slide1['id']}/qc", json={
        "qc_status": "Needs rescan",
        "qc_blur": True,
        "qc_note": "Too blurry"
    })
    assert resp.status_code == 200
    updated_slide = resp.json()
    assert updated_slide["qc_status"] == "Needs rescan"
    assert updated_slide["qc_blur"] is True
    assert updated_slide["qc_actor"] == "Administrator"


def test_qc_with_admin(client):
    case = create_empty_case(client, "QC-TEST-002")
    slide1 = add_wsi(client, case["id"], "Slide 1").json()

    # `client` already has `admin` logged in from the fixture.
    resp = client.post(f"/api/slides/{slide1['id']}/qc", json={
        "qc_status": "Needs rescan",
        "qc_blur": True,
        "qc_note": "Too blurry"
    })
    assert resp.status_code == 200
    updated_slide = resp.json()
    assert updated_slide["qc_status"] == "Needs rescan"
    assert updated_slide["qc_blur"] is True
    assert updated_slide["qc_actor"] == "Administrator"

    # Try to change status to "In Review" -> should fail because of "Needs rescan"
    resp = client.patch(f"/api/cases/{case['id']}/status", json={"status": "In Review"})
    assert resp.status_code == 409
    assert "needs a rescan" in resp.json()["detail"]

    # Update QC to Pass
    resp = client.post(f"/api/slides/{slide1['id']}/qc", json={"qc_status": "Pass"})
    assert resp.status_code == 200

    # Now changing status to In Review should succeed
    resp = client.patch(f"/api/cases/{case['id']}/status", json={"status": "In Review"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "In Review"

    # Test case with no QC result (allowed to transition)
    case2 = create_empty_case(client, "QC-TEST-003")
    slide2 = add_wsi(client, case2["id"], "Slide 2").json()

    # No QC posted — should still be allowed
    resp = client.patch(f"/api/cases/{case2['id']}/status", json={"status": "In Review"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "In Review"
