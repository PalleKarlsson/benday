# Offline dictionaries (T-108, phase 2)

`build.py` builds the StarDict dictionaries for Benday's "Download" list
(Settings › Dictionaries): English, Swedish (two Swedish–Swedish ones and a
Swedish–English one), German, French and Spanish, from Wiktionary extracts
on [kaikki.org](https://kaikki.org) (wiktextract JSONL), the Swedish
Wiktionary's own dump and ISOF's Lexin. Design:
`docs/superpowers/specs/2026-10-28-epub-lookup-design.md` › "Offline
dictionaries"; the Swedish sources:
`docs/superpowers/specs/2026-10-28-swedish-dictionary-research.md`.

```bash
tool/dictionaries/build.py                    # all seven; downloads what's missing or changed
tool/dictionaries/build.py --lang sv,lexin-sv # some (keys: en sv sv-en lexin-sv de fr es)
tool/dictionaries/build.py --offline          # the cached dumps as they are
tool/dictionaries/build.py --base-url https://…/releases/download/dictionaries-2026-10  # urls in the index
tool/dictionaries/lookup.py --text build/dictionaries/wiktionary-sv-*/benday-wiktionary-sv.ifo hus gick
python3 -m unittest discover tool/tests       # tests (tiny samples in tool/tests/fixtures/dictionaries/)
```

Python 3.10+, standard library only. Dumps are cached in
`~/.cache/benday-dictionaries/<key>/` (`--cache-dir`; a HEAD request
decides whether a cached dump is still current, partial downloads resume);
output goes to `build/dictionaries/` (`--out`, ignored by git). Never commit
the dumps or the built dictionaries. Nothing is uploaded: where the archives
are hosted is the owner's decision (`--base-url`, default a placeholder).

A run of all seven takes about 4½ minutes on the dev machine once the dumps
(1.5 GB compressed) are cached; the three Swedish ones about a minute
(sv 45 s, single-threaded bz2 and XML with the wikitext parsed in a worker
pool; sv-en 8 s; lexin-sv 4 s).

## Output

Per dictionary, in `build/dictionaries/`:

- `benday-<id>-<version>.zip`: `benday-<id>.ifo`, `.idx`, `.dict.dz`,
  `.syn` and `LICENSE.txt` (licence and attribution). The `.dict.dz` is
  stored (already compressed), the rest deflated. Files are flat in the
  archive.
- `<id>-<version>/`: the same files unpacked.
- `dictionaries.json`: the index, one entry per dictionary (merged with an
  existing index by `id`): `id` (`wiktionary-<lang>`, `wiktionary-sv-en`,
  `lexin-sv`; the same across versions), `language` (the headwords'
  language: the book's), `definitions` (the language the definitions are
  written in), `name`, `version` (the source's date: its Last-Modified),
  `format` (`stardict`), `archive` (`zip`), `size` and `sha256` (of the
  archive), `unpacked_size`, `words`, `synonyms`, `licence`, `licence_url`,
  `attribution`, `source`, `url`.

The build is reproducible: the same dump gives the same bytes (fixed gzip
and zip times, sorted output).

### StarDict files

- `.ifo`: version 3.0.0, `sametypesequence=h`, `idxoffsetbits=32`,
  `synwordcount`, `author`, `website`, `description` (the attribution),
  `date`, `lang` (the headwords' language, then the definitions' when they
  differ: `sv-en`; Benday reads the first as the language, so an import
  from a file doesn't ask).
- `.idx`: one entry per headword (all of a word's parts of speech in one
  article), sorted by StarDict's rule: `g_ascii_strcasecmp` (bytes, only
  ASCII letters folded), then `strcmp`. Case variants are separate
  headwords (`Hus`, `hus`).
- `.dict.dz`: dictzip (gzip with the `RA` chunk table, 58315-byte chunks,
  each ending with a full flush), readable by `gzip`, `dictzip -d` and
  random access by chunk.
- `.syn`: inflected and alternative forms → their lemma's `.idx` entry,
  same sort order. A form can point at several lemmas (`went` → `go`,
  `wend`, …), and a word can be both a headword and a form (`casa` →
  `casa` and, through `.syn`, `casar`).
- Articles are HTML in a small subset, text escaped, no attributes:
  `<p><b>part of speech</b> <i>head line or gender</i> IPA</p>` then
  `<ol><li>sense<br><i>example</i> – translation</li></ol>` (sub-senses as
  a nested `<ol>`; a sense's labels as `<i>(…)</i>`); one `<p>` + `<ol>`
  per part of speech. Tags used: `p b i ol li br`.

## Sources

| Key | Id | Name | Source | Definitions | Licence |
|---|---|---|---|---|---|
| en | wiktionary-en | English dictionary (Wiktionary) | kaikki.org: English Wiktionary › English | English | CC BY-SA 4.0 |
| sv | wiktionary-sv | Svensk ordbok (Wiktionary) | Swedish Wiktionary dump (`svwiktionary-latest-pages-articles.xml.bz2`), `svwiktionary.py` | Swedish | CC BY-SA 4.0 |
| sv-en | wiktionary-sv-en | Swedish–English (Wiktionary) | kaikki.org: English Wiktionary › Swedish | English | CC BY-SA 4.0 |
| lexin-sv | lexin-sv | Svenska ord (Lexin) | ISOF's Lexin "Svenska ord", 4th edition (`swe_swe.xml`), `lexin.py` | Swedish | CC BY 4.0 |
| de | wiktionary-de | Deutsches Wörterbuch (Wiktionary) | kaikki.org: German Wiktionary › Deutsch | German | CC BY-SA 4.0 |
| fr | wiktionary-fr | Dictionnaire français (Wiktionnaire) | kaikki.org: French Wiktionary › Français | French | CC BY-SA 4.0 |
| es | wiktionary-es | Diccionario español (Wikcionario) | kaikki.org: Spanish Wiktionary › Español | Spanish | CC BY-SA 4.0 |

URLs are in `DICTIONARIES` in `build.py`.

### kaikki.org

kaikki.org publishes wiktextract's extracts of the English Wiktionary
(every language's entries, with English definitions, per language under
`/dictionary/<Language>/`) and of some other editions (`/<xx>wiktionary/`:
cs, de, el, es, fr, id, it, ja, ko, ku, ms, nl, pl, pt, ru, simple, th, tr,
vi, zh in October 2026; no Swedish one). A book's reader wants definitions
in the book's language, so each dictionary takes the native edition's
entries for its own language where kaikki.org has it:

en, de, fr and es take the native edition (the English edition's German
entries would define in English). kaikki.org has no Swedish Wiktionary
extract (wiktextract's sv extractor is a stub), so `sv` reads the
Swedish Wiktionary's dump itself (below), and the English edition's
Swedish entries stay available as `sv-en`, Swedish–English.

### Conversion (kaikki.org)

- Kept: every entry of the language (the per-language files are already
  filtered; `lang_code` is checked), except letters (`character`) and
  senses without a gloss. Proper nouns and multi-word headwords stay.
- Header: the part of speech (`pos_title` in the native editions, an
  English name for the English edition's codes), the English edition's
  head line (`hus n`, `gå (present går, preterite gick, …)`, cut at 160
  characters) or the gender (de, fr), and the first IPA.
- Senses: the gloss (the English edition's `raw_glosses`, which carry its
  labels; the native editions' `raw_tags` as a label), the first example
  cut at 200 characters (and its English translation in the English
  edition), no quotation sources, etymology, translations or audio.
- Forms: the `forms` of a lemma entry become `.syn` rows (single words
  only: no `je siège`, `j’…`, no inflection-table markers). An entry whose
  senses are all "form of" / "alternative form of" a lemma that is in the
  dictionary (the gloss ends with the lemma: "definite plural of rave",
  "… de siéger.") is left out and becomes `.syn` rows instead; one whose
  lemma is missing keeps its article. French "Forme de nom" entries that
  define the word ("Pluriel de travail : définition") stay articles.

### Swedish Wiktionary (`svwiktionary.py`)

The dump (94 MB, from `dumps.wikimedia.org/svwiktionary/latest/`) is
streamed with `bz2` and `xml.etree.iterparse`; a regex-and-brace parser
reads the wikitext, no template expansion:

- Pages: main namespace (`<ns>0</ns>`) with a `==Svenska==` section, cut
  at the next level-2 heading. Each `===…===` part-of-speech heading
  (`Substantiv`, `Verb`, …; `Tecken` and non-POS headings like `Källor`
  skipped) is an entry; a second head template after senses (`hus` [1]
  and [2]) starts another. Level-4 sections (`Översättningar`, …) are not
  read.
- Header: the heading, a head line from the head template (`sv-subst-n-…`
  → `en bil`, `sv-subst-t-…` → `ett hus`, both when templates share a
  block: `ett vad; en vad`; proper nouns none; verbs `gå (gick, gått)` from
  `pret=`/`sup=`, or `-ade`/`-at` for a plain `sv-verb-ar`; adjectives
  `bra (bättre, bäst)` from `komp=`/`sup=`), and the IPA of
  `*{{uttal|sv|ipa=…}}`.
- Senses: `#` lines (`##` as sub-senses). Leading `{{tagg|…|text=…}}`
  (positional labels and `text=`; `kat=` dropped), `{{dödform}}`
  (föråldrat), `{{oböjl}}`, `{{oräkn}}` and a hand-written `(''…'')` are
  the labels. In the text: `{{avledning|sv|snabb|adj}}` → "avledning av
  adjektivet snabb" (`ordform=perfpart` → "perfektparticip av …"),
  `{{led}}`, `{{länka}}`, `{{övrigatecken}}` as text, inline `{{tagg}}` in
  brackets; `{{?}}`, `{{färg}}`, sources and other templates dropped;
  `[[a|b]]` → b, quotes, `<ref>`, comments and tags dropped, `<nowiki>`
  and `<math>` literal, entities decoded.
- Example: the first `#:` line under a sense that is a plain italic
  sentence (no templates); `{{citat}}`, `{{synonymer}}`, `{{fraser}}` and
  the like are skipped.
- Forms: a definition that is only `{{böjning|sv|<pos>|<lemma>}}`
  ("böjningsform av …") or `{{gammalstavning|sv|…|<modern>}}` ("äldre
  stavning av …"), maybe several (`war`), is a "form of" sense: as for the
  kaikki builds, a page of only those becomes .syn rows when the lemma is
  in the dictionary (339k of the 451k entries), else keeps its article.
  The head line's verb and adjective forms are .syn rows too.

The rest (`convert.entry_from` with edition `svwikt`, `assemble`,
`stardict`) is shared with the kaikki builds.

### Lexin (`lexin.py`)

`swe_swe.xml` (30 MB) from <https://sprakresurser.isof.se/lexin/svenska/>,
"Svenska ord", 4th edition (2020; the file's Last-Modified, used as the
version, is the server's). Not Språkbanken's `LEXIN.zip`: that is the 2nd
edition with a 2002 licence forbidding publication.

- One article per headword (Lexin's two `går`, noun and verb, together).
  Header: the part of speech written out (`subst., ingen böjning` →
  `substantiv, ingen böjning`), the inflections with Lexin's `att`/`har`/
  `är`/`!` (`att gå, gick, har gått, är gången, gå!`; `–` for a missing
  form dropped), alternative spellings (`eller akne`) and Lexin's own
  pronunciation in brackets (not IPA).
- Senses: one per `<Lexeme>`: labels (`<Comment>` of type style/general,
  `<Gramcom>`), definition (a type-def `<Comment>` when there is none),
  `<Explanation>`, construction patterns (`<Graminfo>`), up to three
  examples, sub-senses (`<Cycle>`) as a nested list, idioms in bold with
  their definition, "Sammansättningar: …" (compounds, `|` dropped) and
  "Motsats: …" (antonyms). Audio, illustrations, animations, themes left
  out.
- Forms: every `<Index>` (inflections, genitives, the compounds' forms)
  but the compound parts (`Type="prefix|suffix"`) and phrases; Lexin heads
  verbs in the present tense, so `gå` and `gick` find `går`. A lemma that
  only says "see X" (`akne` → `acne`) is a .syn row of X when X is in the
  dictionary.

## Sizes (extracts of 2026-10-01 … 28)

| Dictionary | Headwords | Forms (.syn) | .dict.dz | .idx | .syn | Archive | Unpacked |
|---|---|---|---|---|---|---|---|
| en | 844,222 | 653,183 | 60.3 MB | 16.6 MB | 10.2 MB | 71.8 MB | 87.1 MB |
| sv | 108,298 | 342,119 | 4.2 MB | 2.0 MB | 5.7 MB | 6.1 MB | 12.0 MB |
| sv-en | 80,550 | 307,284 | 2.9 MB | 1.5 MB | 5.0 MB | 4.5 MB | 9.5 MB |
| lexin-sv | 22,336 | 174,397 | 1.4 MB | 0.4 MB | 2.8 MB | 2.1 MB | 4.7 MB |
| de | 301,575 | 774,784 | 24.5 MB | 6.3 MB | 13.2 MB | 30.2 MB | 44.0 MB |
| fr | 544,889 | 1,694,234 | 43.4 MB | 11.2 MB | 29.5 MB | 54.0 MB | 84.1 MB |
| es | 395,035 | 594,302 | 10.1 MB | 7.7 MB | 9.2 MB | 15.0 MB | 27.0 MB |

English is the largest: multi-word headwords are 22% of its text (43 MB
of 198 MB uncompressed) and capitalised ones (mostly names) 15%.

## Licence

Wiktionary's text is CC BY-SA 4.0 (and GFDL); kaikki.org's extracts carry
the same licence. The Wiktionary dictionaries are adaptations and are
shared under CC BY-SA 4.0: every archive has a `LICENSE.txt` crediting
Wiktionary's contributors (with the edition's URL; "Swedish Wiktionary
(sv.wiktionary.org)" for `sv`), Wiktextract and kaikki.org for the kaikki
builds, linking the licence and saying what was changed; the `.ifo`
description and the index's `attribution` say the same.

Lexin "Svenska ord" is CC BY 4.0 (ISOF's dataset page and `metadata.xml`;
also researchdata.se, ext0305): `lexin-sv`'s `LICENSE.txt`, `.ifo` and
index entry credit Institutet för språk och folkminnen (Språkrådet) and
the revision at Göteborgs universitet (with the revisers' names in
`LICENSE.txt`), link the licence and say it was converted to StarDict and
what was left out. No share-alike. The app should show the attribution
with the dictionary (name, licence, link). The build tool itself is
Benday's code.

## Publishing

The public site repo (PalleKarlsson/benday) rebuilds and publishes the
dictionaries with its Dictionaries workflow
(`website/.github/workflows/dictionaries.yml` here, published with the
website by `scripts/publish-website.sh`): every quarter, or by hand with
*Run workflow*. Each run makes a release `dictionaries-<date>` holding the
zips and replaces `dictionaries.json` on the fixed release `dictionaries`,
the address the app reads:
https://github.com/PalleKarlsson/benday/releases/download/dictionaries/dictionaries.json

The workflow runs the copy of this tool in `website/tools/dictionaries/`.
After changing anything here, copy it there
(`cp tool/dictionaries/*.py tool/dictionaries/README.md website/tools/dictionaries/`);
`tool/tests/test_dictionaries_copy.py` fails until you do.

