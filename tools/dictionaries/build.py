#!/usr/bin/env python3
"""Builds Benday's offline dictionaries as StarDict (.ifo, .idx, .dict.dz,
.syn) in a .zip with the licence, plus dictionaries.json. Sources:
Wiktionary extracts from kaikki.org (wiktextract JSONL, CC BY-SA 4.0), the
Swedish Wiktionary's own dump (CC BY-SA 4.0, parsed by svwiktionary.py),
ISOF's Lexin "Svenska ord" (CC BY 4.0, lexin.py) and EDRDG's JMdict
(Japanese–English, CC BY-SA 4.0, jmdict.py).

  tool/dictionaries/build.py                     # all dictionaries
  tool/dictionaries/build.py --lang sv,lexin-sv  # some (keys of DICTIONARIES)
  tool/dictionaries/build.py --lang sv-en --input x.jsonl.gz --version 2026-10-01

Dumps are cached in ~/.cache/benday-dictionaries (--cache-dir); output goes
to build/dictionaries (--out). Nothing is uploaded. See README.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import gzip
import hashlib
import json
import multiprocessing
import os
import shutil
import sys
import time
import urllib.request
import zipfile
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convert  # noqa: E402
import jmdict  # noqa: E402
import lexin  # noqa: E402
import stardict  # noqa: E402
import svwiktionary  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
KAIKKI = 'https://kaikki.org'
USER_AGENT = 'Benday-dictionary-build/1 (+https://getbenday.com)'

# Per dictionary (the key is --lang's and the cache folder's name):
# `source` says how it is read (kaikki: wiktextract JSONL; svwiktionary:
# the Wikimedia dump; lexin: ISOF's XML; jmdict: EDRDG's JMdict_e),
# `language` is the headwords'
# (the book's), `definitions` the language they are defined in. The
# Wiktionary ones take the native edition where one can be had, else the
# English Wiktionary's entries for the language. See README.md › Sources.
DICTIONARIES = {
    'en': {
        'source': 'kaikki', 'id': 'wiktionary-en', 'language': 'en',
        'url': f'{KAIKKI}/dictionary/English/kaikki.org-dictionary-English.jsonl.gz',
        'edition': 'en', 'wiki': 'en.wiktionary.org',
        'name': 'English dictionary (Wiktionary)',
        'definitions': 'en',
    },
    'sv': {
        'source': 'svwiktionary', 'id': 'wiktionary-sv', 'language': 'sv',
        'url': 'https://dumps.wikimedia.org/svwiktionary/latest/'
               'svwiktionary-latest-pages-articles.xml.bz2',
        'edition': 'svwikt', 'wiki': 'sv.wiktionary.org',
        'name': 'Svensk ordbok (Wiktionary)',
        'definitions': 'sv',
    },
    'sv-en': {
        'source': 'kaikki', 'id': 'wiktionary-sv-en', 'language': 'sv',
        'url': f'{KAIKKI}/dictionary/Swedish/kaikki.org-dictionary-Swedish.jsonl.gz',
        'edition': 'en', 'wiki': 'en.wiktionary.org',
        'name': 'Swedish–English (Wiktionary)',
        'definitions': 'en',
    },
    'lexin-sv': {
        'source': 'lexin', 'id': 'lexin-sv', 'language': 'sv',
        'url': 'https://sprakresurser.isof.se/lexin/svenska/swe_swe.xml',
        'name': 'Svenska ord (Lexin)',
        'definitions': 'sv',
    },
    'ja-en': {
        'source': 'jmdict', 'id': 'jmdict-ja-en', 'language': 'ja',
        'url': 'https://www.edrdg.org/pub/Nihongo/JMdict_e.gz',
        'name': 'Japanese–English (JMdict)',
        'definitions': 'en',
    },
    'de': {
        'source': 'kaikki', 'id': 'wiktionary-de', 'language': 'de',
        'url': f'{KAIKKI}/dewiktionary/Deutsch/kaikki.org-dictionary-Deutsch.jsonl.gz',
        'edition': 'de', 'wiki': 'de.wiktionary.org',
        'name': 'Deutsches Wörterbuch (Wiktionary)',
        'definitions': 'de',
    },
    'fr': {
        'source': 'kaikki', 'id': 'wiktionary-fr', 'language': 'fr',
        'url': f'{KAIKKI}/frwiktionary/Fran%C3%A7ais/kaikki.org-dictionary-Fran%C3%A7ais.jsonl.gz',
        'edition': 'fr', 'wiki': 'fr.wiktionary.org',
        'name': 'Dictionnaire français (Wiktionnaire)',
        'definitions': 'fr',
    },
    'es': {
        'source': 'kaikki', 'id': 'wiktionary-es', 'language': 'es',
        'url': f'{KAIKKI}/eswiktionary/Espa%C3%B1ol/kaikki.org-dictionary-Espa%C3%B1ol.jsonl.gz',
        'edition': 'es', 'wiki': 'es.wiktionary.org',
        'name': 'Diccionario español (Wikcionario)',
        'definitions': 'es',
    },
}

BY_SA = ('CC BY-SA 4.0', 'https://creativecommons.org/licenses/by-sa/4.0/')
BY = ('CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/')
LEXIN_PAGE = 'https://sprakresurser.isof.se/lexin/svenska/'
EDRDG = 'https://www.edrdg.org/'
EDRDG_LICENCE = 'https://www.edrdg.org/edrdg/licence.html'
JMDICT_PAGE = 'https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project'


AUTHORS = {
    'lexin': 'Institutet för språk och folkminnen (Språkrådet)',
    'jmdict': 'Electronic Dictionary Research and Development Group',
}


def ifo_lang(cfg: dict) -> str:
    """The .ifo's `lang`: the headwords' language, then the definitions'
    when they differ (`sv-en`); Benday takes the first as the book's."""
    if cfg['definitions'] == cfg['language']:
        return cfg['language']
    return f"{cfg['language']}-{cfg['definitions']}"


def licence_of(cfg: dict) -> tuple[str, str]:
    return BY if cfg['source'] == 'lexin' else BY_SA


def attribution(cfg: dict) -> str:
    if cfg['source'] == 'jmdict':
        # EDRDG's sample acknowledgement for a dictionary, and its licence.
        return ('This publication has included material from the JMdict '
                '(EDICT, etc.) dictionary files in accordance with the '
                'licence provisions of the Electronic Dictionary Research '
                f'and Development Group ({EDRDG}). The files are the '
                'property of the Group and used in conformance with its '
                f'licence ({EDRDG_LICENCE}): {BY_SA[0]} ({BY_SA[1]}). '
                'Converted to StarDict by Benday: reformatted; '
                'cross-references, antonyms, loanword sources and sense '
                'restrictions left out; other spellings and readings linked '
                'to the headword.')
    if cfg['source'] == 'lexin':
        return ('Lexin: Svenska ord, 4th edition (fjärde versionen), '
                'Institutet för språk och folkminnen (Språkrådet), revised '
                'at Göteborgs universitet on its commission; licensed '
                f'{BY[0]} ({BY[1]}); source {LEXIN_PAGE}. Converted to '
                'StarDict by Benday: reformatted; pronunciation audio, '
                'illustrations, animations and theme codes left out.')
    if cfg['source'] == 'svwiktionary':
        return ('Definitions from the Swedish Wiktionary (sv.wiktionary.org,'
                ' https://sv.wiktionary.org) by its contributors, licensed '
                f'{BY_SA[0]} ({BY_SA[1]}). Parsed from the Wikimedia dump '
                'and converted to StarDict by Benday: reformatted, templates '
                'rendered as text, translations, quotations and etymology '
                'left out, inflected forms linked to their lemma.')
    return (f'Definitions from Wiktionary (https://{cfg["wiki"]}) by its '
            f'contributors, licensed {BY_SA[0]} ({BY_SA[1]}). Extracted '
            'with Wiktextract by Tatu Ylonen (https://kaikki.org). '
            'Converted to StarDict by Benday: reformatted, examples '
            'shortened, inflected forms linked to their lemma.')


_FILES = """Files: StarDict 3.0.0 (.ifo, .idx, .dict.dz dictzip, .syn),
sametypesequence=h.
"""

_BY_SA_TERMS = """Licence: this dictionary is an adaptation of Wiktionary content and is
shared under the same licence, Creative Commons Attribution-ShareAlike 4.0
International ({url}; full text at
https://creativecommons.org/licenses/by-sa/4.0/legalcode). You may copy,
change and share it, also commercially, if you credit Wiktionary's
contributors as above, link the licence, say that it was changed, and share
your changes under the same licence. Wiktionary's text is also available
under the GNU Free Documentation License; see
https://{wiki}/wiki/Wiktionary:Copyrights (or the edition's
equivalent page).
"""


def licence_text(key: str, cfg: dict, version: str, source: str) -> str:
    head = (f"{cfg['name']}\nVersion {version} (language: "
            f"{cfg['language']}, definitions in: {cfg['definitions']})\n\n"
            f"{attribution(cfg)}\n\n")
    if cfg['source'] == 'jmdict':
        return head + f"""Source: {source}
JMdict/EDICT project: {JMDICT_PAGE}
EDRDG licence statement: {EDRDG_LICENCE}

JMdict is the property of the Electronic Dictionary Research and
Development Group (EDRDG) and is used in conformance with the Group's
licence. Benday claims no copyright over this material, and the EDRDG
doesn't endorse Benday or this conversion.

Licence: Creative Commons Attribution-ShareAlike 4.0 International
({BY_SA[1]}; full text at
https://creativecommons.org/licenses/by-sa/4.0/legalcode). You may copy,
change and share it, also commercially, if you credit the EDRDG as above,
link the licence, say that it was changed, and share your changes under
the same licence. The EDRDG's licence also asks software that uses the
files to keep them up to date: rebuild from the current JMdict regularly.

Changes: converted from JMdict_e (the English glosses) to StarDict by
Benday's build tool (tool/dictionaries/jmdict.py): one article per
headword (its first kanji spelling, else its first reading) with the part
of speech, the readings and other spellings, then one numbered sense per
JMdict sense with its labels (part of speech, field, misc, dialect), its
glosses and its note. Other spellings and readings are linked to the
headword. Cross-references, antonyms, loanword sources and the
restrictions of senses to some spellings were left out.

""" + _FILES
    if cfg['source'] == 'lexin':
        return head + f"""Source: {source}
Dataset page: {LEXIN_PAGE} (also https://researchdata.se/en/catalogue/dataset/ext0305-1)
Credit: Lexin: Svenska ord, Lexins svenska lexikon, fjärde versionen
(published 2020-03-09). Institutet för språk och folkminnen (Språkrådet).
The revision was made at Göteborgs universitet (University of Gothenburg)
on commission of Institutet för språk och folkminnen by Daniel Berg, Sture
Berg, Ann-Kristin Hult, Louise Holmer, Christian Sjögreen, Emma Sköldberg
and Maria Toporowska Gronostaj, led by professor Sven-Göran Malmgren.

Licence: Creative Commons Attribution 4.0 International (CC BY 4.0),
{BY[1]} (full text at https://creativecommons.org/licenses/by/4.0/legalcode).
You may copy, change and share it, also commercially, if you credit the
source as above, link the licence and say what was changed.

Changes: converted from Lexin's XML (swe_swe.xml) to StarDict by Benday's
build tool: one article per headword with its part of speech,
inflections, pronunciation (Lexin's own transcription), definitions,
explanations, construction patterns, examples, sub-senses, idioms,
compounds and antonyms; inflected forms (Lexin's index) linked to their
headword. Pronunciation audio, illustrations, animations, theme codes and
cross-references were left out.

""" + _FILES
    if cfg['source'] == 'svwiktionary':
        return head + f"""Source: {source}
Swedish Wiktionary (sv.wiktionary.org): https://sv.wiktionary.org
Parsed from the Wikimedia dump of {version} by Benday's build tool
(tool/dictionaries/svwiktionary.py): the Swedish sections ("Svenska") of
the main namespace; part of speech, gender and short head lines from the
head templates, pronunciation (IPA), definitions with their labels, the
first plain example of a sense; inflected forms and old spellings
("böjningsform av", "äldre stavning av") linked to their lemma.
Translations, quotations, synonyms, etymology and audio were left out.

""" + _BY_SA_TERMS.format(url=BY_SA[1], wiki=cfg['wiki']) + '\n' + _FILES
    return head + f"""Source: {source}
Wiktionary edition: https://{cfg['wiki']}
Wiktextract: https://github.com/tatuylonen/wiktextract
Citation: Tatu Ylonen, "Wiktextract: Wiktionary as Machine-Readable
Structured Data", Proceedings of the 13th Conference on Language Resources
and Evaluation (LREC), pp. 1317-1325, Marseille, 2022.

""" + _BY_SA_TERMS.format(url=BY_SA[1], wiki=cfg['wiki']) + '\n' + _FILES


# --- downloads -------------------------------------------------------------

def _head(url: str) -> dict:
    req = urllib.request.Request(url, method='HEAD',
                                 headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return {'size': int(r.headers.get('Content-Length') or -1),
                'etag': r.headers.get('ETag'),
                'last_modified': r.headers.get('Last-Modified')}


def fetch(url: str, cache_dir: Path, key: str, offline: bool = False,
          log=print) -> tuple[Path, dict]:
    """The dump at [url] in the cache (downloaded, resumed or refreshed as
    needed) and its metadata (size, etag, last_modified)."""
    folder = cache_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    name = urllib.request.unquote(url.rsplit('/', 1)[1])
    path = folder / name
    meta_path = folder / (name + '.meta.json')
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    if offline:
        if not path.exists():
            raise SystemExit(f'{path} not cached (--offline)')
        return path, meta or {'size': path.stat().st_size, 'etag': None,
                              'last_modified': None}
    remote = _head(url)
    if (path.exists() and path.stat().st_size == remote['size']
            and (meta is None or meta.get('etag') == remote['etag'])):
        meta_path.write_text(json.dumps(remote, indent=1))
        return path, remote
    part = folder / (name + '.part')
    part_meta = folder / (name + '.part.json')
    start = 0
    if part.exists() and part_meta.exists() and \
            json.loads(part_meta.read_text()).get('etag') == remote['etag']:
        start = part.stat().st_size
    else:
        part.unlink(missing_ok=True)
    part_meta.write_text(json.dumps(remote))
    headers = {'User-Agent': USER_AGENT}
    if start:
        headers['Range'] = f'bytes={start}-'
    log(f'  downloading {url} ({remote["size"] / 1e6:.0f} MB'
        + (f', resuming at {start / 1e6:.0f} MB' if start else '') + ')')
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r, \
            open(part, 'ab' if start and r.status == 206 else 'wb') as out:
        shutil.copyfileobj(r, out, 1 << 20)
    if part.stat().st_size != remote['size']:
        raise SystemExit(f'{url}: got {part.stat().st_size} bytes, '
                         f'expected {remote["size"]}; run again to resume')
    part.replace(path)
    part_meta.unlink(missing_ok=True)
    meta_path.write_text(json.dumps(remote, indent=1))
    return path, remote


def version_of(meta: dict | None, path: Path) -> str:
    """The extract's date (the server's Last-Modified), as YYYY-MM-DD."""
    if meta and meta.get('last_modified'):
        when = email.utils.parsedate_to_datetime(meta['last_modified'])
    else:
        when = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
    return when.strftime('%Y-%m-%d')


# --- conversion ------------------------------------------------------------

def _batches(path: Path, size: int = 2000):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as f:
        batch = []
        for line in f:
            batch.append(line)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch


def _page_batches(path: Path, size: int = 2000):
    batch = []
    for page in svwiktionary.iter_pages(path):
        batch.append(page)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _convert_svwikt(pages) -> list:
    """A batch of (title, Swedish section) → convert.Entry objects (top
    level, so a worker pool can call it)."""
    out = []
    for d in svwiktionary.parse_pages(pages):
        e = convert.entry_from(d, 'svwikt', 'sv')
        if e:
            out.append(e)
    return out


def _pooled(work, batches, workers: int):
    if workers <= 1:
        for b in batches:
            yield from work(b)
        return
    with multiprocessing.Pool(workers) as pool:
        for entries in pool.imap(work, batches, chunksize=2):
            yield from entries


def read_entries(path: Path, cfg: dict, workers: int):
    """The source at [path] as convert.Entry objects, in its order."""
    if cfg['source'] == 'lexin':
        return iter(lexin.read_entries(path))
    if cfg['source'] == 'jmdict':
        return iter(jmdict.read_entries(path))
    if cfg['source'] == 'svwiktionary':
        return _pooled(_convert_svwikt, _page_batches(path), workers)
    work = partial(convert.convert_lines, edition=cfg['edition'],
                   lang=cfg['language'])
    return _pooled(work, _batches(path), workers)


def _zip(archive: Path, files: list[tuple[str, Path]], date: tuple) -> None:
    """A reproducible zip: fixed times and order; .dict.dz stored (it is
    compressed already), the rest deflated."""
    with zipfile.ZipFile(archive, 'w') as z:
        for name, path in files:
            info = zipfile.ZipInfo(name, date_time=date)
            info.external_attr = 0o644 << 16
            info.compress_type = (zipfile.ZIP_STORED if name.endswith('.dz')
                                  else zipfile.ZIP_DEFLATED)
            z.writestr(info, path.read_bytes(), compresslevel=9)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def build_dictionary(key: str, cfg: dict, source_path: Path, version: str,
                     out: Path, base_url: str, source_url: str,
                     workers: int = 1, log=print) -> dict:
    t0 = time.time()
    built = convert.assemble(read_entries(source_path, cfg, workers))
    t1 = time.time()
    dict_id = cfg['id']
    base = f'benday-{dict_id}'
    when = dt.datetime.strptime(version, '%Y-%m-%d').replace(
        tzinfo=dt.timezone.utc)
    work = out / f'{dict_id}-{version}'
    if work.exists():
        shutil.rmtree(work)
    paths = stardict.write_stardict(
        work, base, built.articles, built.synonyms, {
            'bookname': cfg['name'],
            'author': AUTHORS.get(cfg['source'], 'Wiktionary contributors'),
            'website': (LEXIN_PAGE if cfg['source'] == 'lexin'
                        else EDRDG if cfg['source'] == 'jmdict'
                        else f'https://{cfg["wiki"]}'),
            'description': attribution(cfg),
            'date': when.strftime('%Y.%m.%d'),
            'sametypesequence': 'h',
            'lang': ifo_lang(cfg),
        }, mtime=int(when.timestamp()))
    lic = work / 'LICENSE.txt'
    lic.write_text(licence_text(key, cfg, version, source_url),
                   encoding='utf-8')
    files = [(p.name, p) for p in paths.values()] + [(lic.name, lic)]
    archive = out / f'{base}-{version}.zip'
    _zip(archive, files, when.timetuple()[:6])
    unpacked = sum(p.stat().st_size for _, p in files)
    entry = {
        'id': dict_id,
        'language': cfg['language'],
        'definitions': cfg['definitions'],
        'name': cfg['name'],
        'version': version,
        'format': 'stardict',
        'archive': 'zip',
        'size': archive.stat().st_size,
        'unpacked_size': unpacked,
        'sha256': sha256(archive),
        'words': len(built.articles),
        'synonyms': len(built.synonyms),
        'licence': licence_of(cfg)[0],
        'licence_url': licence_of(cfg)[1],
        'attribution': attribution(cfg),
        'source': source_url,
        'url': f'{base_url.rstrip("/")}/{archive.name}',
    }
    log(f'  {key}: {built.entries} entries → {len(built.articles)} '
        f'headwords, {len(built.synonyms)} forms ({built.dropped_forms} '
        f'form-only entries as .syn); convert {t1 - t0:.0f} s, write '
        f'{time.time() - t1:.0f} s')
    log('  ' + ', '.join(f'{p.name} {p.stat().st_size / 1e6:.1f} MB'
                         for _, p in files[:-1]))
    log(f'  {archive.name}: {entry["size"] / 1e6:.1f} MB '
        f'(unpacked {unpacked / 1e6:.1f} MB)')
    return entry


def update_index(index_path: Path, entries: list[dict]) -> None:
    index = {'schema': 1, 'dictionaries': []}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding='utf-8'))
    by_id = {d['id']: d for d in index['dictionaries']}
    for e in entries:
        by_id[e['id']] = e
    index['dictionaries'] = sorted(by_id.values(), key=lambda d: d['id'])
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False)
                          + '\n', encoding='utf-8')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('--lang', default=','.join(DICTIONARIES),
                    help='dictionaries, comma-separated: '
                         + ', '.join(DICTIONARIES))
    ap.add_argument('--cache-dir', type=Path, default=Path(
        os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
        / 'benday-dictionaries')
    ap.add_argument('--out', type=Path, default=REPO / 'build' / 'dictionaries')
    ap.add_argument('--base-url', default='REPLACE_WITH_HOSTING_URL',
                    help='where the archives will be hosted (for the index)')
    ap.add_argument('--input', type=Path,
                    help='a local source file (JSONL(.gz), dump .xml.bz2, '
                         'Lexin XML or JMdict_e(.gz)) instead of the download '
                         '(one --lang only)')
    ap.add_argument('--version', help='version for --input (YYYY-MM-DD)')
    ap.add_argument('--offline', action='store_true',
                    help='use the cached dumps without asking their servers')
    ap.add_argument('--workers', type=int,
                    default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    args = ap.parse_args(argv)

    keys = [k.strip() for k in args.lang.split(',') if k.strip()]
    for k in keys:
        if k not in DICTIONARIES:
            ap.error(f'unknown dictionary {k}')
    if args.input and len(keys) != 1:
        ap.error('--input needs exactly one --lang')
    args.out.mkdir(parents=True, exist_ok=True)
    entries = []
    for key in keys:
        cfg = DICTIONARIES[key]
        print(f'{key}: {cfg["name"]}')
        if args.input:
            path, source = args.input, cfg['url']
            version = args.version or version_of(None, path)
        else:
            path, meta = fetch(cfg['url'], args.cache_dir, key, args.offline)
            source = cfg['url']
            version = version_of(meta, path)
        entries.append(build_dictionary(key, cfg, path, version, args.out,
                                        args.base_url, source, args.workers))
    update_index(args.out / 'dictionaries.json', entries)
    print(f'index: {args.out / "dictionaries.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
