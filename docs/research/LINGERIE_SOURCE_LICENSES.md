# Lingerie sources: what each licence allows here

This repository is MIT. A source's files may be kept here only under a licence that lets
an MIT project redistribute them; everything else is described, cited, or run as an
external tool, never copied in. `tools/data/verify_lingerie_sources.py` enforces the first
two columns.

| Licence | Files kept here | Code reused | Obligation | Sources |
| --- | --- | --- | --- | --- |
| MIT | yes | yes | keep the copyright and licence notice with the copy | FreeSewing Uma, GarmentCode |
| Apache-2.0 | yes | yes | keep the licence beside the copy; state changes (none: copies are byte-for-byte) | BraCupPattern |
| Public release (U.S. Government) | yes | n/a | cite | ANSUR II (existing, `assets/anatomy/`) |
| GPL-3.0 | **no** | **no** | would bind this repository to GPL: methods are described in our own words only | GarmentMeasurements, Seamly2D |
| Research-only / gated (`license: other`) | **no** | **no** | not requested, not downloaded | T2P |
| Paid standards (ISO, ASTM) | **no** | n/a | definitions may be followed; the text is never copied | ISO/DIS 8559-6, ASTM D4964, ASTM D2594 |
| Not verified | **no** | **no** | decide after the licence is read | GarmentCodeData v2 (ETH page rate-limited 2026-10-24) |

Attribution lines to carry wherever a derived figure is shown are in each record's
`attribution` field, and in the `provenance` block of every normalized JSON.

Commercial use: MIT and Apache-2.0 allow it. Nothing in the gated, GPL or paid rows is used
by the generator, so none of their terms reach a garment this repository produces.
