-- Alien Signal Detection Database Schema and Data

CREATE TABLE observatories (
    observstation VARCHAR(60) PRIMARY KEY,
    weathprofile VARCHAR(40),
    seeingprofile VARCHAR(50),
    atmostransparency NUMERIC(5,3),
    lunarstage VARCHAR(25),
    lunardistdeg NUMERIC(7,2),
    solarstatus VARCHAR(35),
    geomagstatus VARCHAR(35),
    sidereallocal VARCHAR(12),
    airtempc NUMERIC(5,2),
    humidityrate NUMERIC(6,3),
    windspeedms NUMERIC(4,2),
    presshpa NUMERIC(6,1)
);

CREATE TABLE telescopes (
    telescregistry VARCHAR(20) PRIMARY KEY,
    observstation VARCHAR(60) NOT NULL REFERENCES observatories(observstation),
    equipstatus VARCHAR(35),
    calibrstatus VARCHAR(50),
    pointaccarc NUMERIC(6,2),
    trackaccarc NUMERIC(6,2),
    focusquality VARCHAR(25),
    detecttempk NUMERIC(7,2),
    coolsysstatus VARCHAR(35),
    powerstatus VARCHAR(30),
    datastorstatus VARCHAR(35),
    netstatus VARCHAR(40),
    bandusagepct NUMERIC(5,2),
    procqueuestatus VARCHAR(40)
);

CREATE TABLE signals (
    signalregistry VARCHAR(36) PRIMARY KEY,
    timemark TIMESTAMPTZ,
    telescref VARCHAR(20) NOT NULL REFERENCES telescopes(telescregistry),
    detectinstr VARCHAR(50),
    signalclass VARCHAR(50),
    sigstrdb NUMERIC(7,2),
    freqmhz NUMERIC(9,3),
    bwhz NUMERIC(13,3),
    centerfreqmhz NUMERIC(8,3),
    freqdrifthzs NUMERIC(9,3),
    doppshifthz DOUBLE PRECISION,
    sigdursec NUMERIC(10,2),
    pulsepersec NUMERIC(6,3),
    pulsewidms NUMERIC(6,3),
    modtype VARCHAR(30),
    modindex NUMERIC(6,4),
    carrierfreqmhz NUMERIC(9,3),
    phaseshiftdeg NUMERIC(6,2),
    polarmode VARCHAR(30),
    polarangledeg NUMERIC(5,1),
    snrratio NUMERIC(6,2),
    noisefloordbm DOUBLE PRECISION,
    interflvl VARCHAR(30),
    rfistat VARCHAR(30),
    atmointerf VARCHAR(30)
);

CREATE TABLE signalprobabilities (
    signalref VARCHAR(36) PRIMARY KEY REFERENCES signals(signalregistry),
    falseposprob NUMERIC(5,4),
    sigunique NUMERIC(7,4),
    simindex NUMERIC(5,4),
    corrscore NUMERIC(5,4),
    anomscore DOUBLE PRECISION,
    techsigprob NUMERIC(5,4),
    biosigprob NUMERIC(6,4),
    natsrcprob NUMERIC(7,4),
    artsrcprob NUMERIC(3,1)
);

CREATE TABLE signaldynamics (
    signalref VARCHAR(36) PRIMARY KEY REFERENCES signals(signalregistry),
    sigintegrity VARCHAR(30),
    sigrecurr VARCHAR(25),
    sigevolve VARCHAR(25),
    tempstab VARCHAR(20),
    spatstab VARCHAR(20),
    freqstab VARCHAR(35),
    phasestab VARCHAR(35),
    ampstab VARCHAR(20),
    modstab VARCHAR(30),
    sigcoherence VARCHAR(25),
    sigdisp VARCHAR(25),
    sigscint VARCHAR(45)
);

CREATE TABLE signalclassification (
    signalref VARCHAR(36) PRIMARY KEY REFERENCES signals(signalregistry),
    sigclasstype VARCHAR(40),
    sigpattern VARCHAR(60),
    repeatcount SMALLINT,
    periodsec NUMERIC(7,3),
    complexidx NUMERIC(6,3),
    entropyval NUMERIC(6,2),
    infodense NUMERIC(6,3),
    classconf NUMERIC(5,2)
);

CREATE TABLE signaldecoding (
    signalref VARCHAR(36) PRIMARY KEY REFERENCES signals(signalregistry),
    encodetype VARCHAR(40),
    compressratio NUMERIC(6,3),
    errcorrlvl VARCHAR(35),
    decodeconf NUMERIC(5,2),
    decodemethod VARCHAR(35),
    decodestat VARCHAR(25),
    decodeiters SMALLINT,
    proctimehrs NUMERIC(6,2),
    compresources VARCHAR(50),
    analysisdp VARCHAR(25),
    veriflvl VARCHAR(30),
    confirmstat VARCHAR(30)
);

CREATE TABLE observationalconditions (
    signalref VARCHAR(36) PRIMARY KEY REFERENCES signals(signalregistry),
    obstime TIME,
    obsdate DATE,
    obsdurhrs NUMERIC(5,2)
);

CREATE TABLE sourceproperties (
    signalref VARCHAR(36) PRIMARY KEY REFERENCES signals(signalregistry),
    sourceradeg NUMERIC(7,4),
    sourcedecdeg NUMERIC(7,4),
    sourcedistly NUMERIC(10,2),
    gallong NUMERIC(6,2),
    gallat NUMERIC(6,2),
    celestobj VARCHAR(75),
    objtype VARCHAR(50),
    objmag NUMERIC(5,2),
    objtempk INTEGER,
    objmasssol NUMERIC(6,3),
    objagegyr NUMERIC(6,3),
    objmetal NUMERIC(5,3),
    objpropmotion NUMERIC(7,2),
    objradvel NUMERIC(7,2)
);

CREATE TABLE signaladvancedphenomena (
    signalref VARCHAR(36) PRIMARY KEY REFERENCES signals(signalregistry),
    intermedeffects VARCHAR(40),
    gravlens VARCHAR(50),
    quanteffects VARCHAR(85),
    encryptevid VARCHAR(40),
    langstruct TEXT,
    msgcontent TEXT,
    cultsig VARCHAR(60),
    sciimpact VARCHAR(50)
);

CREATE TABLE researchprocess (
    signalref VARCHAR(36) PRIMARY KEY REFERENCES signals(signalregistry),
    analysisprio TEXT,
    followstat VARCHAR(25),
    peerrevstat VARCHAR(25),
    pubstat VARCHAR(25),
    resprio VARCHAR(30),
    fundstat VARCHAR(30),
    collabstat VARCHAR(35),
    secclass VARCHAR(35),
    discstat VARCHAR(40),
    notesmemo TEXT
);

-- Observatory data
INSERT INTO observatories VALUES
('Observatory-Alpha', 'Clear', 'Good', 0.920, 'New', 165.00, 'Low', 'Quiet', '14:23:45', 12.50, 25.000, 2.50, 1015.0),
('Observatory-Beta', 'Cloudy', 'Poor', 0.450, 'Full', 45.00, 'High', 'Storm', '08:15:30', -5.00, 78.000, 12.00, 998.0),
('Observatory-Gamma', 'Clear', 'Good', 0.780, 'First Quarter', 95.00, 'Low', 'Quiet', '21:40:15', 18.00, 40.000, 5.00, 1010.0);

-- Telescope data
INSERT INTO telescopes VALUES
('T001', 'Observatory-Alpha', 'Operational', 'Current', 1.50, 2.00, 'Good', 90.00, 'Normal', 'Main', 'Available', 'Connected', 45.00, 'Normal'),
('T002', 'Observatory-Beta', 'Degraded', 'Overdue', 5.00, 8.00, 'Poor', 250.00, 'Critical', 'Backup', 'Low', 'Disconnected', 92.00, 'Full'),
('T003', 'Observatory-Gamma', 'Operational', 'Current', 2.50, 3.00, 'Good', 120.00, 'Normal', 'Main', 'Available', 'Limited', 60.00, 'Normal');

-- Signal data
INSERT INTO signals (signalregistry, timemark, telescref, detectinstr, signalclass, sigstrdb, freqmhz, bwhz, centerfreqmhz, freqdrifthzs, doppshifthz, sigdursec, pulsepersec, pulsewidms, modtype, modindex, carrierfreqmhz, phaseshiftdeg, polarmode, polarangledeg, snrratio, noisefloordbm, interflvl, rfistat, atmointerf) VALUES
('SIG001', '2024-03-15 02:30:00+00', 'T001', 'Radio Telescope', 'Narrowband', -45.50, 1420.405, 150.500, 1420.405, 0.050, 50.0, 3600.00, 0.000, 0.000, 'FM', 0.7000, 1420.000, 45.00, 'Linear', 90.0, 25.50, -130.0, 'Low', 'Clean', 'Minimal'),
('SIG002', '2024-03-15 14:00:00+00', 'T001', 'Radio Telescope', 'Broadband', -120.00, 500.000, 5000000.000, 500.000, 2.500, 200.0, 5.00, 0.000, 0.000, 'Unknown', 0.1000, 500.000, 0.00, 'Unknown', 0.0, 5.00, -95.0, 'High', 'Contaminated', 'Severe'),
('SIG003', '2024-04-01 22:15:00+00', 'T002', 'Quantum Detector', 'Modulated', -75.00, 2400.000, 800.000, 2400.000, 0.300, 120.0, 1800.00, 2.000, 50.000, 'AM', 0.5000, 2400.000, 90.00, 'Circular', 45.0, 15.00, -110.0, 'Medium', 'Unknown', 'Moderate'),
('SIG004', '2024-04-10 05:45:00+00', 'T003', 'Optical Telescope', 'Narrowband', -30.00, 1667.000, 50.000, 1667.000, 0.010, 10.0, 7200.00, 1.500, 100.000, 'PM', 0.9000, 1667.000, 180.00, 'Linear', 0.0, 30.00, -120.0, 'None', 'Clean', 'Minimal'),
('SIG005', '2024-05-20 18:30:00+00', 'T001', 'Radio Telescope', 'Pulsed', -90.00, 800.000, 25000.000, 800.000, 1.000, -100.0, 600.00, 5.000, 20.000, 'QAM', 0.4000, 800.000, 60.00, 'Elliptical', 30.0, 12.00, -105.0, 'Medium', 'Unknown', 'Moderate'),
('SIG006', '2024-06-05 10:00:00+00', 'T002', 'Infrared Array', 'Continuous', -55.00, 5000.000, 2000.000, 5000.000, 0.150, 80.0, 2400.00, 0.000, 0.000, 'FM', 0.6000, 5000.000, 120.00, 'Linear', 60.0, 20.00, -115.0, 'Low', 'Clean', 'Minimal'),
('SIG007', '2024-07-12 03:20:00+00', 'T003', 'Radio Telescope', 'Broadband', -150.00, 300.000, 10000000.000, 300.000, 5.000, -500.0, 2.00, 0.000, 0.000, 'Unknown', 0.0500, 300.000, 0.00, 'Unknown', 0.0, 8.00, -140.0, 'High', 'Contaminated', 'Severe'),
('SIG008', '2024-08-01 20:10:00+00', 'T001', 'Quantum Detector', 'Narrowband', -40.00, 1500.000, 100.000, 1500.000, 0.080, 30.0, 5000.00, 3.000, 75.000, 'AM', 0.8000, 1500.000, 135.00, 'Circular', 70.0, 18.00, -100.0, 'Low', 'Clean', 'Minimal');

-- Signal probabilities
INSERT INTO signalprobabilities VALUES
('SIG001', 0.0200, 0.9100, 0.1500, 0.9500, 7.2, 0.8500, 0.0500, 0.1200, 0.9),
('SIG002', 0.8500, 0.2000, 0.9000, -0.3000, 0.3, 0.1000, 0.0000, 0.8800, 0.1),
('SIG003', 0.1500, 0.5500, 0.5000, 0.4000, 3.5, 0.4500, 0.3000, 0.4000, 0.5),
('SIG004', 0.0100, 0.9500, 0.1000, 0.9800, 8.5, 0.9200, 0.0100, 0.0500, 0.9),
('SIG005', 0.3500, 0.6000, 0.4500, 0.2000, 2.0, 0.3000, 0.5000, 0.5500, 0.3),
('SIG006', 0.1000, 0.7000, 0.3500, 0.7000, 4.0, 0.6000, 0.2000, 0.2500, 0.7),
('SIG007', 0.5000, 0.3000, 0.8000, -0.1000, 1.0, 0.1500, 0.7000, 0.7000, 0.1),
('SIG008', 0.0500, 0.8800, 0.2000, 0.8500, 6.0, 0.7500, 0.1000, 0.1800, 0.8);

-- Signal dynamics (partial)
INSERT INTO signaldynamics VALUES
('SIG001', 'High', 'Regular', 'Static', 'Stable', 'Moderate', 'Stable', 'Stable', 'Stable', 'Consistent', 'High', 'Low', 'Minimal'),
('SIG003', 'Medium', 'Sporadic', 'Dynamic', 'Variable', 'Low', 'Unstable', 'Variable', 'Variable', 'Inconsistent', 'Medium', 'Moderate', 'Significant'),
('SIG004', 'High', 'Regular', 'Static', 'Stable', 'Moderate', 'Stable', 'Stable', 'Stable', 'Consistent', 'High', 'Low', 'Minimal'),
('SIG006', 'Medium', 'None', 'Static', 'Stable', 'High', 'Stable', 'Stable', 'Stable', 'Consistent', 'High', 'Low', 'Minimal'),
('SIG008', 'High', 'Regular', 'Static', 'Stable', 'Moderate', 'Stable', 'Stable', 'Stable', 'Consistent', 'High', 'Low', 'Minimal');

-- Signal classification (partial)
INSERT INTO signalclassification VALUES
('SIG001', 'Candidate', 'Structured', 15, 120.500, 4.500, 0.55, 1.200, 88.50),
('SIG004', 'Candidate', 'Periodic', 50, 60.000, 6.000, 0.65, 1.800, 95.00),
('SIG008', 'Candidate', 'Structured', 25, 90.000, 5.200, 0.48, 1.500, 91.00);

-- Signal decoding (partial)
INSERT INTO signaldecoding VALUES
('SIG001', 'Binary', 3.500, 'High', 92.00, 'Wavelet', 'Completed', 45, 120.50, 'High', 'Comprehensive', 'Verified', 'Confirmed'),
('SIG004', 'Complex', 5.200, 'High', 96.50, 'Neural Network', 'Completed', 120, 340.00, 'Extreme', 'Comprehensive', 'Verified', 'Confirmed');

-- Observational conditions
INSERT INTO observationalconditions VALUES
('SIG001', '02:30:00', '2024-03-15', 8.50),
('SIG002', '14:00:00', '2024-03-15', 0.50),
('SIG003', '22:15:00', '2024-04-01', 4.00),
('SIG004', '05:45:00', '2024-04-10', 12.00),
('SIG005', '18:30:00', '2024-05-20', 2.00),
('SIG006', '10:00:00', '2024-06-05', 6.50),
('SIG007', '03:20:00', '2024-07-12', 0.25),
('SIG008', '20:10:00', '2024-08-01', 10.00);

-- Source properties (partial)
INSERT INTO sourceproperties VALUES
('SIG001', 180.5000, 45.2000, 12000.00, 120.50, 35.20, 'Star', 'Dwarf', 5.50, 5500, 0.950, 4.500, 0.015, 25.50, -15.30),
('SIG004', 210.8000, -30.5000, 450.00, 280.30, -15.80, 'Star', 'Main Sequence', 8.20, 6200, 1.100, 3.200, 0.020, 12.30, 22.70);

-- Signal advanced phenomena (partial)
INSERT INTO signaladvancedphenomena VALUES
('SIG001', 'Minimal', 'None', 'Significant', 'Strong', 'Complex', 'Possible', 'High', 'Major'),
('SIG004', 'Minimal', 'Weak', 'Observed', 'Strong', 'Complex', 'Identified', 'High', 'Major'),
('SIG008', 'Moderate', 'None', 'Significant', 'Strong', 'Simple', 'Possible', 'Low', 'Moderate');

-- Research process (partial)
INSERT INTO researchprocess VALUES
('SIG001', 'Urgent', 'Scheduled', 'In Progress', 'Draft', 'High', 'Funded', 'International', 'Classified', 'Partial', 'Priority signal under active investigation by multiple teams.'),
('SIG004', 'Urgent', 'Required', 'Pending', 'Draft', 'High', 'Pending', 'Team', 'Restricted', 'None', 'Strong candidate requiring independent verification.'),
('SIG006', 'Medium', 'Completed', 'Completed', 'Submitted', 'Medium', 'Unfunded', 'Solo', 'Public', 'Full', 'Moderate interest signal with complete analysis.');
