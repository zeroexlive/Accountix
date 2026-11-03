"""Hand-crafted statement-file fixtures for Sprint 18 (ADR-044).

Minimal but valid per format. The money always adds up where the
fixture is used through the create-from-file flow:

- CAMT_CLEAN: opening 100 + 1100 - 300 = closing 900.
- OFX1: opening (not in file) 1000 + 1100 - 300 - 50.25 = LEDGERBAL
  1749.75.
- OFX2: 2500.50 - 125 = LEDGERBAL 2375.50.
"""

CAMT_CLEAN = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
  <BkToCstmrStmt>
    <GrpHdr><MsgId>MSG-1</MsgId><CreDtTm>2026-07-01T09:00:00</CreDtTm></GrpHdr>
    <Stmt>
      <Id>STMT-2026-06</Id>
      <FrToDt><FrDt>2026-06-01</FrDt><ToDt>2026-06-30</ToDt></FrToDt>
      <Acct><Id><IBAN>IR062345678901234567890001</IBAN></Id></Acct>
      <Bal>
        <Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>
        <Amt Ccy="IRR">100.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt><Dt>2026-05-31</Dt></Dt>
      </Bal>
      <Bal>
        <Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>
        <Amt Ccy="IRR">900.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt><Dt>2026-06-30</Dt></Dt>
      </Bal>
      <Ntry>
        <Amt Ccy="IRR">1100.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2026-06-01</Dt></BookgDt>
        <AcctSvcrRef>C-1001</AcctSvcrRef>
        <NtryDtls><TxDtls>
          <RmtInf><Ustrd>Customer transfer</Ustrd></RmtInf>
        </TxDtls></NtryDtls>
      </Ntry>
      <Ntry>
        <Amt Ccy="IRR">300.00</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
        <BookgDt><Dt>2026-06-02</Dt></BookgDt>
        <AddtlNtryInf>Supplier payment</AddtlNtryInf>
        <NtryDtls><TxDtls>
          <Refs><EndToEndId>E2E-2002</EndToEndId></Refs>
        </TxDtls></NtryDtls>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>
"""

# Entry 3 has an unparseable amount: it must be reported at index 3
# while entries 1-2 still parse/import. No <FrToDt>: the period
# falls back to the entry dates (2026-06-01 .. 2026-06-15).
CAMT_BROKEN = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>STMT-B</Id>
      <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt>0.00</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>
      <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt>800.00</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>
      <Ntry>
        <Amt>1100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2026-06-01</Dt></BookgDt>
        <AcctSvcrRef>REF-A</AcctSvcrRef>
        <NtryDtls><TxDtls><RmtInf><Ustrd>Customer transfer inbound</Ustrd></RmtInf></TxDtls></NtryDtls>
      </Ntry>
      <Ntry>
        <Amt>300.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
        <BookgDt><Dt>2026-06-02</Dt></BookgDt>
        <AddtlNtryInf>Supplier payment by transfer</AddtlNtryInf>
        <NtryDtls><TxDtls><Refs><AcctSvcrRef>REF-B</AcctSvcrRef></Refs></TxDtls></NtryDtls>
      </Ntry>
      <Ntry>
        <Amt>not-a-number</Amt><CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2026-06-15</Dt></BookgDt>
        <AcctSvcrRef>REF-C</AcctSvcrRef>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>
"""

# No XML namespace at all: local-name matching must still parse it.
CAMT_PLAIN = """<Document>
  <BkToCstmrStmt><Stmt>
    <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt>0.00</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>
    <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt>50.00</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>
    <Ntry><Amt>50.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-06-05</Dt></BookgDt><AcctSvcrRef>P-1</AcctSvcrRef><NtryDtls><TxDtls><RmtInf><Ustrd>Plain transfer</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
  </Stmt></BkToCstmrStmt>
</Document>
"""

CAMT_TWO_STMTS = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
  <BkToCstmrStmt>
    <Stmt><Id>S-1</Id></Stmt>
    <Stmt><Id>S-2</Id></Stmt>
  </BkToCstmrStmt>
</Document>
"""

OFX1 = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<DTSERVER>20260701120000[0:GMT]
<LANGUAGE>ENG
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<STMTRS>
<CURDEF>IRR
<BANKACCTFROM>
<BANKID>0123
<ACCTID>987654
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260601000000[0:GMT]
<DTEND>20260630000000[0:GMT]
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260601103000[3:IRST]
<TRNAMT>1100.00
<FITID>202606010001
<NAME>Customer Transfer
<MEMO>Invoice 44
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260602
<TRNAMT>-300.00
<FITID>202606020001
<NAME>Supplier Payment
</STMTTRN>
<STMTTRN>
<TRNTYPE>FEE
<DTPOSTED>20260615120000
<TRNAMT>-50.25
<FITID>202606150001
<NAME>Bank
<MEMO>Monthly fee
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>1749.75
<DTASOF>20260630000000[0:GMT]
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""

# Same file with the second transaction's amount broken: only that
# transaction is rejected, at index 2.
OFX_BROKEN = OFX1.replace("<TRNAMT>-300.00", "<TRNAMT>not-a-number")

OFX2 = """<?xml version="1.0" encoding="UTF-8"?>
<?OFX OFXHEADER="200" VERSION="220" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>
<OFX>
  <SIGNONMSGSRSV1>
    <SONRS>
      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
      <DTSERVER>20260701120000[0:GMT]</DTSERVER>
      <LANGUAGE>ENG</LANGUAGE>
    </SONRS>
  </SIGNONMSGSRSV1>
  <BANKMSGSRSV1>
    <STMTTRNRS>
      <TRNUID>1</TRNUID>
      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
      <STMTRS>
        <CURDEF>IRR</CURDEF>
        <BANKACCTFROM>
          <BANKID>0123</BANKID>
          <ACCTID>987654</ACCTID>
          <ACCTTYPE>CHECKING</ACCTTYPE>
        </BANKACCTFROM>
        <BANKTRANLIST>
          <DTSTART>20260601000000[0:GMT]</DTSTART>
          <DTEND>20260630000000[0:GMT]</DTEND>
          <STMTTRN>
            <TRNTYPE>CREDIT</TRNTYPE>
            <DTPOSTED>20260603101500[3:IRST]</DTPOSTED>
            <TRNAMT>2500.50</TRNAMT>
            <FITID>XML-0001</FITID>
            <NAME>Card Sale</NAME>
            <MEMO>POS terminal</MEMO>
          </STMTTRN>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20260604</DTPOSTED>
            <TRNAMT>-125.00</TRNAMT>
            <FITID>XML-0002</FITID>
            <NAME>Utility Bill</NAME>
          </STMTTRN>
        </BANKTRANLIST>
        <LEDGERBAL>
          <BALAMT>2375.50</BALAMT>
          <DTASOF>20260630000000[0:GMT]</DTASOF>
        </LEDGERBAL>
      </STMTRS>
    </STMTTRNRS>
  </BANKMSGSRSV1>
</OFX>
"""

GARBAGE_HTML = "<html><head><title>Bank</title></head><body>Your statement</body></html>"

# A PNG magic header plus bytes that are not valid UTF-8 anywhere.
GARBAGE_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\x00\x01"
