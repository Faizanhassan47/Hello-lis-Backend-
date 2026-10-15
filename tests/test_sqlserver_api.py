import main


def create_case(client, case_id='SQL-CASE-001', with_image=False, png_file=None):
    files = {'image': ('slide.png', png_file, 'image/png')} if with_image else None
    response = client.post('/api/cases', data={'case_id':case_id,'description':'SQL Server integration test'}, files=files)
    assert response.status_code == 201, response.text
    return response.json()


def test_public_status_and_auth_boundary(client):
    anonymous = type(client)(main.app)
    assert anonymous.get('/api/status').status_code == 200
    assert anonymous.get('/api/cases').status_code == 401
    status = client.get('/api/status')
    assert status.status_code == 200
    assert 'openslide_available' in status.json()


def test_csrf_is_enforced(client):
    header = client.headers.pop('X-CSRF-Token')
    try:
        assert client.post('/api/cases', data={'case_id':'BLOCKED','description':''}).status_code == 403
    finally:
        client.headers['X-CSRF-Token'] = header


def test_user_password_is_hashed(client):
    response = client.post('/api/users', json={'username':'viewer','display_name':'Viewer','role':'Viewer','password':'safe-password-123'})
    assert response.status_code in (200, 201), response.text
    with main.connect() as db:
        columns = {row['name'].lower() for row in db.execute("SELECT COLUMN_NAME AS name FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='users'")}
        user = db.execute('SELECT password_hash FROM users WHERE username=?', ('viewer',)).fetchone()
    assert 'password' not in columns
    assert user['password_hash'] != 'safe-password-123'


def test_case_slide_worklist_and_legacy_image_routes(client, png_file):
    case = create_case(client, with_image=True, png_file=png_file)
    assert case['slide_count'] == 1
    listed = client.get('/api/cases', params={'search':'SQL-CASE'}); assert listed.status_code == 200
    assert any(item['id'] == case['id'] for item in listed.json())
    detail = client.get(f"/api/cases/{case['id']}"); assert detail.status_code == 200
    slide = detail.json()['slides'][0]
    assert client.get(f"/api/slides/{slide['id']}/image").status_code == 200
    assert client.get(f"/api/cases/{case['id']}/image").status_code == 200
    update = client.patch(f"/api/slides/{slide['id']}", json={'label':'Updated','stain':'H&E','specimen_description':'Block A'})
    assert update.status_code == 200 and update.json()['label'] == 'Updated'


def test_review_qc_and_report_lifecycle(client, png_file):
    case = create_case(client, 'SQL-WORKFLOW-001', True, png_file)
    slide = case['slides'][0]
    qc = client.post(f"/api/slides/{slide['id']}/qc", json={'qc_status':'Pass','qc_blur':False,'qc_missing_tissue':False,'qc_scan_artifact':False,'qc_incorrect_label':False,'qc_note':''})
    assert qc.status_code in (200, 201), qc.text
    assigned = client.patch(f"/api/cases/{case['id']}/reviewer", json={'reviewer':'Dr Test'})
    assert assigned.status_code == 200, assigned.text
    progress = client.patch(f"/api/cases/{case['id']}/status", json={'status':'In Review'})
    assert progress.status_code == 200, progress.text
    note = client.post(f"/api/cases/{case['id']}/review-notes", json={'note':'Reviewed in SQL integration test'})
    assert note.status_code in (200, 201), note.text
    report = client.post(f"/api/cases/{case['id']}/reports", json={'reviewer_name':'Dr Test'})
    assert report.status_code in (200, 201), report.text
    report_id = report.json()['id']
    patch = client.patch(f'/api/reports/{report_id}', json={'specimen_clinical':'Specimen','gross_description':'Gross','microscopic_findings':'Microscopy','diagnosis':'Test diagnosis','comments':'Test only','reviewer_name':'Dr Test','findings':[]})
    assert patch.status_code == 200, patch.text
    finalized = client.post(f'/api/reports/{report_id}/finalize')
    assert finalized.status_code == 200, finalized.text
    assert client.get(f'/api/reports/{report_id}/pdf').status_code == 200
    assert client.get(f'/api/reports/{report_id}/csv').status_code == 200
    assert client.get(f'/api/reports/{report_id}/html').status_code == 200


def test_platform_health_schema_and_authorization(client):
    health = client.get('/api/platform/health')
    assert health.status_code == 200, health.text
    assert health.json()['database']['ok'] is True
    assert client.get('/api/platform/ingestion/jobs').status_code == 200
    assert client.get('/api/platform/ai/models').status_code == 200
    assert client.get('/api/platform/hl7/events').status_code == 200
    assert client.get('/api/platform/backups').status_code == 200
