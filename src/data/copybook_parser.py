"""Parse COBOL copybook layout files into Python record specifications.

This is a minimal parser supporting the subset of COBOL copybook syntax we need:
- Level-numbered fields (01, 05)
- PIC X(n) for character fields
- PIC 9(n) for numeric fields
- Hyphenated field names

It is not a full COBOL parser. Real-world copybook parsers handle REDEFINES,
OCCURS, COMP-3 packed decimal, signed fields, and many other features. The
parser here is sufficient for the prototype and is honest about its scope in
the methodology paper as 'illustrative, not production-grade.'
"""

import re
from dataclasses import dataclass
from pathlib import Path


# Maps COBOL field names to Python attribute names in the Claim schema.
# This is the bridge between the legacy data world and the modern data world.
COBOL_TO_PYTHON_NAME = {
    "CLAIM-ID": "claim_id",
    "FILING-STATE": "filing_state",
    "CLAIM-DATE": "claim_date",
    "WEEKLY-BENEFIT-AMOUNT": "weekly_benefit_amount",
    "EMPLOYER-EIN": "employer_ein",
    "CLAIMANT-SSN": "claimant_ssn",
    "DEVICE-FINGERPRINT": "device_fingerprint",
    "BANK-ROUTING": "bank_routing",
    "BANK-ACCOUNT": "bank_account",
    "FIRST-NAME": "first_name",
    "LAST-NAME": "last_name",
    "DOB": "dob",
    "ADDRESS": "address",
    "IP-ADDRESS": "ip_address",
}


@dataclass
class FieldSpec:
    """Specification for a single field in a fixed-width record."""
    cobol_name: str       # e.g. "CLAIMANT-SSN"
    python_name: str      # e.g. "claimant_ssn"
    offset: int           # byte offset within the record
    length: int           # field width in bytes
    pic_type: str         # "X" for alphanumeric, "9" for numeric


@dataclass
class RecordSpec:
    """Specification for a complete fixed-width record."""
    record_name: str
    fields: list[FieldSpec]
    total_length: int

    def field_by_python_name(self, python_name: str) -> FieldSpec:
        for f in self.fields:
            if f.python_name == python_name:
                return f
        raise KeyError(f"No field named {python_name!r}")


# Regex matching lines like "    05  CLAIMANT-SSN     PIC X(11)."
FIELD_LINE_PATTERN = re.compile(
    r"^\s*(?P<level>\d{2})\s+"
    r"(?P<name>[A-Z][A-Z0-9\-]*)\s+"
    r"PIC\s+(?P<pic>[X9])\((?P<length>\d+)\)\s*\.\s*$"
)

# Regex matching the record header line like "01  CLAIM-RECORD."
RECORD_LINE_PATTERN = re.compile(
    r"^\s*01\s+(?P<name>[A-Z][A-Z0-9\-]*)\s*\.\s*$"
)


def parse_copybook(path: Path) -> RecordSpec:
    """Parse a COBOL copybook file into a RecordSpec."""
    record_name = None
    fields: list[FieldSpec] = []
    offset = 0

    with path.open() as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip()

            if not line.strip():
                continue

            record_match = RECORD_LINE_PATTERN.match(line)
            if record_match:
                record_name = record_match.group("name")
                continue

            field_match = FIELD_LINE_PATTERN.match(line)
            if field_match:
                cobol_name = field_match.group("name")
                length = int(field_match.group("length"))
                pic_type = field_match.group("pic")

                if cobol_name not in COBOL_TO_PYTHON_NAME:
                    raise ValueError(
                        f"Line {line_num}: unknown COBOL field {cobol_name!r}. "
                        f"Add it to COBOL_TO_PYTHON_NAME if intentional."
                    )

                fields.append(FieldSpec(
                    cobol_name=cobol_name,
                    python_name=COBOL_TO_PYTHON_NAME[cobol_name],
                    offset=offset,
                    length=length,
                    pic_type=pic_type,
                ))
                offset += length
                continue

            raise ValueError(
                f"Line {line_num}: could not parse {line!r}. "
                f"Expected 'NN FIELD-NAME PIC X(N).' format."
            )

    if record_name is None:
        raise ValueError("Copybook file missing 01-level record declaration")

    return RecordSpec(
        record_name=record_name,
        fields=fields,
        total_length=offset,
    )


if __name__ == "__main__":
    spec = parse_copybook(Path("src/data/copybook_layout.txt"))
    print(f"Record: {spec.record_name}")
    print(f"Total length: {spec.total_length} bytes")
    print(f"{'COBOL Name':<25} {'Python Name':<25} {'Offset':>7} {'Length':>7} {'Type':>5}")
    for f in spec.fields:
        print(f"{f.cobol_name:<25} {f.python_name:<25} {f.offset:>7} {f.length:>7} {f.pic_type:>5}")