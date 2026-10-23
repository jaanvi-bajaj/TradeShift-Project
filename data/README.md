# data/

Small reference tables kept in Git. Each row has a source link. Large trade data is not
stored here; it lives in S3 and RDS, and in the release snapshot.

| File | Rows | What it is | Built by |
|---|---|---|---|
| `tariff_events.csv` | 9 | One row per tariff action: who was tariffed, exemptions, rate, announced and effective dates, HS version, Federal Register link, notes | By hand, from the notices linked in each row |
| `tariff_event_products.csv` | ~10,500 | HS codes each event covers (HTS8 and HS6 for Section 301; HS6 for 232 and 201) | `scripts/build_tariff_lines.py` |
| `countries.csv` | ~255 | ISO alpha-2, name, Census Schedule C code, Comtrade M49 code, EU-28 (2018) flag | `scripts/build_reference.py` |

## How the event product lists were checked

The Section 301 lists come from the "informal" annex of each USTR notice (one HTS8 code per
line). Parsed counts against the official counts:

| Event | Parsed HTS8 lines | Official | Distinct HS6 |
|---|---|---|---|
| List 1 (83 FR 28710) | 820 | 818 | 562 |
| List 2 (83 FR 40823) | 280 | 279 | 200 |
| List 3 (83 FR 47974) | 5,743 | 5,745 | 3,050 |
| List 4A (84 FR 43304) | 3,236 | about 3,229 plus partial lines | 1,443 |

The small differences come from codes cited in annex notes. They make no difference at HS6
level, where the detector works.

Section 232 products are the HTS ranges in Proclamations 9705 (steel) and 9704 (aluminium),
expanded to HS6 against the USITC HTS. The Section 201 washer safeguard covers HS 8450.11,
8450.20 and 8450.90 (Proclamation 9694).

## Who counts as "tariffed"

- `tariffed_suppliers`: ISO codes separated by `;`. `ALL` means every country, and `EU` expands to EU-28 as of 2018.
- `exempt_suppliers`: removed from the tariffed set (for example Canada for washers).
- An event can therefore tariff many suppliers at once, which Section 232 needs.
