"""Enterprise platform extensions for the SQL Server pathology backend.

The module provides vendor-neutral infrastructure. Scanner, LIS, and AI adapters
must be validated with real partner artifacts before clinical deployment.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field


DDL = [
"""IF OBJECT_ID('patients','U') IS NULL CREATE TABLE patients (
 id INT IDENTITY PRIMARY KEY, external_id VARCHAR(255) UNIQUE, display_label VARCHAR(255) NOT NULL,
 created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
"""IF OBJECT_ID('accessions','U') IS NULL CREATE TABLE accessions (
 id INT IDENTITY PRIMARY KEY, patient_id INT NULL REFERENCES patients(id), accession_number VARCHAR(255) UNIQUE NOT NULL,
 order_id VARCHAR(255), priority VARCHAR(30) NOT NULL DEFAULT 'Routine', due_at DATETIME2 NULL,
 created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
"""IF OBJECT_ID('specimens','U') IS NULL CREATE TABLE specimens (
 id INT IDENTITY PRIMARY KEY, accession_id INT NOT NULL REFERENCES accessions(id), specimen_code VARCHAR(255) NOT NULL,
 specimen_type VARCHAR(255), description VARCHAR(MAX), created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
"""IF OBJECT_ID('blocks','U') IS NULL CREATE TABLE blocks (
 id INT IDENTITY PRIMARY KEY, specimen_id INT NOT NULL REFERENCES specimens(id), block_code VARCHAR(255) NOT NULL,
 description VARCHAR(MAX), created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
"""IF OBJECT_ID('ingestion_jobs','U') IS NULL CREATE TABLE ingestion_jobs (
 id INT IDENTITY PRIMARY KEY, correlation_id VARCHAR(64) UNIQUE NOT NULL, source_path VARCHAR(2048), source_device VARCHAR(255),
 adapter_name VARCHAR(120) NOT NULL DEFAULT 'manual', original_filename VARCHAR(512) NOT NULL, checksum_sha256 VARCHAR(64),
 file_size BIGINT, status VARCHAR(30) NOT NULL, attempts INT NOT NULL DEFAULT 0, progress INT NOT NULL DEFAULT 0,
 error_detail VARCHAR(MAX), quarantine_path VARCHAR(2048), created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
 started_at DATETIME2 NULL, completed_at DATETIME2 NULL)""",
"""IF OBJECT_ID('image_versions','U') IS NULL CREATE TABLE image_versions (
 id INT IDENTITY PRIMARY KEY, slide_id INT NOT NULL REFERENCES slides(id), version INT NOT NULL, checksum_sha256 VARCHAR(64) NOT NULL,
 source_path VARCHAR(2048), source_device VARCHAR(255), scanner_make VARCHAR(120), scanner_model VARCHAR(120),
 magnification FLOAT NULL, pixel_size_microns FLOAT NULL, acquisition_time DATETIME2 NULL, metadata_json VARCHAR(MAX),
 stored_filename VARCHAR(512) NOT NULL, created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), UNIQUE(slide_id,version))""",
"""IF OBJECT_ID('reconciliation_items','U') IS NULL CREATE TABLE reconciliation_items (
 id INT IDENTITY PRIMARY KEY, ingestion_job_id INT REFERENCES ingestion_jobs(id), proposed_case_id VARCHAR(255), reason VARCHAR(MAX) NOT NULL,
 status VARCHAR(30) NOT NULL DEFAULT 'Open', resolved_case_id INT NULL REFERENCES cases(id), resolved_by VARCHAR(255),
 created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), resolved_at DATETIME2 NULL)""",
"""IF OBJECT_ID('scanner_compatibility','U') IS NULL CREATE TABLE scanner_compatibility (
 id INT IDENTITY PRIMARY KEY, manufacturer VARCHAR(120) NOT NULL, model VARCHAR(120) NOT NULL, software_version VARCHAR(120),
 format VARCHAR(80) NOT NULL, import_method VARCHAR(120) NOT NULL, metadata_coverage VARCHAR(MAX), limitations VARCHAR(MAX),
 validation_status VARCHAR(30) NOT NULL DEFAULT 'Unverified', tested_at DATETIME2 NULL)""",
"""IF OBJECT_ID('ai_models','U') IS NULL CREATE TABLE ai_models (
 id INT IDENTITY PRIMARY KEY, name VARCHAR(255) NOT NULL, version VARCHAR(120) NOT NULL, checksum VARCHAR(128) NOT NULL,
 task VARCHAR(255) NOT NULL, intended_use VARCHAR(MAX), compatible_inputs VARCHAR(MAX), limitations VARCHAR(MAX),
 approval_status VARCHAR(30) NOT NULL DEFAULT 'Research', adapter_name VARCHAR(120) NOT NULL,
 created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), UNIQUE(name,version))""",
"""IF OBJECT_ID('ai_jobs','U') IS NULL CREATE TABLE ai_jobs (
 id INT IDENTITY PRIMARY KEY, correlation_id VARCHAR(64) UNIQUE NOT NULL, model_id INT NOT NULL REFERENCES ai_models(id),
 slide_id INT NOT NULL REFERENCES slides(id), image_version_id INT NULL REFERENCES image_versions(id), status VARCHAR(30) NOT NULL,
 progress INT NOT NULL DEFAULT 0, parameters_json VARCHAR(MAX), environment_json VARCHAR(MAX), error_detail VARCHAR(MAX),
 requested_by VARCHAR(255) NOT NULL, created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), started_at DATETIME2 NULL, completed_at DATETIME2 NULL)""",
"""IF OBJECT_ID('ai_results','U') IS NULL CREATE TABLE ai_results (
 id INT IDENTITY PRIMARY KEY, ai_job_id INT NOT NULL REFERENCES ai_jobs(id), result_type VARCHAR(80) NOT NULL,
 geometry_json VARCHAR(MAX), measurements_json VARCHAR(MAX), confidence FLOAT NULL, raw_output_json VARCHAR(MAX),
 review_status VARCHAR(30) NOT NULL DEFAULT 'Unreviewed', reviewed_by VARCHAR(255), review_note VARCHAR(MAX),
 created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), reviewed_at DATETIME2 NULL)""",
"""IF OBJECT_ID('hl7_channels','U') IS NULL CREATE TABLE hl7_channels (
 id INT IDENTITY PRIMARY KEY, name VARCHAR(255) UNIQUE NOT NULL, direction VARCHAR(20) NOT NULL, version VARCHAR(20) NOT NULL DEFAULT '2.5.1',
 transport VARCHAR(30) NOT NULL DEFAULT 'MLLP', host VARCHAR(255), port INT, enabled BIT NOT NULL DEFAULT 0,
 mapping_json VARCHAR(MAX), created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
"""IF OBJECT_ID('integration_events','U') IS NULL CREATE TABLE integration_events (
 id INT IDENTITY PRIMARY KEY, channel_id INT NULL REFERENCES hl7_channels(id), correlation_id VARCHAR(64) UNIQUE NOT NULL,
 message_control_id VARCHAR(255), message_type VARCHAR(40), direction VARCHAR(20) NOT NULL, raw_payload VARCHAR(MAX) NOT NULL,
 normalized_json VARCHAR(MAX), status VARCHAR(30) NOT NULL, acknowledgement VARCHAR(MAX), attempts INT NOT NULL DEFAULT 0,
 error_detail VARCHAR(MAX), created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), processed_at DATETIME2 NULL)""",
"""IF OBJECT_ID('system_settings','U') IS NULL CREATE TABLE system_settings (
 setting_key VARCHAR(255) PRIMARY KEY, setting_value VARCHAR(MAX), updated_by VARCHAR(255), updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
"""IF OBJECT_ID('backup_runs','U') IS NULL CREATE TABLE backup_runs (
 id INT IDENTITY PRIMARY KEY, correlation_id VARCHAR(64) UNIQUE NOT NULL, status VARCHAR(30) NOT NULL, destination VARCHAR(2048),
 manifest_json VARCHAR(MAX), error_detail VARCHAR(MAX), started_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), completed_at DATETIME2 NULL)""",
]


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255); version: str = Field(min_length=1, max_length=120)
    checksum: str = Field(min_length=8, max_length=128); task: str = Field(min_length=1, max_length=255)
    intended_use: str = ""; compatible_inputs: str = ""; limitations: str = ""
    approval_status: str = "Research"; adapter_name: str = "external"

class AiJobCreate(BaseModel):
    model_id: int; slide_id: int; image_version_id: int | None = None; parameters: dict = {}

class ChannelCreate(BaseModel):
    name: str; direction: str; version: str = "2.5.1"; transport: str = "MLLP"
    host: str | None = None; port: int | None = None; enabled: bool = False; mapping: dict = {}

class Hl7MessageCreate(BaseModel):
    channel_id: int | None = None; direction: str = "inbound"; raw_payload: str

class PatientCreate(BaseModel):
    external_id: str | None = Field(default=None, max_length=255)
    display_label: str = Field(min_length=1, max_length=255)

class AccessionCreate(BaseModel):
    patient_id: int | None = None
    accession_number: str = Field(min_length=1, max_length=255)
    order_id: str | None = Field(default=None, max_length=255)
    priority: str = "Routine"
    due_at: datetime | None = None

class SpecimenCreate(BaseModel):
    accession_id: int
    specimen_code: str = Field(min_length=1, max_length=255)
    specimen_type: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=4000)

class BlockCreate(BaseModel):
    specimen_id: int
    block_code: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)

class IngestionCreate(BaseModel):
    source_path: str
    source_device: str = "local-folder"
    adapter_name: str = "openslide"

class CompatibilityCreate(BaseModel):
    manufacturer: str; model: str; software_version: str = ""; format: str
    import_method: str = "manual"; metadata_coverage: str = ""; limitations: str = ""
    validation_status: str = "Unverified"

class JobStatusUpdate(BaseModel):
    status: str; progress: int = Field(default=0, ge=0, le=100); error_detail: str = ""

class AiResultCreate(BaseModel):
    result_type: str; geometry: dict | list | None = None; measurements: dict = {}
    confidence: float | None = None; raw_output: dict = {}

class AiReview(BaseModel):
    review_status: str; review_note: str = ""

class SettingUpdate(BaseModel):
    value: str = Field(max_length=4000)

class BackupCreate(BaseModel):
    name: str = Field(default="pathology", pattern=r"^[A-Za-z0-9_-]{1,80}$")

class ReconciliationResolve(BaseModel):
    resolved_case_id: int

TERMINAL_INGESTION = {'Completed', 'Failed', 'Quarantined', 'Duplicate', 'Cancelled'}


def _rows(connect, sql, params=()):
    with connect() as db: return [dict(row) for row in db.execute(sql, params).fetchall()]

def _parse_hl7(payload: str):
    segments = [line.split('|') for line in payload.replace('\n', '\r').split('\r') if line]
    if not segments or segments[0][0] != 'MSH': raise HTTPException(400, 'HL7 message must start with MSH')
    msh = segments[0]
    return {'message_type': msh[8] if len(msh) > 8 else '', 'message_control_id': msh[9] if len(msh) > 9 else '',
            'version': msh[11] if len(msh) > 11 else '', 'segments': {segment[0]: segment[1:] for segment in segments}}

def create_platform_router(connect, require_roles, get_current_user, uploads_dir: Path):
    router = APIRouter(prefix='/api/platform', tags=['platform'])
    quarantine_dir = Path(os.getenv('QUARANTINE_DIR', uploads_dir.parent / 'quarantine'))
    if not quarantine_dir.is_absolute(): quarantine_dir = uploads_dir.parent / quarantine_dir
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    @router.get('/patients')
    def patients(_=Depends(require_roles(['Admin','Technician','Pathologist','Viewer']))):
        return _rows(connect, 'SELECT TOP 500 * FROM patients ORDER BY id DESC')

    @router.post('/patients', status_code=201)
    def create_patient(item: PatientCreate, _=Depends(require_roles(['Admin','Technician']))):
        with connect() as db:
            cur=db.execute('INSERT INTO patients (external_id,display_label) VALUES (?,?)',(item.external_id,item.display_label)); db.commit()
            return {'id':cur.lastrowid,**item.model_dump()}

    @router.get('/accessions')
    def accessions(_=Depends(require_roles(['Admin','Technician','Pathologist','Viewer']))):
        return _rows(connect, 'SELECT TOP 500 * FROM accessions ORDER BY id DESC')

    @router.post('/accessions', status_code=201)
    def create_accession(item: AccessionCreate, _=Depends(require_roles(['Admin','Technician']))):
        if item.priority not in {'Routine','Urgent','Stat'}: raise HTTPException(400,'Invalid priority')
        with connect() as db:
            cur=db.execute('INSERT INTO accessions (patient_id,accession_number,order_id,priority,due_at) VALUES (?,?,?,?,?)',(item.patient_id,item.accession_number,item.order_id,item.priority,item.due_at)); db.commit()
            return {'id':cur.lastrowid,**item.model_dump()}

    @router.get('/specimens')
    def specimens(_=Depends(require_roles(['Admin','Technician','Pathologist','Viewer']))): return _rows(connect,'SELECT TOP 500 * FROM specimens ORDER BY id DESC')

    @router.post('/specimens', status_code=201)
    def create_specimen(item: SpecimenCreate, _=Depends(require_roles(['Admin','Technician']))):
        with connect() as db:
            cur=db.execute('INSERT INTO specimens (accession_id,specimen_code,specimen_type,description) VALUES (?,?,?,?)',(item.accession_id,item.specimen_code,item.specimen_type,item.description)); db.commit()
            return {'id':cur.lastrowid,**item.model_dump()}

    @router.get('/blocks')
    def blocks(_=Depends(require_roles(['Admin','Technician','Pathologist','Viewer']))): return _rows(connect,'SELECT TOP 500 * FROM blocks ORDER BY id DESC')

    @router.post('/blocks', status_code=201)
    def create_block(item: BlockCreate, _=Depends(require_roles(['Admin','Technician']))):
        with connect() as db:
            cur=db.execute('INSERT INTO blocks (specimen_id,block_code,description) VALUES (?,?,?)',(item.specimen_id,item.block_code,item.description)); db.commit()
            return {'id':cur.lastrowid,**item.model_dump()}

    @router.get('/compatibility')
    def compatibility(_=Depends(require_roles(['Admin','Technician','Pathologist','Viewer']))):
        return _rows(connect, 'SELECT * FROM scanner_compatibility ORDER BY manufacturer, model')

    @router.post('/compatibility', status_code=201)
    def add_compatibility(item:CompatibilityCreate,_=Depends(require_roles(['Admin']))):
        if item.validation_status not in {'Unverified','Testing','Verified','Unsupported'}: raise HTTPException(400,'Invalid validation status')
        with connect() as db:
            cur=db.execute('INSERT INTO scanner_compatibility (manufacturer,model,software_version,format,import_method,metadata_coverage,limitations,validation_status,tested_at) VALUES (?,?,?,?,?,?,?,?,CASE WHEN ?=\'Verified\' THEN SYSUTCDATETIME() ELSE NULL END)',
              (item.manufacturer,item.model,item.software_version,item.format,item.import_method,item.metadata_coverage,item.limitations,item.validation_status,item.validation_status)); db.commit()
            return {'id':cur.lastrowid,**item.model_dump()}

    @router.get('/ingestion/jobs')
    def ingestion_jobs(_=Depends(require_roles(['Admin','Technician']))):
        return _rows(connect, 'SELECT TOP 200 * FROM ingestion_jobs ORDER BY id DESC')

    @router.post('/ingestion/jobs', status_code=202)
    def queue_ingestion(item: IngestionCreate, _=Depends(require_roles(['Admin','Technician']))):
        watched = os.getenv('WATCHED_FOLDER','').strip()
        if not watched: raise HTTPException(409,'WATCHED_FOLDER is not configured')
        root=Path(watched).resolve(); source=Path(item.source_path).resolve()
        if source != root and root not in source.parents: raise HTTPException(400,'Source path must be inside WATCHED_FOLDER')
        if not source.is_file(): raise HTTPException(404,'Source file not found')
        digest=hashlib.sha256()
        with source.open('rb') as handle:
            for chunk in iter(lambda:handle.read(8*1024*1024),b''): digest.update(chunk)
        checksum=digest.hexdigest()
        with connect() as db:
            duplicate=db.execute("SELECT TOP 1 id FROM ingestion_jobs WHERE checksum_sha256=? AND status='Completed'",(checksum,)).fetchone()
            job_status='Duplicate' if duplicate else 'Queued'; cid=uuid4().hex
            cur=db.execute('INSERT INTO ingestion_jobs (correlation_id,source_path,source_device,adapter_name,original_filename,checksum_sha256,file_size,status) VALUES (?,?,?,?,?,?,?,?)',
              (cid,str(source),item.source_device,item.adapter_name,source.name,checksum,source.stat().st_size,job_status)); db.commit()
            return {'id':cur.lastrowid,'correlation_id':cid,'checksum_sha256':checksum,'status':job_status,'duplicate_of':duplicate['id'] if duplicate else None}

    @router.patch('/ingestion/jobs/{job_id}')
    def update_ingestion(job_id:int,item:JobStatusUpdate,_=Depends(require_roles(['Admin','Technician']))):
        allowed={'Queued','Processing','Completed','Failed','Quarantined','Duplicate','Cancelled'}
        if item.status not in allowed: raise HTTPException(400,'Invalid status')
        with connect() as db:
            row=db.execute('SELECT id FROM ingestion_jobs WHERE id=?',(job_id,)).fetchone()
            if not row: raise HTTPException(404,'Ingestion job not found')
            db.execute("UPDATE ingestion_jobs SET status=?,progress=?,error_detail=?,attempts=attempts+1,started_at=COALESCE(started_at,SYSUTCDATETIME()),completed_at=CASE WHEN ? IN ('Completed','Failed','Quarantined','Cancelled') THEN SYSUTCDATETIME() ELSE completed_at END WHERE id=?",(item.status,item.progress,item.error_detail,item.status,job_id)); db.commit()
        return {'id':job_id,**item.model_dump()}

    @router.post('/ingestion/jobs/{job_id}/process')
    def process_ingestion(job_id:int, user=Depends(require_roles(['Admin','Technician']))):
        """Process one queued file. Vendor-specific scanners should enqueue files through adapters."""
        allowed_extensions={'.svs','.tif','.tiff','.ndpi','.mrxs','.jpg','.jpeg','.png'}
        with connect() as db:
            job=db.execute('SELECT * FROM ingestion_jobs WHERE id=?',(job_id,)).fetchone()
            if not job: raise HTTPException(404,'Ingestion job not found')
            if job['status'] in TERMINAL_INGESTION: raise HTTPException(409,f"Job is already {job['status']}")
            db.execute("UPDATE ingestion_jobs SET status='Processing',progress=10,attempts=attempts+1,started_at=COALESCE(started_at,SYSUTCDATETIME()) WHERE id=?",(job_id,)); db.commit()
        source=Path(job['source_path'])
        try:
            if not source.is_file(): raise FileNotFoundError('Source file no longer exists')
            if source.suffix.lower() not in allowed_extensions: raise ValueError(f'Unsupported image extension: {source.suffix}')
            destination=uploads_dir / f"{uuid4().hex}{source.suffix.lower()}"
            shutil.copy2(source,destination)
            with connect() as db:
                db.execute("UPDATE ingestion_jobs SET status='Completed',progress=100,completed_at=SYSUTCDATETIME(),error_detail=NULL WHERE id=?",(job_id,)); db.commit()
            return {'id':job_id,'status':'Completed','stored_filename':destination.name,'checksum_sha256':job['checksum_sha256']}
        except Exception as exc:
            quarantine_path=None
            try:
                if source.is_file():
                    target=quarantine_dir / f"{job_id}-{source.name}"
                    shutil.copy2(source,target); quarantine_path=str(target)
            except OSError:
                pass
            with connect() as db:
                db.execute("UPDATE ingestion_jobs SET status='Quarantined',error_detail=?,quarantine_path=?,completed_at=SYSUTCDATETIME() WHERE id=?",(str(exc)[:4000],quarantine_path,job_id)); db.commit()
            raise HTTPException(422,f'Ingestion failed and was quarantined: {exc}')

    @router.post('/ingestion/jobs/{job_id}/retry', status_code=202)
    def retry_ingestion(job_id:int,_=Depends(require_roles(['Admin','Technician']))):
        with connect() as db:
            row=db.execute('SELECT status FROM ingestion_jobs WHERE id=?',(job_id,)).fetchone()
            if not row: raise HTTPException(404,'Ingestion job not found')
            if row['status'] not in {'Failed','Quarantined','Cancelled'}: raise HTTPException(409,'Only failed, quarantined, or cancelled jobs can be retried')
            db.execute("UPDATE ingestion_jobs SET status='Queued',progress=0,error_detail=NULL,completed_at=NULL WHERE id=?",(job_id,)); db.commit()
        return {'id':job_id,'status':'Queued'}

    @router.get('/reconciliation')
    def reconciliation(_=Depends(require_roles(['Admin','Technician','Pathologist']))):
        return _rows(connect, 'SELECT TOP 200 * FROM reconciliation_items ORDER BY id DESC')

    @router.patch('/reconciliation/{item_id}/resolve')
    def resolve_reconciliation(item_id:int,item:ReconciliationResolve,user=Depends(require_roles(['Admin','Technician']))):
        with connect() as db:
            case=db.execute('SELECT id FROM cases WHERE id=?',(item.resolved_case_id,)).fetchone()
            if not case: raise HTTPException(400,'Resolved case does not exist')
            cur=db.execute("UPDATE reconciliation_items SET status='Resolved',resolved_case_id=?,resolved_by=?,resolved_at=SYSUTCDATETIME() WHERE id=? AND status='Open'",(item.resolved_case_id,user['username'],item_id))
            if not cur.rowcount: raise HTTPException(404,'Open reconciliation item not found')
            db.commit()
        return {'id':item_id,'status':'Resolved','resolved_case_id':item.resolved_case_id}

    @router.get('/ai/models')
    def models(_=Depends(require_roles(['Admin','Pathologist','Viewer']))): return _rows(connect, 'SELECT * FROM ai_models ORDER BY name, version DESC')

    @router.post('/ai/models', status_code=201)
    def create_model(item: ModelCreate, user=Depends(require_roles(['Admin']))):
        if item.approval_status not in {'Research','Validated','Retired'}: raise HTTPException(400, 'Invalid approval status')
        with connect() as db:
            cur=db.execute('INSERT INTO ai_models (name,version,checksum,task,intended_use,compatible_inputs,limitations,approval_status,adapter_name) VALUES (?,?,?,?,?,?,?,?,?)',
              (item.name,item.version,item.checksum,item.task,item.intended_use,item.compatible_inputs,item.limitations,item.approval_status,item.adapter_name)); db.commit()
            return {'id':cur.lastrowid, **item.model_dump()}

    @router.get('/ai/jobs')
    def ai_jobs(_=Depends(require_roles(['Admin','Pathologist','Viewer']))): return _rows(connect, 'SELECT TOP 200 * FROM ai_jobs ORDER BY id DESC')

    @router.post('/ai/jobs', status_code=202)
    def create_ai_job(item: AiJobCreate, user=Depends(require_roles(['Admin','Pathologist']))):
        with connect() as db:
            model=db.execute('SELECT id,approval_status FROM ai_models WHERE id=?',(item.model_id,)).fetchone()
            slide=db.execute('SELECT id FROM slides WHERE id=?',(item.slide_id,)).fetchone()
            if not model or not slide: raise HTTPException(400,'Invalid model or slide')
            cid=uuid4().hex; cur=db.execute("INSERT INTO ai_jobs (correlation_id,model_id,slide_id,image_version_id,status,parameters_json,requested_by) VALUES (?,?,?,?,?,?,?)",
              (cid,item.model_id,item.slide_id,item.image_version_id,'Queued',json.dumps(item.parameters),user['username'])); db.commit()
            return {'id':cur.lastrowid,'correlation_id':cid,'status':'Queued'}

    @router.patch('/ai/jobs/{job_id}')
    def update_ai_job(job_id:int,item:JobStatusUpdate,_=Depends(require_roles(['Admin']))):
        allowed={'Queued','Running','Completed','Failed','Cancelled'}
        if item.status not in allowed: raise HTTPException(400,'Invalid AI job status')
        with connect() as db:
            db.execute("UPDATE ai_jobs SET status=?,progress=?,error_detail=?,started_at=COALESCE(started_at,SYSUTCDATETIME()),completed_at=CASE WHEN ? IN ('Completed','Failed','Cancelled') THEN SYSUTCDATETIME() ELSE completed_at END WHERE id=?",(item.status,item.progress,item.error_detail,item.status,job_id)); db.commit()
        return {'id':job_id,**item.model_dump()}

    @router.get('/ai/jobs/{job_id}/results')
    def ai_results(job_id:int,_=Depends(require_roles(['Admin','Pathologist','Viewer']))): return _rows(connect,'SELECT * FROM ai_results WHERE ai_job_id=? ORDER BY id',(job_id,))

    @router.post('/ai/jobs/{job_id}/results',status_code=201)
    def create_ai_result(job_id:int,item:AiResultCreate,_=Depends(require_roles(['Admin']))):
        with connect() as db:
            cur=db.execute('INSERT INTO ai_results (ai_job_id,result_type,geometry_json,measurements_json,confidence,raw_output_json) VALUES (?,?,?,?,?,?)',(job_id,item.result_type,json.dumps(item.geometry),json.dumps(item.measurements),item.confidence,json.dumps(item.raw_output))); db.commit()
            return {'id':cur.lastrowid,'ai_job_id':job_id,**item.model_dump()}

    @router.patch('/ai/results/{result_id}/review')
    def review_ai_result(result_id:int,item:AiReview,user=Depends(require_roles(['Admin','Pathologist']))):
        if item.review_status not in {'Accepted','Rejected','Corrected'}: raise HTTPException(400,'Invalid review status')
        with connect() as db:
            db.execute('UPDATE ai_results SET review_status=?,reviewed_by=?,review_note=?,reviewed_at=SYSUTCDATETIME() WHERE id=?',(item.review_status,user['username'],item.review_note,result_id)); db.commit()
        return {'id':result_id,**item.model_dump(),'reviewed_by':user['username']}

    @router.get('/hl7/channels')
    def channels(_=Depends(require_roles(['Admin']))): return _rows(connect, 'SELECT * FROM hl7_channels ORDER BY name')

    @router.post('/hl7/channels', status_code=201)
    def create_channel(item: ChannelCreate, _=Depends(require_roles(['Admin']))):
        if item.direction not in {'inbound','outbound'}: raise HTTPException(400,'Invalid direction')
        with connect() as db:
            cur=db.execute('INSERT INTO hl7_channels (name,direction,version,transport,host,port,enabled,mapping_json) VALUES (?,?,?,?,?,?,?,?)',
              (item.name,item.direction,item.version,item.transport,item.host,item.port,int(item.enabled),json.dumps(item.mapping))); db.commit()
            return {'id':cur.lastrowid,**item.model_dump()}

    @router.post('/hl7/messages', status_code=202)
    def receive_hl7(item: Hl7MessageCreate, _=Depends(require_roles(['Admin']))):
        parsed=_parse_hl7(item.raw_payload); cid=uuid4().hex
        with connect() as db:
            cur=db.execute("INSERT INTO integration_events (channel_id,correlation_id,message_control_id,message_type,direction,raw_payload,normalized_json,status) VALUES (?,?,?,?,?,?,?,'Received')",
              (item.channel_id,cid,parsed['message_control_id'],parsed['message_type'],item.direction,item.raw_payload,json.dumps(parsed))); db.commit()
            return {'id':cur.lastrowid,'correlation_id':cid,'status':'Received','parsed':parsed}

    @router.get('/hl7/events')
    def events(_=Depends(require_roles(['Admin']))): return _rows(connect, 'SELECT TOP 200 * FROM integration_events ORDER BY id DESC')

    @router.post('/hl7/events/{event_id}/replay',status_code=202)
    def replay_event(event_id:int,_=Depends(require_roles(['Admin']))):
        with connect() as db:
            row=db.execute('SELECT id FROM integration_events WHERE id=?',(event_id,)).fetchone()
            if not row: raise HTTPException(404,'Integration event not found')
            db.execute("UPDATE integration_events SET status='Received',attempts=attempts+1,error_detail=NULL,processed_at=NULL WHERE id=?",(event_id,)); db.commit()
        return {'id':event_id,'status':'Received'}

    @router.post('/hl7/events/{event_id}/ack')
    def acknowledge_event(event_id:int,accepted:bool=True,_=Depends(require_roles(['Admin']))):
        code='AA' if accepted else 'AE'; ack=f'MSH|^~\\&|PATHOLOGY|LOCAL|LIS|LOCAL|{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") }||ACK|{uuid4().hex[:20]}|P|2.5.1\rMSA|{code}|EVENT-{event_id}'
        with connect() as db:
            db.execute("UPDATE integration_events SET acknowledgement=?,status=?,processed_at=SYSUTCDATETIME() WHERE id=?",(ack,'Acknowledged' if accepted else 'Rejected',event_id)); db.commit()
        return {'id':event_id,'acknowledgement':ack,'status':'Acknowledged' if accepted else 'Rejected'}

    @router.get('/health')
    def health(request: Request, _=Depends(require_roles(['Admin']))):
        usage=shutil.disk_usage(uploads_dir); db_ok=True
        try:
            with connect() as db: db.execute('SELECT 1').fetchone()
        except Exception: db_ok=False
        return {'ok':db_ok,'database':{'ok':db_ok},'storage':{'path':str(uploads_dir),'total':usage.total,'used':usage.used,'free':usage.free,'used_percent':round(usage.used/usage.total*100,2)},
                'version':os.getenv('APP_VERSION','development'),'request_id':getattr(request.state,'request_id',None),'time':datetime.now(timezone.utc).isoformat()}

    @router.get('/settings')
    def settings(_=Depends(require_roles(['Admin']))):
        return _rows(connect,'SELECT setting_key,setting_value,updated_by,updated_at FROM system_settings ORDER BY setting_key')

    @router.put('/settings/{key}')
    def update_setting(key:str,item:SettingUpdate,user=Depends(require_roles(['Admin']))):
        allowed={'retention_days','storage_warning_percent','storage_critical_percent','ingestion_max_attempts'}
        if key not in allowed: raise HTTPException(400,'Unsupported setting')
        try: value=int(item.value)
        except ValueError: raise HTTPException(400,'Setting value must be an integer')
        if value < 1: raise HTTPException(400,'Setting value must be positive')
        with connect() as db:
            db.execute("MERGE system_settings AS target USING (SELECT ? AS setting_key) AS source ON target.setting_key=source.setting_key WHEN MATCHED THEN UPDATE SET setting_value=?,updated_by=?,updated_at=SYSUTCDATETIME() WHEN NOT MATCHED THEN INSERT (setting_key,setting_value,updated_by) VALUES (?,?,?);",(key,str(value),user['username'],key,str(value),user['username'])); db.commit()
        return {'setting_key':key,'setting_value':str(value),'updated_by':user['username']}

    @router.get('/backups')
    def backups(_=Depends(require_roles(['Admin']))):
        return _rows(connect,'SELECT TOP 100 * FROM backup_runs ORDER BY id DESC')

    @router.post('/backups',status_code=202)
    def create_backup(item:BackupCreate,_=Depends(require_roles(['Admin']))):
        """Run a SQL Server native backup to the configured server-visible directory."""
        backup_root=Path(os.getenv('BACKUP_DIR','backups')).resolve(); backup_root.mkdir(parents=True,exist_ok=True)
        destination=(backup_root/f"{item.name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.bak").resolve()
        if backup_root not in destination.parents: raise HTTPException(400,'Invalid backup destination')
        cid=uuid4().hex
        with connect() as db:
            cur=db.execute("INSERT INTO backup_runs (correlation_id,status,destination) VALUES (?,'Running',?)",(cid,str(destination))); db.commit(); run_id=cur.lastrowid
        try:
            database=os.getenv('DB_NAME','').replace(']','')
            if not database: raise RuntimeError('DB_NAME is not configured')
            with connect() as db:
                db.execute(f"BACKUP DATABASE [{database}] TO DISK=? WITH COPY_ONLY, CHECKSUM, INIT",(str(destination),)); db.commit()
                manifest={'database':database,'destination':str(destination),'copy_only':True,'checksum':True}
                db.execute("UPDATE backup_runs SET status='Completed',manifest_json=?,completed_at=SYSUTCDATETIME() WHERE id=?",(json.dumps(manifest),run_id)); db.commit()
            return {'id':run_id,'correlation_id':cid,'status':'Completed','destination':str(destination)}
        except Exception as exc:
            with connect() as db:
                db.execute("UPDATE backup_runs SET status='Failed',error_detail=?,completed_at=SYSUTCDATETIME() WHERE id=?",(str(exc)[:4000],run_id)); db.commit()
            raise HTTPException(500,'Backup failed. Verify SQL Server service-account access to BACKUP_DIR.')

    @router.get('/retention/preview')
    def retention_preview(days:int=3650,_=Depends(require_roles(['Admin']))):
        if days < 1: raise HTTPException(400,'days must be positive')
        with connect() as db:
            counts={
              'audit_events':db.execute('SELECT COUNT(*) AS n FROM audit_log WHERE created_at < DATEADD(day, ?, SYSUTCDATETIME())',(-days,)).fetchone()['n'],
              'integration_events':db.execute('SELECT COUNT(*) AS n FROM integration_events WHERE created_at < DATEADD(day, ?, SYSUTCDATETIME())',(-days,)).fetchone()['n'],
            }
        return {'retention_days':days,'preview_only':True,'eligible':counts}

    @router.get('/audit')
    def audit_events(_=Depends(require_roles(['Admin']))): return _rows(connect, 'SELECT TOP 500 * FROM audit_log ORDER BY id DESC')
    return router


def init_platform_schema(connect):
    with connect() as db:
        for statement in DDL: db.execute(statement)
        db.commit()
