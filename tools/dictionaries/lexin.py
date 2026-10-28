"""Lexin "Svenska ord", 4th edition (ISOF's swe_swe.xml, CC BY 4.0) →
convert.Entry objects for convert.assemble.

One Entry per `<Lemma>` (an `<Article>` holds one): the header is the part
of speech, the inflections (`att gå, gick, har gått`) and Lexin's own
pronunciation (not IPA), then one numbered sense per `<Lexeme>`: its
labels (`<Comment Type="style|general">`, `<Gramcom>`), definition,
explanation, construction patterns (`<Graminfo>`), examples, the
sub-senses (`<Cycle>`, as a nested list), idioms with their definitions,
compounds and antonyms. Audio, illustrations, animations and theme codes
are left out. A lemma that only refers to another ("akne": see "acne")
becomes a .syn row of that one.

The `<Index>` forms (inflections, genitives, the compounds' forms) become
the lemma's .syn rows, so `gå` finds the verb Lexin heads in the present
tense (`går`). The compound parts (`<Index Type="prefix|suffix">`) aren't
forms of the lemma and are skipped. Compound boundaries (`|` in
`abonnemangs|avgift`) are dropped.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from convert import Entry, Sense, _cut, _e, _valid_word

# Lexin's abbreviated parts of speech, written out.
POS_WORDS = {
    'subst.': 'substantiv', 'adj.': 'adjektiv', 'adv.': 'adverb',
    'pron.': 'pronomen', 'prep.': 'preposition', 'räkn.': 'räkneord',
    'interj.': 'interjektion', 'förk.': 'förkortning',
    'konj.': 'konjunktion',
}
MAX_EXAMPLES = 3
MAX_TEXT = 300
_SPACE = re.compile(r'\s+')


def _text(el) -> str:
    """An element's own text (not its children's), cleaned."""
    if el is None or el.text is None:
        return ''
    return _SPACE.sub(' ', el.text.replace('|', '')).strip()


_ABBREV = re.compile(r'(?<!\w)(' + '|'.join(
    re.escape(a) for a in POS_WORDS) + r')(?=[\s,]|$)')


def _pos(type_: str) -> str:
    """`subst., ingen böjning` → `substantiv, ingen böjning`."""
    return _ABBREV.sub(lambda m: POS_WORDS[m.group(1)], type_.strip())


def _inflection(el) -> str:
    form, spec = _text(el), (el.get('Spec') or '').strip()
    if not form:
        return ''
    if spec == '!':
        return form + '!'
    if spec in ('att', 'har', 'är'):
        return f'{spec} {form}'
    return form


def _header(lemma) -> str:
    parts = [f'<b>{_e(_pos(lemma.get("Type") or ""))}</b>']
    head = []
    for alt in lemma.findall('Alternate'):
        if _text(alt):
            spec = (alt.get('Spec') or 'eller').strip()
            head.append(f'{spec} {_text(alt)}')
    # "–" stands for a form that doesn't exist (acne: no plural).
    inflections = [i for i in map(_inflection, lemma.findall('Inflection'))
                   if i and i != '–']
    if inflections:
        head.append(', '.join(inflections))
    if head:
        parts.append(f'<i>{_e(_cut("; ".join(head), 200))}</i>')
    phon = _text(lemma.find('Phonetic'))
    if phon:
        parts.append(_e(f'[{phon}]'))
    return f'<p>{" ".join(parts)}</p>'


def _labels(el) -> list[str]:
    out = []
    for c in el:
        if c.tag == 'Comment' and c.get('Type') in ('style', 'general'):
            out.append(_text(c))
        elif c.tag == 'Gramcom':
            out.append(_text(c))
    return [l for l in out if l]


def _body(el) -> str:
    """A Lexeme's or Cycle's labels, definition, patterns and examples."""
    labels = _labels(el)
    out = f'<i>({_e(", ".join(labels))})</i> ' if labels else ''
    defs = [_text(d) for d in el.findall('Definition') if _text(d)]
    if not defs:  # an interjection's "utrop av sorg" is a def comment
        defs = [_text(c) for c in el.findall('Comment')
                if c.get('Type') == 'def' and _text(c)]
    out = (out + _e('; '.join(defs))).rstrip()
    for x in el.findall('Explanation'):
        if _text(x):
            out += f'<br>{_e(_cut(_text(x), MAX_TEXT))}'
    for g in el.findall('Graminfo'):
        if _text(g):
            out += f'<br>{_e(_text(g))}'
    for x in el.findall('Example')[:MAX_EXAMPLES]:
        if _text(x):
            out += f'<br><i>{_e(_cut(_text(x), MAX_TEXT))}</i>'
    return out


def _lexeme(lex) -> str:
    out = _body(lex)
    cycles = [_body(c) for c in lex.findall('Cycle')]
    cycles = [c for c in cycles if c]
    if cycles:
        out += '<ol>' + ''.join(f'<li>{c}</li>' for c in cycles) + '</ol>'
    for idiom in lex.findall('Idiom'):
        phrase = _text(idiom)
        if not phrase:
            continue
        meaning = '; '.join(_text(d) for d in idiom.findall('Definition')
                            if _text(d))
        out += f'<br><b>{_e(phrase)}</b>'
        if meaning:
            out += f' – {_e(meaning)}'
    compounds = [_text(c) for c in lex.findall('Compound') if _text(c)]
    if compounds:
        out += f'<br>Sammansättningar: {_e(", ".join(compounds))}'
    antonyms = [r.get('Value', '').replace('|', '').strip()
                for r in lex.findall('Reference')
                if r.get('Type') == 'antonym']
    antonyms = [a for a in antonyms if a]
    if antonyms:
        out += f'<br>Motsats: {_e(", ".join(antonyms))}'
    # A lexeme with only idioms (går: "i går") starts with one.
    return out.removeprefix('<br>')


def entry_from(lemma) -> Entry | None:
    word = (lemma.get('Value') or '').replace('|', '').strip()
    if not _valid_word(word):
        return None
    senses = [Sense(f'<li>{s}</li>')
              for s in map(_lexeme, lemma.findall('Lexeme')) if s]
    if not senses:
        # A lemma that only says "see acne" (akne, allt): a .syn row of
        # its target when that is in the dictionary, else this article.
        for r in lemma.findall('Reference'):
            target = (r.get('Value') or '').replace('|', '').strip()
            if r.get('Type') == 'see' and _valid_word(target):
                senses.append(Sense(f'<li>se {_e(target)}</li>', [target]))
    if not senses:
        return None
    forms = []
    for idx in lemma.iter('Index'):
        if idx.get('Type') in ('prefix', 'suffix'):
            continue
        form = (idx.get('Value') or '').replace('|', '').strip()
        if (form and form != word and _valid_word(form)
                and not any(c.isspace() for c in form)
                and form not in forms):
            forms.append(form)
    return Entry(word, _header(lemma), senses, forms)


def read_entries(path) -> list[Entry]:
    """Every Lemma of swe_swe.xml at [path], in the file's order."""
    out = []
    for _, el in ET.iterparse(path):
        if el.tag == 'Article':
            for lemma in el.findall('Lemma'):
                e = entry_from(lemma)
                if e:
                    out.append(e)
            el.clear()
    return out
