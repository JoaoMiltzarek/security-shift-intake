# Vendored handwriting fonts

This directory contains five font files used only to render synthetic occurrence sheets. Every
font is distributed under the SIL Open Font License 1.1 and has its own adjacent `*.OFL.txt`
license copy.

[`FONTS.md`](FONTS.md) records the upstream project, attribution, committed SHA-256, and local
license for every font. [`../../THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) explains
how these licenses relate to the project's separate PolyForm terms.

Tests verify that the bundle is present, each font has its matching license file, recorded hashes
match the committed bytes, and the PT-BR characters used by the generator render as real glyphs.
A new or replaced font requires all of those checks and an updated notice in the same commit.

The synthetic renderer can fall back to Pillow's default font in a partial developer checkout,
but such output is not eligible for the authenticated release corpus. Font-rendered handwriting
is also easier and less varied than human cursive; synthetic OCR results are not a claim of
real-handwriting accuracy.
