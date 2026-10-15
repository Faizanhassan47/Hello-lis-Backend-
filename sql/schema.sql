/*
 Digital Pathology SQL Server schema
 -----------------------------------
 Run this script while connected to the database selected for the application.
 It does not create, select, drop, or clear a database, and it is safe to rerun.
 Application startup also performs idempotent schema initialization.
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF OBJECT_ID('dbo.users', 'U') IS NULL
CREATE TABLE dbo.users (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_users PRIMARY KEY,
    username VARCHAR(255) NOT NULL CONSTRAINT UQ_users_username UNIQUE,
    display_name VARCHAR(MAX) NOT NULL,
    role VARCHAR(MAX) NOT NULL,
    password_hash VARCHAR(MAX) NOT NULL,
    is_active INT NOT NULL CONSTRAINT DF_users_active DEFAULT (1),
    created_at VARCHAR(MAX) NULL CONSTRAINT DF_users_created DEFAULT (CURRENT_TIMESTAMP),
    last_login DATETIME NULL
);
GO

IF OBJECT_ID('dbo.cases', 'U') IS NULL
CREATE TABLE dbo.cases (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_cases PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL CONSTRAINT UQ_cases_case_id UNIQUE,
    description VARCHAR(MAX) NOT NULL,
    filename VARCHAR(255) NOT NULL CONSTRAINT DF_cases_filename DEFAULT (''),
    created_at DATETIME NOT NULL CONSTRAINT DF_cases_created DEFAULT (CURRENT_TIMESTAMP),
    file_type VARCHAR(MAX) NOT NULL CONSTRAINT DF_cases_file_type DEFAULT ('raster'),
    format VARCHAR(MAX) NULL,
    width INT NULL,
    height INT NULL,
    file_size INT NULL,
    status VARCHAR(MAX) NOT NULL CONSTRAINT DF_cases_status DEFAULT ('New'),
    reviewer VARCHAR(MAX) NOT NULL CONSTRAINT DF_cases_reviewer DEFAULT ('')
);
GO

IF OBJECT_ID('dbo.slides', 'U') IS NULL
CREATE TABLE dbo.slides (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_slides PRIMARY KEY,
    case_id INT NOT NULL CONSTRAINT FK_slides_cases REFERENCES dbo.cases(id),
    label VARCHAR(MAX) NOT NULL,
    stain VARCHAR(MAX) NOT NULL CONSTRAINT DF_slides_stain DEFAULT (''),
    specimen_description VARCHAR(MAX) NOT NULL CONSTRAINT DF_slides_specimen DEFAULT (''),
    filename VARCHAR(255) NOT NULL CONSTRAINT UQ_slides_filename UNIQUE,
    file_type VARCHAR(MAX) NOT NULL CONSTRAINT CK_slides_file_type CHECK (file_type IN ('raster','wsi')),
    format VARCHAR(MAX) NOT NULL,
    file_size INT NOT NULL,
    width INT NOT NULL,
    height INT NOT NULL,
    level_count INT NOT NULL CONSTRAINT DF_slides_levels DEFAULT (1),
    thumbnail VARBINARY(MAX) NULL,
    upload_state VARCHAR(MAX) NOT NULL CONSTRAINT DF_slides_upload_state DEFAULT ('uploading'),
    created_at DATETIME NOT NULL CONSTRAINT DF_slides_created DEFAULT (CURRENT_TIMESTAMP),
    qc_status VARCHAR(MAX) NULL,
    qc_missing_tissue INT NULL CONSTRAINT DF_slides_qc_missing DEFAULT (0),
    qc_blur INT NULL CONSTRAINT DF_slides_qc_blur DEFAULT (0),
    qc_scan_artifact INT NULL CONSTRAINT DF_slides_qc_artifact DEFAULT (0),
    qc_incorrect_label INT NULL CONSTRAINT DF_slides_qc_label DEFAULT (0),
    qc_note VARCHAR(MAX) NULL CONSTRAINT DF_slides_qc_note DEFAULT (''),
    qc_actor VARCHAR(MAX) NULL CONSTRAINT DF_slides_qc_actor DEFAULT (''),
    qc_timestamp DATETIME NULL,
    CONSTRAINT CK_slides_upload_state CHECK (upload_state IN ('uploading','processing','ready','error'))
);
GO

IF OBJECT_ID('dbo.slide_qc_history', 'U') IS NULL
CREATE TABLE dbo.slide_qc_history (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_slide_qc_history PRIMARY KEY,
    slide_id INT NOT NULL CONSTRAINT FK_slide_qc_history_slide REFERENCES dbo.slides(id),
    qc_status VARCHAR(MAX) NULL,
    qc_missing_tissue BIT NULL,
    qc_blur BIT NULL,
    qc_scan_artifact BIT NULL,
    qc_incorrect_label BIT NULL,
    qc_note VARCHAR(MAX) NULL,
    actor VARCHAR(MAX) NOT NULL,
    created_at VARCHAR(MAX) NULL CONSTRAINT DF_slide_qc_history_created DEFAULT (CURRENT_TIMESTAMP)
);
GO

IF OBJECT_ID('dbo.annotations', 'U') IS NULL
CREATE TABLE dbo.annotations (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_annotations PRIMARY KEY,
    slide_id INT NOT NULL CONSTRAINT FK_annotations_slide REFERENCES dbo.slides(id),
    annotation_type VARCHAR(MAX) NOT NULL CONSTRAINT DF_annotations_type DEFAULT ('rectangle'),
    label VARCHAR(MAX) NOT NULL,
    note VARCHAR(MAX) NOT NULL CONSTRAINT DF_annotations_note DEFAULT (''),
    color VARCHAR(MAX) NOT NULL CONSTRAINT DF_annotations_color DEFAULT ('#e85d75'),
    x REAL NULL, y REAL NULL, width REAL NULL, height REAL NULL,
    points VARCHAR(MAX) NULL,
    created_at DATETIME NOT NULL CONSTRAINT DF_annotations_created DEFAULT (CURRENT_TIMESTAMP),
    updated_at VARCHAR(MAX) NOT NULL CONSTRAINT DF_annotations_updated DEFAULT (CURRENT_TIMESTAMP),
    CONSTRAINT CK_annotations_type CHECK (annotation_type IN ('rectangle','polygon','arrow'))
);
GO

IF OBJECT_ID('dbo.case_review_notes', 'U') IS NULL
CREATE TABLE dbo.case_review_notes (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_case_review_notes PRIMARY KEY,
    case_id INT NOT NULL CONSTRAINT FK_case_review_notes_case REFERENCES dbo.cases(id),
    author VARCHAR(MAX) NOT NULL,
    note VARCHAR(MAX) NOT NULL,
    created_at DATETIME NOT NULL CONSTRAINT DF_case_review_notes_created DEFAULT (CURRENT_TIMESTAMP)
);
GO

IF OBJECT_ID('dbo.case_review_history', 'U') IS NULL
CREATE TABLE dbo.case_review_history (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_case_review_history PRIMARY KEY,
    case_id INT NOT NULL CONSTRAINT FK_case_review_history_case REFERENCES dbo.cases(id),
    change_type VARCHAR(MAX) NOT NULL,
    previous_value VARCHAR(MAX) NOT NULL,
    new_value VARCHAR(MAX) NOT NULL,
    actor VARCHAR(MAX) NOT NULL,
    created_at DATETIME NOT NULL CONSTRAINT DF_case_review_history_created DEFAULT (CURRENT_TIMESTAMP),
    CONSTRAINT CK_case_review_history_type CHECK (change_type IN ('status','reviewer'))
);
GO

IF OBJECT_ID('dbo.reports', 'U') IS NULL
CREATE TABLE dbo.reports (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_reports PRIMARY KEY,
    case_id INT NOT NULL CONSTRAINT FK_reports_case REFERENCES dbo.cases(id),
    version INT NOT NULL,
    status VARCHAR(MAX) NOT NULL,
    specimen_clinical VARCHAR(MAX) NOT NULL CONSTRAINT DF_reports_specimen DEFAULT (''),
    gross_description VARCHAR(MAX) NOT NULL CONSTRAINT DF_reports_gross DEFAULT (''),
    microscopic_findings VARCHAR(MAX) NOT NULL CONSTRAINT DF_reports_micro DEFAULT (''),
    diagnosis VARCHAR(MAX) NOT NULL CONSTRAINT DF_reports_diagnosis DEFAULT (''),
    comments VARCHAR(MAX) NOT NULL CONSTRAINT DF_reports_comments DEFAULT (''),
    reviewer_name VARCHAR(MAX) NOT NULL CONSTRAINT DF_reports_reviewer DEFAULT (''),
    created_at DATETIME NOT NULL CONSTRAINT DF_reports_created DEFAULT (CURRENT_TIMESTAMP),
    finalized_at VARCHAR(MAX) NULL,
    CONSTRAINT CK_reports_status CHECK (status IN ('Draft','Finalized'))
);
GO

IF OBJECT_ID('dbo.audit_log', 'U') IS NULL
CREATE TABLE dbo.audit_log (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_audit_log PRIMARY KEY,
    actor_username VARCHAR(MAX) NOT NULL,
    action VARCHAR(MAX) NOT NULL,
    target_type VARCHAR(MAX) NOT NULL,
    target_id VARCHAR(MAX) NOT NULL CONSTRAINT DF_audit_target DEFAULT (''),
    details VARCHAR(MAX) NOT NULL CONSTRAINT DF_audit_details DEFAULT (''),
    created_at DATETIME NOT NULL CONSTRAINT DF_audit_created DEFAULT (CURRENT_TIMESTAMP)
);
GO

IF OBJECT_ID('dbo.report_findings', 'U') IS NULL
CREATE TABLE dbo.report_findings (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_report_findings PRIMARY KEY,
    report_id INT NOT NULL CONSTRAINT FK_report_findings_report REFERENCES dbo.reports(id),
    slide_id INT NULL CONSTRAINT FK_report_findings_slide REFERENCES dbo.slides(id) ON DELETE SET NULL,
    annotation_id INT NULL CONSTRAINT FK_report_findings_annotation REFERENCES dbo.annotations(id) ON DELETE SET NULL,
    text VARCHAR(MAX) NOT NULL CONSTRAINT DF_report_findings_text DEFAULT (''),
    sort_order INT NOT NULL CONSTRAINT DF_report_findings_order DEFAULT (0)
);
GO

IF OBJECT_ID('dbo.patients', 'U') IS NULL
CREATE TABLE dbo.patients (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_patients PRIMARY KEY,
    external_id VARCHAR(255) NULL CONSTRAINT UQ_patients_external UNIQUE,
    display_label VARCHAR(255) NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_patients_created DEFAULT (SYSUTCDATETIME())
);
GO

IF OBJECT_ID('dbo.accessions', 'U') IS NULL
CREATE TABLE dbo.accessions (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_accessions PRIMARY KEY,
    patient_id INT NULL CONSTRAINT FK_accessions_patient REFERENCES dbo.patients(id),
    accession_number VARCHAR(255) NOT NULL CONSTRAINT UQ_accessions_number UNIQUE,
    order_id VARCHAR(255) NULL,
    priority VARCHAR(30) NOT NULL CONSTRAINT DF_accessions_priority DEFAULT ('Routine'),
    due_at DATETIME2 NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_accessions_created DEFAULT (SYSUTCDATETIME())
);
GO

IF OBJECT_ID('dbo.specimens', 'U') IS NULL
CREATE TABLE dbo.specimens (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_specimens PRIMARY KEY,
    accession_id INT NOT NULL CONSTRAINT FK_specimens_accession REFERENCES dbo.accessions(id),
    specimen_code VARCHAR(255) NOT NULL,
    specimen_type VARCHAR(255) NULL,
    description VARCHAR(MAX) NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_specimens_created DEFAULT (SYSUTCDATETIME())
);
GO

IF OBJECT_ID('dbo.blocks', 'U') IS NULL
CREATE TABLE dbo.blocks (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_blocks PRIMARY KEY,
    specimen_id INT NOT NULL CONSTRAINT FK_blocks_specimen REFERENCES dbo.specimens(id),
    block_code VARCHAR(255) NOT NULL,
    description VARCHAR(MAX) NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_blocks_created DEFAULT (SYSUTCDATETIME())
);
GO

IF OBJECT_ID('dbo.ingestion_jobs', 'U') IS NULL
CREATE TABLE dbo.ingestion_jobs (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ingestion_jobs PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL CONSTRAINT UQ_ingestion_correlation UNIQUE,
    source_path VARCHAR(2048) NULL,
    source_device VARCHAR(255) NULL,
    adapter_name VARCHAR(120) NOT NULL CONSTRAINT DF_ingestion_adapter DEFAULT ('manual'),
    original_filename VARCHAR(512) NOT NULL,
    checksum_sha256 VARCHAR(64) NULL,
    file_size BIGINT NULL,
    status VARCHAR(30) NOT NULL,
    attempts INT NOT NULL CONSTRAINT DF_ingestion_attempts DEFAULT (0),
    progress INT NOT NULL CONSTRAINT DF_ingestion_progress DEFAULT (0),
    error_detail VARCHAR(MAX) NULL,
    quarantine_path VARCHAR(2048) NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_ingestion_created DEFAULT (SYSUTCDATETIME()),
    started_at DATETIME2 NULL,
    completed_at DATETIME2 NULL
);
GO

IF OBJECT_ID('dbo.image_versions', 'U') IS NULL
CREATE TABLE dbo.image_versions (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_image_versions PRIMARY KEY,
    slide_id INT NOT NULL CONSTRAINT FK_image_versions_slide REFERENCES dbo.slides(id),
    version INT NOT NULL,
    checksum_sha256 VARCHAR(64) NOT NULL,
    source_path VARCHAR(2048) NULL,
    source_device VARCHAR(255) NULL,
    scanner_make VARCHAR(120) NULL,
    scanner_model VARCHAR(120) NULL,
    magnification FLOAT NULL,
    pixel_size_microns FLOAT NULL,
    acquisition_time DATETIME2 NULL,
    metadata_json VARCHAR(MAX) NULL,
    stored_filename VARCHAR(512) NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_image_versions_created DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT UQ_image_versions_slide_version UNIQUE (slide_id, version)
);
GO

IF OBJECT_ID('dbo.reconciliation_items', 'U') IS NULL
CREATE TABLE dbo.reconciliation_items (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_reconciliation_items PRIMARY KEY,
    ingestion_job_id INT NULL CONSTRAINT FK_reconciliation_job REFERENCES dbo.ingestion_jobs(id),
    proposed_case_id VARCHAR(255) NULL,
    reason VARCHAR(MAX) NOT NULL,
    status VARCHAR(30) NOT NULL CONSTRAINT DF_reconciliation_status DEFAULT ('Open'),
    resolved_case_id INT NULL CONSTRAINT FK_reconciliation_case REFERENCES dbo.cases(id),
    resolved_by VARCHAR(255) NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_reconciliation_created DEFAULT (SYSUTCDATETIME()),
    resolved_at DATETIME2 NULL
);
GO

IF OBJECT_ID('dbo.scanner_compatibility', 'U') IS NULL
CREATE TABLE dbo.scanner_compatibility (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_scanner_compatibility PRIMARY KEY,
    manufacturer VARCHAR(120) NOT NULL,
    model VARCHAR(120) NOT NULL,
    software_version VARCHAR(120) NULL,
    format VARCHAR(80) NOT NULL,
    import_method VARCHAR(120) NOT NULL,
    metadata_coverage VARCHAR(MAX) NULL,
    limitations VARCHAR(MAX) NULL,
    validation_status VARCHAR(30) NOT NULL CONSTRAINT DF_scanner_validation DEFAULT ('Unverified'),
    tested_at DATETIME2 NULL
);
GO

IF OBJECT_ID('dbo.ai_models', 'U') IS NULL
CREATE TABLE dbo.ai_models (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ai_models PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(120) NOT NULL,
    checksum VARCHAR(128) NOT NULL,
    task VARCHAR(255) NOT NULL,
    intended_use VARCHAR(MAX) NULL,
    compatible_inputs VARCHAR(MAX) NULL,
    limitations VARCHAR(MAX) NULL,
    approval_status VARCHAR(30) NOT NULL CONSTRAINT DF_ai_models_approval DEFAULT ('Research'),
    adapter_name VARCHAR(120) NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_ai_models_created DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT UQ_ai_models_name_version UNIQUE (name, version)
);
GO

IF OBJECT_ID('dbo.ai_jobs', 'U') IS NULL
CREATE TABLE dbo.ai_jobs (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ai_jobs PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL CONSTRAINT UQ_ai_jobs_correlation UNIQUE,
    model_id INT NOT NULL CONSTRAINT FK_ai_jobs_model REFERENCES dbo.ai_models(id),
    slide_id INT NOT NULL CONSTRAINT FK_ai_jobs_slide REFERENCES dbo.slides(id),
    image_version_id INT NULL CONSTRAINT FK_ai_jobs_image_version REFERENCES dbo.image_versions(id),
    status VARCHAR(30) NOT NULL,
    progress INT NOT NULL CONSTRAINT DF_ai_jobs_progress DEFAULT (0),
    parameters_json VARCHAR(MAX) NULL,
    environment_json VARCHAR(MAX) NULL,
    error_detail VARCHAR(MAX) NULL,
    requested_by VARCHAR(255) NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_ai_jobs_created DEFAULT (SYSUTCDATETIME()),
    started_at DATETIME2 NULL,
    completed_at DATETIME2 NULL
);
GO

IF OBJECT_ID('dbo.ai_results', 'U') IS NULL
CREATE TABLE dbo.ai_results (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ai_results PRIMARY KEY,
    ai_job_id INT NOT NULL CONSTRAINT FK_ai_results_job REFERENCES dbo.ai_jobs(id),
    result_type VARCHAR(80) NOT NULL,
    geometry_json VARCHAR(MAX) NULL,
    measurements_json VARCHAR(MAX) NULL,
    confidence FLOAT NULL,
    raw_output_json VARCHAR(MAX) NULL,
    review_status VARCHAR(30) NOT NULL CONSTRAINT DF_ai_results_review DEFAULT ('Unreviewed'),
    reviewed_by VARCHAR(255) NULL,
    review_note VARCHAR(MAX) NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_ai_results_created DEFAULT (SYSUTCDATETIME()),
    reviewed_at DATETIME2 NULL
);
GO

IF OBJECT_ID('dbo.hl7_channels', 'U') IS NULL
CREATE TABLE dbo.hl7_channels (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_hl7_channels PRIMARY KEY,
    name VARCHAR(255) NOT NULL CONSTRAINT UQ_hl7_channels_name UNIQUE,
    direction VARCHAR(20) NOT NULL,
    version VARCHAR(20) NOT NULL CONSTRAINT DF_hl7_channels_version DEFAULT ('2.5.1'),
    transport VARCHAR(30) NOT NULL CONSTRAINT DF_hl7_channels_transport DEFAULT ('MLLP'),
    host VARCHAR(255) NULL,
    port INT NULL,
    enabled BIT NOT NULL CONSTRAINT DF_hl7_channels_enabled DEFAULT (0),
    mapping_json VARCHAR(MAX) NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_hl7_channels_created DEFAULT (SYSUTCDATETIME())
);
GO

IF OBJECT_ID('dbo.integration_events', 'U') IS NULL
CREATE TABLE dbo.integration_events (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_integration_events PRIMARY KEY,
    channel_id INT NULL CONSTRAINT FK_integration_events_channel REFERENCES dbo.hl7_channels(id),
    correlation_id VARCHAR(64) NOT NULL CONSTRAINT UQ_integration_events_correlation UNIQUE,
    message_control_id VARCHAR(255) NULL,
    message_type VARCHAR(40) NULL,
    direction VARCHAR(20) NOT NULL,
    raw_payload VARCHAR(MAX) NOT NULL,
    normalized_json VARCHAR(MAX) NULL,
    status VARCHAR(30) NOT NULL,
    acknowledgement VARCHAR(MAX) NULL,
    attempts INT NOT NULL CONSTRAINT DF_integration_attempts DEFAULT (0),
    error_detail VARCHAR(MAX) NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT DF_integration_created DEFAULT (SYSUTCDATETIME()),
    processed_at DATETIME2 NULL
);
GO

IF OBJECT_ID('dbo.system_settings', 'U') IS NULL
CREATE TABLE dbo.system_settings (
    setting_key VARCHAR(255) NOT NULL CONSTRAINT PK_system_settings PRIMARY KEY,
    setting_value VARCHAR(MAX) NULL,
    updated_by VARCHAR(255) NULL,
    updated_at DATETIME2 NOT NULL CONSTRAINT DF_system_settings_updated DEFAULT (SYSUTCDATETIME())
);
GO

IF OBJECT_ID('dbo.backup_runs', 'U') IS NULL
CREATE TABLE dbo.backup_runs (
    id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_backup_runs PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL CONSTRAINT UQ_backup_runs_correlation UNIQUE,
    status VARCHAR(30) NOT NULL,
    destination VARCHAR(2048) NULL,
    manifest_json VARCHAR(MAX) NULL,
    error_detail VARCHAR(MAX) NULL,
    started_at DATETIME2 NOT NULL CONSTRAINT DF_backup_runs_started DEFAULT (SYSUTCDATETIME()),
    completed_at DATETIME2 NULL
);
GO

/* Query indexes used by the API. */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_slides_case_id' AND object_id=OBJECT_ID('dbo.slides')) CREATE INDEX idx_slides_case_id ON dbo.slides(case_id,id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_slide_qc_history_slide_id' AND object_id=OBJECT_ID('dbo.slide_qc_history')) CREATE INDEX idx_slide_qc_history_slide_id ON dbo.slide_qc_history(slide_id,id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_annotations_slide_id' AND object_id=OBJECT_ID('dbo.annotations')) CREATE INDEX idx_annotations_slide_id ON dbo.annotations(slide_id,id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_case_review_notes_case_id' AND object_id=OBJECT_ID('dbo.case_review_notes')) CREATE INDEX idx_case_review_notes_case_id ON dbo.case_review_notes(case_id,id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_case_review_history_case_id' AND object_id=OBJECT_ID('dbo.case_review_history')) CREATE INDEX idx_case_review_history_case_id ON dbo.case_review_history(case_id,id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_reports_case_id' AND object_id=OBJECT_ID('dbo.reports')) CREATE INDEX idx_reports_case_id ON dbo.reports(case_id,version DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_audit_log_created_at' AND object_id=OBJECT_ID('dbo.audit_log')) CREATE INDEX idx_audit_log_created_at ON dbo.audit_log(created_at DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_report_findings_report_id' AND object_id=OBJECT_ID('dbo.report_findings')) CREATE INDEX idx_report_findings_report_id ON dbo.report_findings(report_id,sort_order);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_ingestion_checksum' AND object_id=OBJECT_ID('dbo.ingestion_jobs')) CREATE INDEX idx_ingestion_checksum ON dbo.ingestion_jobs(checksum_sha256,status);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_ai_jobs_status' AND object_id=OBJECT_ID('dbo.ai_jobs')) CREATE INDEX idx_ai_jobs_status ON dbo.ai_jobs(status,created_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='idx_integration_events_status' AND object_id=OBJECT_ID('dbo.integration_events')) CREATE INDEX idx_integration_events_status ON dbo.integration_events(status,created_at);
GO
