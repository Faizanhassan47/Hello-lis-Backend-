from test_api import client
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
