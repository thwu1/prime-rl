CREATE TABLE samples (
    gene_id TEXT PRIMARY KEY,
    organism TEXT NOT NULL,
    sample_type TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    collection_date TEXT
);

CREATE TABLE mass_spec_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    gene_id TEXT NOT NULL,
    protein_sequence TEXT NOT NULL,
    confidence REAL NOT NULL,
    instrument TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (gene_id) REFERENCES samples(gene_id)
);

CREATE TABLE instrument_calibrations (
    calibration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id TEXT NOT NULL,
    calibration_date TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    status TEXT NOT NULL,
    certified_by TEXT,
    tolerance_ppm REAL
);

CREATE TABLE run_instrument_assignments (
    run_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary',
    PRIMARY KEY (run_id, instrument_id)
);

CREATE INDEX idx_ms_gene ON mass_spec_results(gene_id);
CREATE INDEX idx_ms_instrument ON mass_spec_results(instrument);
CREATE INDEX idx_samples_type ON samples(sample_type);
CREATE INDEX idx_samples_org ON samples(organism);
CREATE INDEX idx_samples_batch ON samples(batch_id);
CREATE INDEX idx_calib_instrument ON instrument_calibrations(instrument_id);

INSERT INTO samples VALUES ('XG0001','xenobiont_alpha','characterized','RUN_2157A','2158-08-15');
INSERT INTO samples VALUES ('XG0002','xenobiont_alpha','characterized','RUN_2157B','2157-07-26');
INSERT INTO samples VALUES ('XG0003','xenobiont_alpha','characterized','RUN_2157C','2158-01-20');
INSERT INTO samples VALUES ('XG0004','xenobiont_alpha','characterized','RUN_2158A','2158-09-04');
INSERT INTO samples VALUES ('XG0005','xenobiont_alpha','characterized','RUN_2158B','2157-08-25');
INSERT INTO samples VALUES ('XG0006','xenobiont_alpha','characterized','RUN_2157A','2156-02-16');
INSERT INTO samples VALUES ('XG0007','xenobiont_alpha','characterized','RUN_2157B','2158-08-02');
INSERT INTO samples VALUES ('XG0008','xenobiont_alpha','characterized','RUN_2157C','2157-03-05');
INSERT INTO samples VALUES ('XG0009','xenobiont_alpha','characterized','RUN_2158A','2156-03-24');
INSERT INTO samples VALUES ('XG0010','xenobiont_alpha','characterized','RUN_2158B','2157-09-20');
INSERT INTO samples VALUES ('XG0011','xenobiont_alpha','characterized','RUN_2157A','2158-12-21');
INSERT INTO samples VALUES ('XG0012','xenobiont_alpha','characterized','RUN_2157B','2158-09-23');
INSERT INTO samples VALUES ('XG0013','xenobiont_alpha','characterized','RUN_2157C','2158-08-27');
INSERT INTO samples VALUES ('XG0014','xenobiont_alpha','characterized','RUN_2158A','2157-02-19');
INSERT INTO samples VALUES ('XG0015','xenobiont_alpha','characterized','RUN_2158B','2158-01-12');
INSERT INTO samples VALUES ('XG0016','xenobiont_alpha','characterized','RUN_2157A','2158-12-10');
INSERT INTO samples VALUES ('XG0017','xenobiont_alpha','characterized','RUN_2157B','2158-07-07');
INSERT INTO samples VALUES ('XG0018','xenobiont_alpha','characterized','RUN_2157C','2157-03-08');
INSERT INTO samples VALUES ('XG0019','xenobiont_alpha','characterized','RUN_2158A','2157-03-22');
INSERT INTO samples VALUES ('XG0020','xenobiont_alpha','characterized','RUN_2158B','2158-06-11');
INSERT INTO samples VALUES ('XG0021','xenobiont_alpha','characterized','RUN_2157A','2156-06-26');
INSERT INTO samples VALUES ('XG0022','xenobiont_alpha','characterized','RUN_2157B','2157-03-23');
INSERT INTO samples VALUES ('XG0023','xenobiont_alpha','characterized','RUN_2157C','2158-12-13');
INSERT INTO samples VALUES ('XG0024','xenobiont_alpha','characterized','RUN_2158A','2156-07-16');
INSERT INTO samples VALUES ('XG0025','xenobiont_alpha','characterized','RUN_2158B','2158-09-19');
INSERT INTO samples VALUES ('XG0026','xenobiont_alpha','characterized','RUN_2157A','2158-08-21');
INSERT INTO samples VALUES ('XG0027','xenobiont_alpha','characterized','RUN_2157B','2156-08-08');
INSERT INTO samples VALUES ('XG0028','xenobiont_alpha','characterized','RUN_2157C','2157-09-04');
INSERT INTO samples VALUES ('XG0029','xenobiont_alpha','characterized','RUN_2158A','2156-04-26');
INSERT INTO samples VALUES ('XG0030','xenobiont_alpha','characterized','RUN_2158B','2157-04-09');
INSERT INTO samples VALUES ('XG0031','xenobiont_alpha','characterized','RUN_2157A','2158-11-27');
INSERT INTO samples VALUES ('XG0032','xenobiont_alpha','characterized','RUN_2157B','2158-03-18');
INSERT INTO samples VALUES ('XG0033','xenobiont_alpha','characterized','RUN_2157C','2157-12-26');
INSERT INTO samples VALUES ('XG0034','xenobiont_alpha','characterized','RUN_2158A','2156-09-06');
INSERT INTO samples VALUES ('XG0035','xenobiont_alpha','characterized','RUN_2158B','2156-05-28');
INSERT INTO samples VALUES ('XG0036','xenobiont_alpha','characterized','RUN_2157A','2158-05-15');
INSERT INTO samples VALUES ('XG0037','xenobiont_alpha','characterized','RUN_2157B','2158-11-26');
INSERT INTO samples VALUES ('XG0038','xenobiont_alpha','characterized','RUN_2157C','2156-01-02');
INSERT INTO samples VALUES ('XG0039','xenobiont_alpha','characterized','RUN_2158A','2158-01-01');
INSERT INTO samples VALUES ('XG0040','xenobiont_alpha','characterized','RUN_2158B','2157-05-06');
INSERT INTO samples VALUES ('XG0041','xenobiont_alpha','characterized','RUN_2157A','2158-04-11');
INSERT INTO samples VALUES ('XG0042','xenobiont_alpha','characterized','RUN_2157B','2157-02-21');
INSERT INTO samples VALUES ('XG0043','xenobiont_alpha','characterized','RUN_2157C','2156-08-13');
INSERT INTO samples VALUES ('XG0044','xenobiont_alpha','characterized','RUN_2158A','2156-05-08');
INSERT INTO samples VALUES ('XG0045','xenobiont_alpha','characterized','RUN_2158B','2157-02-02');
INSERT INTO samples VALUES ('XG0046','xenobiont_alpha','characterized','RUN_2157A','2158-02-14');
INSERT INTO samples VALUES ('XG0047','xenobiont_alpha','characterized','RUN_2157B','2157-11-13');
INSERT INTO samples VALUES ('XG0048','xenobiont_alpha','characterized','RUN_2157C','2156-12-01');
INSERT INTO samples VALUES ('XG0049','xenobiont_alpha','characterized','RUN_2158A','2156-09-25');
INSERT INTO samples VALUES ('XG0050','xenobiont_alpha','characterized','RUN_2158B','2156-04-12');
INSERT INTO samples VALUES ('XG0051','xenobiont_alpha','characterized','RUN_2157A','2158-03-24');
INSERT INTO samples VALUES ('XG0052','xenobiont_alpha','characterized','RUN_2157B','2157-01-19');
INSERT INTO samples VALUES ('XG0053','xenobiont_alpha','characterized','RUN_2157C','2158-05-15');
INSERT INTO samples VALUES ('XG0054','xenobiont_alpha','characterized','RUN_2158A','2157-02-26');
INSERT INTO samples VALUES ('XG0055','xenobiont_alpha','characterized','RUN_2158B','2158-04-27');
INSERT INTO samples VALUES ('XG0056','xenobiont_alpha','characterized','RUN_2157A','2158-10-18');
INSERT INTO samples VALUES ('XG0057','xenobiont_alpha','characterized','RUN_2157B','2157-12-01');
INSERT INTO samples VALUES ('XG0058','xenobiont_alpha','characterized','RUN_2157C','2158-11-19');
INSERT INTO samples VALUES ('XG0059','xenobiont_alpha','characterized','RUN_2158A','2157-02-19');
INSERT INTO samples VALUES ('EC0001','e_coli_control','characterized','RUN_2156X','2158-03-03');
INSERT INTO samples VALUES ('EC0002','e_coli_control','characterized','RUN_2156X','2157-07-13');
INSERT INTO samples VALUES ('EC0003','e_coli_control','characterized','RUN_2156X','2158-11-27');
INSERT INTO samples VALUES ('EC0004','e_coli_control','characterized','RUN_2156X','2156-03-15');
INSERT INTO samples VALUES ('EC0005','e_coli_control','characterized','RUN_2156X','2157-01-16');
INSERT INTO samples VALUES ('EC0006','e_coli_control','characterized','RUN_2156X','2157-09-08');
INSERT INTO samples VALUES ('EC0007','e_coli_control','characterized','RUN_2156X','2156-08-28');
INSERT INTO samples VALUES ('EC0008','e_coli_control','characterized','RUN_2156X','2157-06-17');
INSERT INTO samples VALUES ('XY0001','xenobiont_alpha','characterized','RUN_2157Y','2156-11-16');
INSERT INTO samples VALUES ('XY0002','xenobiont_alpha','characterized','RUN_2157Y','2158-05-04');
INSERT INTO samples VALUES ('XY0003','xenobiont_alpha','characterized','RUN_2157Y','2156-10-21');
INSERT INTO samples VALUES ('XY0004','xenobiont_alpha','characterized','RUN_2157Y','2156-03-10');
INSERT INTO samples VALUES ('XY0005','xenobiont_alpha','characterized','RUN_2157Y','2157-06-16');
INSERT INTO samples VALUES ('XY0006','xenobiont_alpha','characterized','RUN_2157Y','2156-01-09');
INSERT INTO samples VALUES ('XG0060','xenobiont_alpha','uncharacterized','RUN_2157A','2156-11-23');
INSERT INTO samples VALUES ('XG0061','xenobiont_alpha','uncharacterized','RUN_2157B','2156-04-22');
INSERT INTO samples VALUES ('XG0062','xenobiont_alpha','uncharacterized','RUN_2157C','2156-07-21');
INSERT INTO samples VALUES ('XG0063','xenobiont_alpha','uncharacterized','RUN_2158A','2156-04-19');
INSERT INTO samples VALUES ('XG0064','xenobiont_alpha','uncharacterized','RUN_2158B','2156-02-22');
INSERT INTO samples VALUES ('XG0065','xenobiont_alpha','uncharacterized','RUN_2157A','2156-08-02');
INSERT INTO samples VALUES ('XG0066','xenobiont_alpha','uncharacterized','RUN_2157B','2156-08-18');
INSERT INTO samples VALUES ('XG0067','xenobiont_alpha','uncharacterized','RUN_2157C','2156-03-07');
INSERT INTO samples VALUES ('XG0068','xenobiont_alpha','uncharacterized','RUN_2158A','2156-11-19');
INSERT INTO samples VALUES ('XG0069','xenobiont_alpha','uncharacterized','RUN_2158B','2157-02-08');
INSERT INTO samples VALUES ('XG0070','xenobiont_alpha','uncharacterized','RUN_2157A','2158-10-16');
INSERT INTO samples VALUES ('XG0071','xenobiont_alpha','uncharacterized','RUN_2157B','2158-10-06');
INSERT INTO samples VALUES ('XG0072','xenobiont_alpha','uncharacterized','RUN_2157C','2157-03-16');
INSERT INTO samples VALUES ('XG0073','xenobiont_alpha','uncharacterized','RUN_2158A','2158-06-06');
INSERT INTO samples VALUES ('XG0074','xenobiont_alpha','uncharacterized','RUN_2158B','2156-12-01');
INSERT INTO samples VALUES ('XG0075','xenobiont_alpha','uncharacterized','RUN_2157A','2158-06-25');
INSERT INTO samples VALUES ('XG0076','xenobiont_alpha','uncharacterized','RUN_2157B','2157-01-13');
INSERT INTO samples VALUES ('XG0077','xenobiont_alpha','uncharacterized','RUN_2157C','2158-03-22');
INSERT INTO samples VALUES ('XG0078','xenobiont_alpha','uncharacterized','RUN_2158A','2156-02-14');
INSERT INTO samples VALUES ('XG0079','xenobiont_alpha','uncharacterized','RUN_2158B','2158-09-22');
INSERT INTO samples VALUES ('XG0080','xenobiont_alpha','uncharacterized','RUN_2157A','2158-08-13');
INSERT INTO samples VALUES ('XG0081','xenobiont_alpha','uncharacterized','RUN_2157B','2157-04-28');
INSERT INTO samples VALUES ('XG0082','xenobiont_alpha','uncharacterized','RUN_2157C','2158-01-13');
INSERT INTO samples VALUES ('XG0083','xenobiont_alpha','uncharacterized','RUN_2158A','2158-08-13');
INSERT INTO samples VALUES ('XG0084','xenobiont_alpha','uncharacterized','RUN_2158B','2157-06-09');

INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0001','QTGVPIA',0.9483,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0001','QTGV',0.3931,'ESI-QTOF-2','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0002','GDGAGNGV',0.9566,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0003','GMGRHY',0.9678,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0003','GMGRHH',0.3798,'MALDI-TOF-1','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0004','ESVTVPG',0.9401,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0004','EQVTVPG',0.325,'ORBITRAP-3','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0005','PDMNG',0.9758,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0006','LVSLC',0.946,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0007','KGLSGVVGV',0.9281,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0007','KGLSGV',0.3303,'ORBITRAP-3','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0008','PGDGGPC',0.9516,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0009','AEPQYYGC',0.963,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0010','LPGCAS',0.9861,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0011','YRSSLCC',0.933,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0011','YRVSLCC',0.341,'ESI-QTOF-2','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0012','LPSITA',0.9758,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0013','GTGCLP',0.9353,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0014','CQGRPC',0.979,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0015','VADSLV',0.9633,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0016','QGHCGRVGRGGR',0.926,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0017','HGYNT',0.9654,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0018','VPMSCN',0.9571,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0019','QHGLYDN',0.9635,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0020','KGRGLTAGGWS',0.9495,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0020','KGRGLTRGGWS',0.535,'MALDI-TOF-1','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0021','NGGQSGA',0.9326,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0021','NGGQSGF',0.5392,'ESI-QTOF-2','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0022','MRAFVM',0.9843,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0022','CRAFVM',0.4494,'MALDI-TOF-1','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0023','SVHSSGVGV',0.9566,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0024','TPCEQF',0.9695,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0025','RWSPMFQS',0.9304,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0026','WGCQSRA',0.9796,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0027','SGGGQHIPGAI',0.9854,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0028','NHATG',0.9425,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0028','NHA',0.4508,'MALDI-TOF-1','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0029','AKGSSFG',0.9684,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0030','ALPPP',0.9163,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0030','AQPPP',0.3287,'MALDI-TOF-1','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0031','PGGRGCY',0.9186,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0031','MGGRGCY',0.3735,'MALDI-TOF-1','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0032','ALWYCWC',0.9136,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0033','HWNGDQGR',0.9851,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0034','LCGCAQGPGAT',0.9142,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0034','LCGCAQGPG',0.4778,'ORBITRAP-3','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0035','MDCGGP',0.9263,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0035','MDCGGK',0.432,'ESI-QTOF-2','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0036','QTCNQT',0.9461,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0037','WKPSRDRV',0.9644,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0038','HGVYGRV',0.9323,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0039','VLVTNQI',0.971,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0040','AGEMQW',0.9112,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0041','EMKPY',0.9765,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0042','LWGPS',0.9765,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0043','SQGLTALA',0.9519,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0043','SQGLTAL',0.4355,'ORBITRAP-3','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0044','SSTISHSS',0.9858,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0044','SSTISHS',0.5007,'MALDI-TOF-1','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0045','PTMND',0.9756,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0046','RWGEGHNVGQY',0.9144,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0046','RWGEYHNVGQY',0.3198,'ORBITRAP-3','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0047','NGGRGRTVTGG',0.9869,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0047','NGGRGRTV',0.4178,'ESI-QTOF-2','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0048','ANVGHTV',0.944,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0049','PGLSVGW',0.9226,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0050','WPYYC',0.9311,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0050','WP',0.5987,'ESI-QTOF-2','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0051','LCANT',0.936,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0052','ETCSGCNGG',0.955,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0052','ETCSGCNG',0.4773,'ORBITRAP-3','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0053','CEMMYMGV',0.9138,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0053','CEMMYM',0.5458,'ESI-QTOF-2','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0054','PNSHGA',0.9601,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0054','PNSHG',0.4509,'ESI-QTOF-2','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0055','SEPGTAVG',0.9222,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0056','DMVVGGGRS',0.9617,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0056','DMVVGGG',0.3001,'ORBITRAP-3','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0057','RYCQGPCL',0.9657,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0058','LASPSGQ',0.9157,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0058','GASPSGQ',0.5796,'ESI-QTOF-2','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0059','FILHC',0.9672,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XG0059','GILHC',0.5459,'ESI-QTOF-2','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('EC0001','SPSISSSN',0.9439,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('EC0002','LIRCS',0.9867,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('EC0003','CRT',0.9899,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('EC0004','RRAEAC',0.9453,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('EC0005','VVSFCEA',0.9254,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('EC0006','SVTARCK',0.966,'ORBITRAP-3','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('EC0007','NGHSC',0.9476,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('EC0008','FRRSSL',0.9112,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0001','MEDVKV',0.9624,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0001','MELVKV',0.4786,'ESI-QTOF-2','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0002','VENTCP',0.9441,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0002','YENTCP',0.3718,'MALDI-TOF-1','rerun - low signal');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0003','TDASNQW',0.9618,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0004','HDGGF',0.9446,'ESI-QTOF-2','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0004','HDG',0.4967,'MALDI-TOF-1','partial - signal cutoff');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0005','WSDCA',0.9623,'MALDI-TOF-1','primary run');
INSERT INTO mass_spec_results (gene_id,protein_sequence,confidence,instrument,notes) VALUES ('XY0006','HKNSTPT',0.9521,'ORBITRAP-3','primary run');

INSERT INTO instrument_calibrations (instrument_id,calibration_date,expiry_date,status,certified_by,tolerance_ppm) VALUES ('ORBITRAP-3','2157-01-10','2159-01-10','valid','Instrument Services Division',2.0);
INSERT INTO instrument_calibrations (instrument_id,calibration_date,expiry_date,status,certified_by,tolerance_ppm) VALUES ('MALDI-TOF-1','2157-02-15','2159-02-15','valid','Instrument Services Division',5.0);
INSERT INTO instrument_calibrations (instrument_id,calibration_date,expiry_date,status,certified_by,tolerance_ppm) VALUES ('ESI-QTOF-2','2156-11-20','2158-11-20','valid','Exobiology Analytical Core',3.0);
INSERT INTO instrument_calibrations (instrument_id,calibration_date,expiry_date,status,certified_by,tolerance_ppm) VALUES ('ESI-QTOF-OLD','2155-06-01','2157-06-01','expired','Instrument Services Division',8.0);

INSERT INTO run_instrument_assignments VALUES ('RUN_2157A','ORBITRAP-3','primary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2157A','MALDI-TOF-1','secondary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2157B','MALDI-TOF-1','primary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2157B','ESI-QTOF-2','secondary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2157C','ORBITRAP-3','primary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2157C','MALDI-TOF-1','secondary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2157C','ESI-QTOF-2','secondary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2158A','ORBITRAP-3','primary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2158A','ESI-QTOF-2','secondary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2158B','ORBITRAP-3','primary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2158B','MALDI-TOF-1','secondary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2158B','ESI-QTOF-2','secondary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2156X','MALDI-TOF-1','primary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2156X','ESI-QTOF-OLD','secondary');
INSERT INTO run_instrument_assignments VALUES ('RUN_2157Y','ESI-QTOF-2','primary');
