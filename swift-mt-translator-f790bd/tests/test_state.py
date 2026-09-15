
import subprocess
import os
import json

import pytest
from lxml import etree

NS = {
    'bah': 'urn:iso:std:iso:20022:tech:xsd:head.001.001.03',
    'pacs': 'urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08',
}


def run_translator(input_file, output_file):
    """Run the translator and return parsed XML tree."""
    assert os.path.exists('/app/mt103_to_pacs008.py'), \
        "Translator not found at /app/mt103_to_pacs008.py"
    result = subprocess.run(
        ['python3', '/app/mt103_to_pacs008.py', input_file, output_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"Translator failed with exit code {result.returncode}: {result.stderr}"
    assert os.path.exists(output_file), f"Output file not created: {output_file}"
    return etree.parse(output_file)


def xtext(tree, xpath):
    """Extract text from first XPath match."""
    results = tree.xpath(xpath, namespaces=NS)
    if not results:
        return None
    if isinstance(results[0], str):
        return results[0]
    return results[0].text if results[0].text else None


# ---------------------------------------------------------------------------
# Test Suite 0: xmllint well-formedness and namespace validation
# ---------------------------------------------------------------------------
class TestXmlToolValidation:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.outputs = []
        for name in ['msg_basic.mt103', 'msg_stp_fx.mt103', 'msg_full_chain.mt103']:
            out = str(tmp_path / f'{name}.xml')
            run_translator(f'/app/input/{name}', out)
            self.outputs.append((name, out))

    def test_xmllint_well_formed(self):
        """All outputs must pass xmllint --noout well-formedness check."""
        for name, out in self.outputs:
            result = subprocess.run(
                ['xmllint', '--noout', out],
                capture_output=True, text=True
            )
            assert result.returncode == 0, \
                f"[{name}] xmllint well-formedness failed: {result.stderr}"

    def test_xmllint_bizmsg_root(self):
        """Verify BizMsg root element is accessible via xmllint XPath."""
        for name, out in self.outputs:
            result = subprocess.run(
                ['xmllint', '--xpath',
                 "local-name(/*)",
                 out],
                capture_output=True, text=True
            )
            assert result.returncode == 0, \
                f"[{name}] xmllint xpath failed: {result.stderr}"
            assert 'BizMsg' in result.stdout, \
                f"[{name}] Root element is not BizMsg: {result.stdout}"

    def test_xmllint_namespace_bah(self):
        """Verify BAH namespace is declared and AppHdr exists."""
        for name, out in self.outputs:
            result = subprocess.run(
                ['xmllint', '--xpath',
                 "string(//*[local-name()='AppHdr']/*[local-name()='BizSvc'])",
                 out],
                capture_output=True, text=True
            )
            assert 'swift.cbprplus.02' in result.stdout, \
                f"[{name}] Could not extract BizSvc via xmllint: {result.stdout}"

    def test_xmllint_namespace_pacs(self):
        """Verify pacs namespace is declared and Document exists."""
        for name, out in self.outputs:
            result = subprocess.run(
                ['xmllint', '--xpath',
                 "string(//*[local-name()='GrpHdr']/*[local-name()='MsgId'])",
                 out],
                capture_output=True, text=True
            )
            assert result.returncode == 0, \
                f"[{name}] Could not extract MsgId via xmllint: {result.stderr}"
            assert len(result.stdout.strip()) > 0, \
                f"[{name}] MsgId empty via xmllint"


# ---------------------------------------------------------------------------
# Test Suite 1: Basic MT103 (SHA charges, IBAN accounts, no intermediaries)
# ---------------------------------------------------------------------------
class TestBasicMessage:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.out = str(tmp_path / 'basic.xml')
        self.tree = run_translator('/app/input/msg_basic.mt103', self.out)

    def test_sender_bic(self):
        assert xtext(self.tree,
            '//bah:AppHdr/bah:Fr/bah:FIId/bah:FinInstnId/bah:BICFI/text()') == 'BANKBEBBXXX'

    def test_receiver_bic(self):
        assert xtext(self.tree,
            '//bah:AppHdr/bah:To/bah:FIId/bah:FinInstnId/bah:BICFI/text()') == 'BANKDEFFXXX'

    def test_biz_msg_idr(self):
        assert xtext(self.tree, '//bah:AppHdr/bah:BizMsgIdr/text()') == 'BASIC001'

    def test_msg_def_idr(self):
        assert xtext(self.tree, '//bah:AppHdr/bah:MsgDefIdr/text()') == 'pacs.008.001.08'

    def test_biz_svc(self):
        assert xtext(self.tree, '//bah:AppHdr/bah:BizSvc/text()') == 'swift.cbprplus.02'

    def test_priority_high(self):
        assert xtext(self.tree, '//bah:AppHdr/bah:Prty/text()') == 'HIGH'

    def test_msg_id(self):
        assert xtext(self.tree, '//pacs:GrpHdr/pacs:MsgId/text()') == 'REF20230315001'

    def test_nb_of_txs(self):
        assert xtext(self.tree, '//pacs:GrpHdr/pacs:NbOfTxs/text()') == '1'

    def test_sttlm_mtd_inda(self):
        assert xtext(self.tree, '//pacs:SttlmInf/pacs:SttlmMtd/text()') == 'INDA'

    def test_tx_id(self):
        assert xtext(self.tree, '//pacs:PmtId/pacs:TxId/text()') == 'REF20230315001'

    def test_uetr(self):
        assert xtext(self.tree, '//pacs:PmtId/pacs:UETR/text()') == \
            'c3d4e5f6-a1b2-3c4d-e5f6-a1b2c3d4e5f6'

    def test_e2e_id(self):
        assert xtext(self.tree, '//pacs:PmtId/pacs:EndToEndId/text()') == 'NOTPROVIDED'

    def test_sttlm_amt_value(self):
        elems = self.tree.xpath('//pacs:CdtTrfTxInf/pacs:IntrBkSttlmAmt', namespaces=NS)
        assert len(elems) >= 1
        assert float(elems[0].text) == pytest.approx(100000.50)

    def test_sttlm_amt_ccy(self):
        elems = self.tree.xpath('//pacs:CdtTrfTxInf/pacs:IntrBkSttlmAmt', namespaces=NS)
        assert elems[0].get('Ccy') == 'EUR'

    def test_sttlm_dt(self):
        assert xtext(self.tree, '//pacs:CdtTrfTxInf/pacs:IntrBkSttlmDt/text()') == '2023-03-15'

    def test_chrg_br_shar(self):
        assert xtext(self.tree, '//pacs:ChrgBr/text()') == 'SHAR'

    def test_dbtr_nm(self):
        assert xtext(self.tree, '//pacs:Dbtr/pacs:Nm/text()') == 'JOHN SMITH'

    def test_dbtr_acct_iban(self):
        assert xtext(self.tree, '//pacs:DbtrAcct/pacs:Id/pacs:IBAN/text()') == \
            'BE62510007547061'

    def test_cdtr_nm(self):
        assert xtext(self.tree, '//pacs:Cdtr/pacs:Nm/text()') == 'HANS MUELLER'

    def test_cdtr_acct_iban(self):
        assert xtext(self.tree, '//pacs:CdtrAcct/pacs:Id/pacs:IBAN/text()') == \
            'DE89370400440532013000'

    def test_rmt_ustrd(self):
        assert xtext(self.tree, '//pacs:RmtInf/pacs:Ustrd/text()') == \
            'INVOICE 2023-001 PAYMENT'


# ---------------------------------------------------------------------------
# Test Suite 2: STP + FX + structured parties + charges + BIC normalization
# ---------------------------------------------------------------------------
class TestStpFxMessage:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.out = str(tmp_path / 'stp.xml')
        self.tree = run_translator('/app/input/msg_stp_fx.mt103', self.out)

    def test_sender_bic(self):
        assert xtext(self.tree,
            '//bah:AppHdr/bah:Fr/bah:FIId/bah:FinInstnId/bah:BICFI/text()') == 'CITIUS33XXX'

    def test_priority_norm(self):
        assert xtext(self.tree, '//bah:AppHdr/bah:Prty/text()') == 'NORM'

    def test_sttlm_mtd_inga(self):
        """53A present without 54A => INGA."""
        assert xtext(self.tree, '//pacs:SttlmInf/pacs:SttlmMtd/text()') == 'INGA'

    def test_svc_lvl_g004(self):
        """Block 3 {119:STP} => SvcLvl/Cd = G004."""
        assert xtext(self.tree, '//pacs:PmtTpInf/pacs:SvcLvl/pacs:Cd/text()') == 'G004'

    def test_sttlm_amt_usd(self):
        elems = self.tree.xpath('//pacs:CdtTrfTxInf/pacs:IntrBkSttlmAmt', namespaces=NS)
        assert elems[0].get('Ccy') == 'USD'
        assert float(elems[0].text) == pytest.approx(250000.00)

    def test_instd_amt_eur(self):
        """Field 33B => InstdAmt."""
        elems = self.tree.xpath('//pacs:InstdAmt', namespaces=NS)
        assert len(elems) >= 1
        assert elems[0].get('Ccy') == 'EUR'
        assert float(elems[0].text) == pytest.approx(230000.00)

    def test_xchg_rate(self):
        rate = xtext(self.tree, '//pacs:XchgRate/text()')
        assert float(rate) == pytest.approx(1.0869)

    def test_dbtr_nm_structured(self):
        """50F line 1/ => Dbtr/Nm."""
        assert xtext(self.tree, '//pacs:Dbtr/pacs:Nm/text()') == 'ACME CORPORATION'

    def test_dbtr_country(self):
        """50F line 3/ country."""
        assert xtext(self.tree, '//pacs:Dbtr/pacs:PstlAdr/pacs:Ctry/text()') == 'US'

    def test_dbtr_town(self):
        """50F line 3/ town name."""
        assert xtext(self.tree, '//pacs:Dbtr/pacs:PstlAdr/pacs:TwnNm/text()') == 'NEW YORK'

    def test_dbtr_acct_non_iban(self):
        """Numeric-only account => Othr/Id (not IBAN)."""
        val = xtext(self.tree, '//pacs:DbtrAcct/pacs:Id/pacs:Othr/pacs:Id/text()')
        assert val == '1234567890123456'

    def test_dbtr_agt_normalized(self):
        """8-char BIC CITIUS33 must be normalized to CITIUS33XXX."""
        bic = xtext(self.tree, '//pacs:DbtrAgt/pacs:FinInstnId/pacs:BICFI/text()')
        assert bic == 'CITIUS33XXX'

    def test_cdtr_nm_structured(self):
        """59F line 1/ => Cdtr/Nm."""
        assert xtext(self.tree, '//pacs:Cdtr/pacs:Nm/text()') == 'SWISS TRADING AG'

    def test_cdtr_country(self):
        assert xtext(self.tree, '//pacs:Cdtr/pacs:PstlAdr/pacs:Ctry/text()') == 'CH'

    def test_cdtr_acct_iban(self):
        assert xtext(self.tree, '//pacs:CdtrAcct/pacs:Id/pacs:IBAN/text()') == \
            'CH9300762011623852957'

    def test_charges_amt(self):
        """71F => ChrgsInf."""
        elems = self.tree.xpath('//pacs:ChrgsInf/pacs:Amt', namespaces=NS)
        assert len(elems) >= 1
        assert elems[0].get('Ccy') == 'USD'
        assert float(elems[0].text) == pytest.approx(25.00)

    def test_inv_cinv_code(self):
        """/INV/ code word => structured remittance CINV."""
        codes = self.tree.xpath(
            '//pacs:RmtInf/pacs:Strd/pacs:RfrdDocInf/pacs:Tp/pacs:CdOrPrtry/pacs:Cd/text()',
            namespaces=NS)
        assert 'CINV' in codes

    def test_inv_ref_number(self):
        ref = xtext(self.tree,
            '//pacs:RmtInf/pacs:Strd/pacs:RfrdDocInf/pacs:Nb/text()')
        assert ref == 'INV-2023-0315'

    def test_sdva_instruction(self):
        """23E:SDVA => InstrForCdtrAgt/Cd."""
        codes = self.tree.xpath('//pacs:InstrForCdtrAgt/pacs:Cd/text()', namespaces=NS)
        assert 'SDVA' in codes

    def test_instg_rmbrsmt_agt(self):
        """53A BIC => InstgRmbrsmntAgt."""
        bic = xtext(self.tree,
            '//pacs:InstgRmbrsmntAgt/pacs:FinInstnId/pacs:BICFI/text()')
        assert bic == 'CHASUS33XXX'

    def test_cdtr_agt(self):
        """57A => CdtrAgt."""
        bic = xtext(self.tree, '//pacs:CdtrAgt/pacs:FinInstnId/pacs:BICFI/text()')
        assert bic == 'BOFAUS3NXXX'


# ---------------------------------------------------------------------------
# Test Suite 3: Full agent chain, reimbursement, regulatory, field 72/77B
# ---------------------------------------------------------------------------
class TestFullChainMessage:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.out = str(tmp_path / 'full.xml')
        self.tree = run_translator('/app/input/msg_full_chain.mt103', self.out)

    def test_sttlm_mtd_cove(self):
        """53A+54A present => COVE."""
        assert xtext(self.tree, '//pacs:SttlmInf/pacs:SttlmMtd/text()') == 'COVE'

    def test_instg_rmbrsmt_agt_bic(self):
        """53A BIC => InstgRmbrsmntAgt."""
        assert xtext(self.tree,
            '//pacs:InstgRmbrsmntAgt/pacs:FinInstnId/pacs:BICFI/text()') == 'BARCGB22XXX'

    def test_instg_rmbrsmt_agt_acct(self):
        """53A account => InstgRmbrsmntAgtAcct."""
        assert xtext(self.tree,
            '//pacs:InstgRmbrsmntAgtAcct/pacs:Id/pacs:Othr/pacs:Id/text()') == 'GB0001234567'

    def test_instd_rmbrsmt_agt_bic(self):
        """54A BIC => InstdRmbrsmntAgt."""
        assert xtext(self.tree,
            '//pacs:InstdRmbrsmntAgt/pacs:FinInstnId/pacs:BICFI/text()') == 'CHASUS33XXX'

    def test_instd_rmbrsmt_agt_acct(self):
        """54A account => InstdRmbrsmntAgtAcct."""
        assert xtext(self.tree,
            '//pacs:InstdRmbrsmntAgtAcct/pacs:Id/pacs:Othr/pacs:Id/text()') == '123456789'

    def test_lcl_instrm(self):
        """26T => LclInstrm/Cd."""
        assert xtext(self.tree, '//pacs:PmtTpInf/pacs:LclInstrm/pacs:Cd/text()') == 'K90'

    def test_ctgy_purp_cort(self):
        """23E:CORT => CtgyPurp/Cd."""
        assert xtext(self.tree, '//pacs:PmtTpInf/pacs:CtgyPurp/pacs:Cd/text()') == 'CORT'

    def test_time_indication_dbt(self):
        """13C /CLSTIME/ => SttlmTmIndctn/DbtDtTm."""
        val = xtext(self.tree, '//pacs:SttlmTmIndctn/pacs:DbtDtTm/text()')
        assert val is not None
        assert '09:15' in val
        assert '+01:00' in val

    def test_chrg_br_debt(self):
        """71A:OUR => ChrgBr = DEBT."""
        assert xtext(self.tree, '//pacs:ChrgBr/text()') == 'DEBT'

    def test_dbtr_anybic(self):
        """50A BIC => Dbtr/Id/OrgId/AnyBIC."""
        assert xtext(self.tree,
            '//pacs:Dbtr/pacs:Id/pacs:OrgId/pacs:AnyBIC/text()') == 'NWBKGB2LXXX'

    def test_dbtr_acct_iban(self):
        """50A /account (IBAN) => DbtrAcct/Id/IBAN."""
        assert xtext(self.tree, '//pacs:DbtrAcct/pacs:Id/pacs:IBAN/text()') == \
            'GB29NWBK60161331926819'

    def test_dbtr_agt_bic(self):
        """52A => DbtrAgt."""
        assert xtext(self.tree,
            '//pacs:DbtrAgt/pacs:FinInstnId/pacs:BICFI/text()') == 'NWBKGB2LXXX'

    def test_cdtr_agt_bic(self):
        """57A BIC => CdtrAgt."""
        assert xtext(self.tree,
            '//pacs:CdtrAgt/pacs:FinInstnId/pacs:BICFI/text()') == 'BOFAUS3NXXX'

    def test_cdtr_agt_acct(self):
        """57A /account => CdtrAgtAcct."""
        assert xtext(self.tree,
            '//pacs:CdtrAgtAcct/pacs:Id/pacs:Othr/pacs:Id/text()') == '9876543210'

    def test_intrmy_agt1(self):
        """56A => IntrmyAgt1."""
        assert xtext(self.tree,
            '//pacs:IntrmyAgt1/pacs:FinInstnId/pacs:BICFI/text()') == 'IRVTUS3NXXX'

    def test_prvs_instg_agt(self):
        """72 /INS/ => PrvsInstgAgt1."""
        assert xtext(self.tree,
            '//pacs:PrvsInstgAgt1/pacs:FinInstnId/pacs:BICFI/text()') == 'ABORAXAAXXX'

    def test_instr_cdtr_agt_bnf(self):
        """72 /BNF/ => InstrForCdtrAgt/InstrInf."""
        vals = self.tree.xpath('//pacs:InstrForCdtrAgt/pacs:InstrInf/text()', namespaces=NS)
        assert any('ATTN ACCOUNTS PAYABLE' in v for v in vals)

    def test_instr_nxt_agt(self):
        """72 // continuation => InstrForNxtAgt/InstrInf."""
        vals = self.tree.xpath('//pacs:InstrForNxtAgt/pacs:InstrInf/text()', namespaces=NS)
        assert any('CONTACT TREASURY DEPT' in v for v in vals)

    def test_rgltry_orderres(self):
        """77B /ORDERRES/ => RgltryRptg with DbtCdtRptgInd=DEBT."""
        rptg = self.tree.xpath(
            '//pacs:RgltryRptg[pacs:DbtCdtRptgInd="DEBT"]', namespaces=NS)
        assert len(rptg) >= 1
        ctry = rptg[0].xpath('pacs:Authrty/pacs:Ctry/text()', namespaces=NS)
        assert ctry[0] == 'GB'

    def test_rgltry_benres(self):
        """77B /BENRES/ => RgltryRptg with DbtCdtRptgInd=CRED."""
        rptg = self.tree.xpath(
            '//pacs:RgltryRptg[pacs:DbtCdtRptgInd="CRED"]', namespaces=NS)
        assert len(rptg) >= 1
        ctry = rptg[0].xpath('pacs:Authrty/pacs:Ctry/text()', namespaces=NS)
        assert ctry[0] == 'US'

    def test_rgltry_orderres_info(self):
        """77B /ORDERRES/ detail info text."""
        rptg = self.tree.xpath(
            '//pacs:RgltryRptg[pacs:DbtCdtRptgInd="DEBT"]', namespaces=NS)
        info = rptg[0].xpath('pacs:Dtls/pacs:Inf/text()', namespaces=NS)
        assert any('LONDON' in i for i in info)

    def test_roc_instr_id(self):
        """70 /ROC/ref => PmtId/InstrId override."""
        instr_id = xtext(self.tree, '//pacs:PmtId/pacs:InstrId/text()')
        assert instr_id == 'PO-2023-1234'

    def test_cdtr_nm(self):
        assert xtext(self.tree, '//pacs:Cdtr/pacs:Nm/text()') == 'GLOBAL IMPORTS LLC'

    def test_cdtr_acct_non_iban(self):
        """Numeric-only account => Othr/Id."""
        val = xtext(self.tree, '//pacs:CdtrAcct/pacs:Id/pacs:Othr/pacs:Id/text()')
        assert val == '33123456789012'

    def test_sttlm_amt_gbp(self):
        elems = self.tree.xpath('//pacs:CdtTrfTxInf/pacs:IntrBkSttlmAmt', namespaces=NS)
        assert elems[0].get('Ccy') == 'GBP'
        assert float(elems[0].text) == pytest.approx(500000.00)

    def test_sttlm_dt(self):
        assert xtext(self.tree,
            '//pacs:CdtTrfTxInf/pacs:IntrBkSttlmDt/text()') == '2023-04-01'


# ---------------------------------------------------------------------------
# Test Suite 4: CBPR+ Compliance (cross-cutting checks on all messages)
# ---------------------------------------------------------------------------
class TestCbprCompliance:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.trees = []
        for name in ['msg_basic.mt103', 'msg_stp_fx.mt103', 'msg_full_chain.mt103']:
            out = str(tmp_path / f'{name}.xml')
            tree = run_translator(f'/app/input/{name}', out)
            self.trees.append((name, tree))

    def test_all_bicfi_11_chars(self):
        """Every BICFI element in every output must be exactly 11 characters."""
        for name, tree in self.trees:
            bics = tree.xpath('//bah:BICFI/text() | //pacs:BICFI/text()',
                              namespaces=NS)
            for bic in bics:
                assert len(bic) == 11, \
                    f"[{name}] BICFI '{bic}' is {len(bic)} chars, expected 11"

    def test_all_anybic_11_chars(self):
        """AnyBIC elements should also be 11 characters for CBPR+."""
        for name, tree in self.trees:
            bics = tree.xpath('//pacs:AnyBIC/text()', namespaces=NS)
            for bic in bics:
                assert len(bic) == 11, \
                    f"[{name}] AnyBIC '{bic}' is {len(bic)} chars, expected 11"

    def test_biz_svc_value(self):
        for name, tree in self.trees:
            val = xtext(tree, '//bah:AppHdr/bah:BizSvc/text()')
            assert val == 'swift.cbprplus.02', f"[{name}] BizSvc = '{val}'"

    def test_msg_def_idr_value(self):
        for name, tree in self.trees:
            val = xtext(tree, '//bah:AppHdr/bah:MsgDefIdr/text()')
            assert val == 'pacs.008.001.08', f"[{name}] MsgDefIdr = '{val}'"

    def test_nb_of_txs_one(self):
        for name, tree in self.trees:
            val = xtext(tree, '//pacs:GrpHdr/pacs:NbOfTxs/text()')
            assert val == '1', f"[{name}] NbOfTxs = '{val}'"

    def test_uetr_present(self):
        for name, tree in self.trees:
            val = xtext(tree, '//pacs:PmtId/pacs:UETR/text()')
            assert val and len(val) > 0, f"[{name}] UETR missing"

    def test_e2e_id_present(self):
        for name, tree in self.trees:
            val = xtext(tree, '//pacs:PmtId/pacs:EndToEndId/text()')
            assert val is not None, f"[{name}] EndToEndId missing"

    def test_well_formed_xml(self):
        """All outputs must be parseable XML."""
        for name, tree in self.trees:
            root = tree.getroot()
            assert root is not None, f"[{name}] Could not parse XML"


# ---------------------------------------------------------------------------
# Test Suite 5: CBPR+ Validation Pipeline (xmlstarlet + jq)
# ---------------------------------------------------------------------------
class TestValidationPipeline:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp_path = tmp_path
        self.outputs = {}
        for name in ['msg_basic.mt103', 'msg_stp_fx.mt103', 'msg_full_chain.mt103']:
            out = str(tmp_path / f'{name}.xml')
            run_translator(f'/app/input/{name}', out)
            self.outputs[name] = out

    def test_validator_exists(self):
        """validate_cbpr.sh must exist and be executable."""
        assert os.path.exists('/app/validate_cbpr.sh'), \
            "validate_cbpr.sh not found at /app/validate_cbpr.sh"
        assert os.access('/app/validate_cbpr.sh', os.X_OK), \
            "validate_cbpr.sh is not executable"

    def test_validator_json_structure(self):
        """Validator output must be valid JSON with required fields."""
        result = subprocess.run(
            ['/app/validate_cbpr.sh', self.outputs['msg_basic.mt103']],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        assert 'valid' in data, "JSON output missing 'valid' key"
        assert 'checks' in data, "JSON output missing 'checks' key"
        assert isinstance(data['checks'], list), "'checks' must be a list"
        assert len(data['checks']) >= 4, "Expected at least 4 checks"
        for check in data['checks']:
            assert 'name' in check, f"Check missing 'name': {check}"
            assert 'pass' in check, f"Check missing 'pass': {check}"
            assert 'value' in check, f"Check missing 'value': {check}"

    def test_validator_passes_valid_translations(self):
        """Validator exits 0 and reports valid=true for correct translations."""
        for name, out in self.outputs.items():
            result = subprocess.run(
                ['/app/validate_cbpr.sh', out],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, \
                f"[{name}] Validator failed: {result.stderr}\n{result.stdout}"
            data = json.loads(result.stdout)
            assert data['valid'] is True, f"[{name}] valid=false: {data}"

    def test_validator_uses_xmlstarlet(self):
        """Validator script must use xmlstarlet for XPath extraction."""
        with open('/app/validate_cbpr.sh') as f:
            content = f.read()
        assert 'xmlstarlet' in content, \
            "validate_cbpr.sh must use xmlstarlet for XPath extraction"

    def test_validator_uses_jq(self):
        """Validator script must use jq for JSON assembly."""
        with open('/app/validate_cbpr.sh') as f:
            content = f.read()
        assert 'jq' in content, \
            "validate_cbpr.sh must use jq for JSON output assembly"

    def test_validator_checks_bizsvc(self):
        """Validator checks must include a BizSvc verification."""
        result = subprocess.run(
            ['/app/validate_cbpr.sh', self.outputs['msg_basic.mt103']],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        names = [c['name'].lower() for c in data['checks']]
        assert any('bizsvc' in n or 'biz_svc' in n for n in names), \
            f"No BizSvc check found in: {names}"

    def test_validator_checks_bic_length(self):
        """Validator checks must include BIC length verification."""
        result = subprocess.run(
            ['/app/validate_cbpr.sh', self.outputs['msg_basic.mt103']],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        names = [c['name'].lower() for c in data['checks']]
        assert any('bic' in n for n in names), \
            f"No BIC length check found in: {names}"

    def test_validator_rejects_non_cbpr_xml(self):
        """Validator must exit non-zero for XML lacking CBPR+ elements."""
        bad_path = str(self.tmp_path / 'bad.xml')
        with open(bad_path, 'w') as f:
            f.write('<root><invalid/></root>')
        result = subprocess.run(
            ['/app/validate_cbpr.sh', bad_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode != 0, \
            "Validator should exit non-zero for non-CBPR+ XML"
        data = json.loads(result.stdout)
        assert data['valid'] is False, \
            "Validator should report valid=false for non-CBPR+ XML"
