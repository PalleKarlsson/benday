"""JMdict (EDRDG's Japanese–English dictionary, JMdict_e.gz, CC BY-SA 4.0)
→ convert.Entry objects for convert.assemble (T-145).

One Entry per `<entry>`, headed by its first kanji spelling (`<keb>`), or
its first reading (`<reb>`) when it has none (する, ありがとう's 有難う is
headed 有難う). The header is the first sense's part of speech and the
readings that go with the headword (`<re_restr>`), then the other
spellings ("also 泪"); one numbered sense per `<sense>`: its labels (part
of speech when it changes, field, misc, dialect), its English glosses
joined by "; ", and its note (`<s_inf>`). Cross-references, antonyms,
loanword sources and the restrictions of senses to some spellings are left
out.

Every other spelling and every reading becomes a .syn row of the headword,
so a word written in kana (まくら) or another way finds its entry. Entries
sharing a headword (the several 生) are one article, as for the other
builds. JMdict's entities (`&n;`) are expanded by the parser from the
file's own DTD; their expansions lose the trailing romanised Japanese term
("noun (common) (futsuumeishi)" → "noun (common)").
"""
from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET

from convert import Entry, Sense, _cut, _e, _valid_word

MAX_TEXT = 300
_SPACE = re.compile(r'\s+')
# The romanised Japanese name at the end of an entity's expansion.
_ROMAJI = re.compile(r'\s*\((?:[a-z]+)\)$')


def _text(el) -> str:
    if el is None or el.text is None:
        return ''
    return _SPACE.sub(' ', el.text).strip()


def label(text: str) -> str:
    """An entity's expansion without its romanised Japanese name."""
    return _ROMAJI.sub('', text.strip())


def _texts(parent, tag: str) -> list[str]:
    return [t for t in (_text(e) for e in parent.findall(tag)) if t]


def entry_from(el) -> Entry | None:
    kanji = [k for k in (_text(k.find('keb')) for k in el.findall('k_ele'))
             if k]
    readings = []  # (reading, the spellings it is restricted to or None)
    for r in el.findall('r_ele'):
        reb = _text(r.find('reb'))
        if not reb:
            continue
        nokanji = r.find('re_nokanji') is not None
        restr = _texts(r, 're_restr')
        readings.append((reb, [] if nokanji else (restr or None)))
    if not kanji and not readings:
        return None
    word = kanji[0] if kanji else readings[0][0]
    if not _valid_word(word):
        return None
    # The head line: the headword's readings, then the other spellings
    # (a kana-only word's other readings).
    heads = [reb for reb, restr in readings
             if restr is None or word in restr] if kanji else []
    others = kanji[1:] if kanji else [reb for reb, _ in readings[1:]]

    senses, last_pos, first_pos = [], None, None
    for s in el.findall('sense'):
        glosses = _texts(s, 'gloss')
        if not glosses:
            continue
        pos = [label(p) for p in _texts(s, 'pos')]
        pos = pos or last_pos or []
        labels = []
        if first_pos is None:
            first_pos = pos
        elif pos != last_pos:
            labels.extend(pos)
        last_pos = pos
        for tag in ('field', 'misc', 'dial'):
            labels.extend(label(t) for t in _texts(s, tag))
        out = f'<i>({_e(", ".join(labels))})</i> ' if labels else ''
        out += _e(_cut('; '.join(glosses), MAX_TEXT))
        for note in _texts(s, 's_inf'):
            out += f'<br><i>{_e(_cut(note, MAX_TEXT))}</i>'
        senses.append(Sense(f'<li>{out}</li>'))
    if not senses:
        return None

    parts = [f'<b>{_e(", ".join(first_pos or []))}</b>'] if first_pos else []
    head = []
    if heads:
        head.append('、'.join(heads))
    if others:
        head.append('also ' + '、'.join(others))
    if head:
        parts.append(f'<i>{_e(_cut("; ".join(head), 200))}</i>')
    header = f'<p>{" ".join(parts)}</p>' if parts else ''

    forms = []
    for f in kanji[1:] + [reb for reb, _ in readings]:
        if f != word and _valid_word(f) and f not in forms:
            forms.append(f)
    return Entry(word, header, senses, forms)


def read_entries(path) -> list[Entry]:
    """Every entry of JMdict at [path] (JMdict_e, gzipped or not), in the
    file's order."""
    opener = gzip.open if str(path).endswith('.gz') else open
    out = []
    with opener(path, 'rb') as f:
        for _, el in ET.iterparse(f):
            if el.tag == 'entry':
                e = entry_from(el)
                if e:
                    out.append(e)
                el.clear()
    return out
