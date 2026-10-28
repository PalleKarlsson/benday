"""StarDict 3.0.0 files: writing (.ifo, .idx, .syn, .dict.dz) and a small
reader for checks and tests.

Format notes (StarDict's doc/StarDictFileFormat):
- .idx: entries `word\\0` + offset (u32 BE) + size (u32 BE), sorted by
  stardict_strcmp: g_ascii_strcasecmp (bytes, ASCII letters folded), then
  strcmp (plain bytes). Words are UTF-8, under 256 bytes.
- .syn: `word\\0` + index into .idx (u32 BE), sorted the same way.
- .dict with sametypesequence=h: each article is the HTML alone (no type
  byte, and the last field of an article has no terminating NUL).
- .dict.dz is dictzip: a gzip member whose FEXTRA has an `RA` subfield
  (VER=1, CHLEN, CHCNT, CHCNT u16 compressed chunk sizes); every chunk of
  CHLEN uncompressed bytes ends with a full flush, so a reader can inflate
  any chunk alone with a fresh raw inflater.
"""
from __future__ import annotations

import io
import struct
import zlib
from bisect import bisect_left
from pathlib import Path

# dictzip's own default: small enough that a chunk's deflate output always
# fits the u16 size field.
DICTZIP_CHUNK = 58315
MAX_WORD_BYTES = 255


def sort_key(word: str) -> tuple[bytes, bytes]:
    """stardict_strcmp as a key: bytes.lower() folds ASCII only, like
    g_ascii_strcasecmp; bytes compare unsigned, like strcmp."""
    b = word.encode('utf-8')
    return (b.lower(), b)


def dictzip(data: bytes, *, chunk: int = DICTZIP_CHUNK, mtime: int = 0,
            name: str | None = None, level: int = 9) -> bytes:
    """Compress [data] as dictzip (readable by gzip, `dictzip -d` and
    random access by chunk)."""
    count = max(1, -(-len(data) // chunk))
    xlen = 4 + 6 + 2 * count  # subfield header + VER/CHLEN/CHCNT + table
    if xlen > 0xFFFF:
        raise ValueError(f'{len(data)} bytes need {count} dictzip chunks; '
                         'the gzip extra field holds at most 32762')
    comp = zlib.compressobj(level, zlib.DEFLATED, -15, 9)
    sizes = []
    body = io.BytesIO()
    for i in range(count):
        out = comp.compress(data[i * chunk:(i + 1) * chunk])
        out += comp.flush(zlib.Z_FULL_FLUSH)
        if len(out) > 0xFFFF:
            raise ValueError('a dictzip chunk compressed to over 64 KiB')
        sizes.append(len(out))
        body.write(out)
    # dictzip writes the final (empty) block after the last chunk, outside
    # the table.
    body.write(comp.flush(zlib.Z_FINISH))

    flags = 0x04  # FEXTRA
    if name:
        flags |= 0x08  # FNAME
    head = struct.pack('<BBBBIBB', 0x1F, 0x8B, 8, flags, mtime, 2, 3)
    extra = b'RA' + struct.pack('<H', 6 + 2 * count)
    extra += struct.pack('<HHH', 1, chunk, count)
    extra += struct.pack(f'<{count}H', *sizes)
    head += struct.pack('<H', len(extra)) + extra
    if name:
        head += name.encode('latin-1', 'replace') + b'\0'
    tail = struct.pack('<II', zlib.crc32(data) & 0xFFFFFFFF,
                       len(data) & 0xFFFFFFFF)
    return head + body.getvalue() + tail


class DictzipReader:
    """Random access into a .dict.dz through its chunk table."""

    def __init__(self, raw: bytes):
        if raw[:2] != b'\x1f\x8b' or raw[2] != 8:
            raise ValueError('not gzip')
        flags = raw[3]
        if not flags & 0x04:
            raise ValueError('no FEXTRA: not dictzip')
        pos = 10
        (xlen,) = struct.unpack_from('<H', raw, pos)
        pos += 2
        extra_end = pos + xlen
        self.chunk = self.sizes = None
        while pos + 4 <= extra_end:
            si = raw[pos:pos + 2]
            (ln,) = struct.unpack_from('<H', raw, pos + 2)
            if si == b'RA':
                ver, chlen, chcnt = struct.unpack_from('<HHH', raw, pos + 4)
                if ver != 1:
                    raise ValueError(f'dictzip version {ver}')
                self.chunk = chlen
                self.sizes = struct.unpack_from(f'<{chcnt}H', raw, pos + 10)
            pos += 4 + ln
        if self.chunk is None:
            raise ValueError('no RA subfield: not dictzip')
        pos = extra_end
        for flag in (0x08, 0x10):  # FNAME, FCOMMENT
            if flags & flag:
                pos = raw.index(b'\0', pos) + 1
        if flags & 0x02:  # FHCRC
            pos += 2
        self.raw = raw
        self.offsets = []
        for size in self.sizes:
            self.offsets.append(pos)
            pos += size
        self.inflated_chunks = 0  # for tests: what a read touched

    def _chunk(self, i: int) -> bytes:
        self.inflated_chunks += 1
        start = self.offsets[i]
        d = zlib.decompressobj(-15)
        return d.decompress(self.raw[start:start + self.sizes[i]])

    def read(self, offset: int, size: int) -> bytes:
        first = offset // self.chunk
        last = (offset + size - 1) // self.chunk if size else first
        data = b''.join(self._chunk(i) for i in range(first, last + 1))
        start = offset - first * self.chunk
        return data[start:start + size]


def write_stardict(out_dir: Path, base: str, articles: list[tuple[str, str]],
                   synonyms: list[tuple[str, str]], ifo: dict[str, str],
                   *, mtime: int = 0) -> dict[str, Path]:
    """Writes `<base>.ifo/.idx/.dict.dz/.syn` from [articles] (word, HTML;
    words unique) and [synonyms] (form, headword that is in [articles]).
    Returns the paths by extension."""
    articles = sorted(articles, key=lambda a: sort_key(a[0]))
    index_of = {}
    idx = io.BytesIO()
    dic = io.BytesIO()
    for i, (word, html) in enumerate(articles):
        wb = word.encode('utf-8')
        if len(wb) > MAX_WORD_BYTES or b'\0' in wb:
            raise ValueError(f'bad headword {word!r}')
        if word in index_of:
            raise ValueError(f'duplicate headword {word!r}')
        index_of[word] = i
        data = html.encode('utf-8')
        idx.write(wb + b'\0' + struct.pack('>II', dic.tell(), len(data)))
        dic.write(data)
    if dic.tell() > 0xFFFFFFFF:
        raise ValueError('.dict over 4 GiB needs idxoffsetbits=64')

    syn_rows = sorted({(f, index_of[h]) for f, h in synonyms},
                      key=lambda r: (sort_key(r[0]), r[1]))
    syn = io.BytesIO()
    for form, i in syn_rows:
        fb = form.encode('utf-8')
        if len(fb) > MAX_WORD_BYTES or b'\0' in fb:
            raise ValueError(f'bad synonym {form!r}')
        syn.write(fb + b'\0' + struct.pack('>I', i))

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        'ifo': out_dir / f'{base}.ifo',
        'idx': out_dir / f'{base}.idx',
        'dict.dz': out_dir / f'{base}.dict.dz',
    }
    paths['idx'].write_bytes(idx.getvalue())
    paths['dict.dz'].write_bytes(
        dictzip(dic.getvalue(), mtime=mtime, name=f'{base}.dict'))
    if syn_rows:
        paths['syn'] = out_dir / f'{base}.syn'
        paths['syn'].write_bytes(syn.getvalue())

    lines = ["StarDict's dict ifo file", 'version=3.0.0']
    fields = {'bookname': ifo['bookname'],
              'wordcount': str(len(articles)),
              'synwordcount': str(len(syn_rows)) if syn_rows else None,
              'idxfilesize': str(idx.tell()),
              'idxoffsetbits': '32'}
    fields.update({k: v for k, v in ifo.items() if k != 'bookname'})
    for key, value in fields.items():
        if value is None:
            continue
        value = str(value).replace('\r', ' ').replace('\n', '<br>')
        lines.append(f'{key}={value}')
    paths['ifo'].write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return paths


class StarDict:
    """Reads a StarDict dictionary written by write_stardict (or any with
    sametypesequence and 32-bit offsets), for spot checks and tests."""

    def __init__(self, ifo_path: Path):
        ifo_path = Path(ifo_path)
        base = str(ifo_path)[:-len('.ifo')]
        lines = ifo_path.read_text(encoding='utf-8').splitlines()
        if lines[0] != "StarDict's dict ifo file":
            raise ValueError('not an .ifo')
        self.info = dict(l.split('=', 1) for l in lines[1:] if '=' in l)
        raw_idx = Path(base + '.idx').read_bytes()
        self.words, self.entries = [], []
        pos = 0
        while pos < len(raw_idx):
            end = raw_idx.index(b'\0', pos)
            off, size = struct.unpack_from('>II', raw_idx, end + 1)
            self.words.append(raw_idx[pos:end].decode('utf-8'))
            self.entries.append((off, size))
            pos = end + 9
        self.keys = [sort_key(w) for w in self.words]
        self.syn = []
        syn_path = Path(base + '.syn')
        if syn_path.exists():
            raw = syn_path.read_bytes()
            pos = 0
            while pos < len(raw):
                end = raw.index(b'\0', pos)
                (i,) = struct.unpack_from('>I', raw, end + 1)
                self.syn.append((raw[pos:end].decode('utf-8'), i))
                pos = end + 5
        self.syn_keys = [sort_key(w)[0] for w, _ in self.syn]
        dz = Path(base + '.dict.dz')
        if dz.exists():
            self.dict = DictzipReader(dz.read_bytes())
        else:
            plain = Path(base + '.dict').read_bytes()
            self.dict = type('Plain', (), {
                'read': lambda _s, o, n: plain[o:o + n]})()

    def article(self, i: int) -> str:
        off, size = self.entries[i]
        return self.dict.read(off, size).decode('utf-8')

    def lookup(self, word: str) -> list[tuple[str, str]]:
        """Headwords matching [word] case-insensitively (ASCII folding, as
        StarDict), then those its .syn forms point at: (headword, html)."""
        folded = sort_key(word)[0]
        hits = []
        i = bisect_left(self.keys, (folded, b''))
        while i < len(self.keys) and self.keys[i][0] == folded:
            hits.append(i)
            i += 1
        j = bisect_left(self.syn_keys, folded)
        while j < len(self.syn_keys) and self.syn_keys[j] == folded:
            if self.syn[j][1] not in hits:
                hits.append(self.syn[j][1])
            j += 1
        return [(self.words[i], self.article(i)) for i in hits]
