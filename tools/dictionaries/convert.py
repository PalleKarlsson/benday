"""Wiktextract JSONL (kaikki.org) → StarDict articles and synonyms.

One article per headword: every part-of-speech entry of that word in the
dump's order, each as a header line and numbered senses, in a small HTML
subset (p, b, i, ol, li, br; text escaped, no attributes) that Benday's
reader and other StarDict readers can show as is.

Inflected forms point at their lemma through .syn:
- the `forms` of a lemma entry (plurals, verb forms, …; single words only);
- entries that are only "form of" / "alternative form of" senses whose
  lemma is in the dictionary are left out and become .syn rows instead
  (their article would only say "plural of X"; the reader shows X's).
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field

# Part of speech names for the English Wiktionary's extracts (no pos_title).
POS_EN = {
    'noun': 'noun', 'verb': 'verb', 'adj': 'adjective', 'adv': 'adverb',
    'name': 'proper noun', 'pron': 'pronoun', 'prep': 'preposition',
    'postp': 'postposition', 'conj': 'conjunction', 'intj': 'interjection',
    'det': 'determiner', 'article': 'article', 'num': 'numeral',
    'particle': 'particle', 'prefix': 'prefix', 'suffix': 'suffix',
    'infix': 'infix', 'interfix': 'interfix', 'affix': 'affix',
    'abbrev': 'abbreviation', 'phrase': 'phrase', 'prep_phrase':
    'prepositional phrase', 'proverb': 'proverb', 'contraction':
    'contraction', 'symbol': 'symbol', 'punct': 'punctuation',
    'adv_phrase': 'adverbial phrase', 'combining_form': 'combining form',
}

# Grammatical gender after the part of speech, in the definitions' language
# (the native editions' pos_title doesn't always carry it).
GENDER = {
    'de': {'masculine': 'm', 'feminine': 'f', 'neuter': 'n'},
    'fr': {'masculine': 'masculin', 'feminine': 'féminin'},
}

SKIP_POS = {'character', 'romanization', 'hard-redirect', 'soft-redirect'}
SKIP_FORM_TAGS = {'table-tags', 'inflection-template', 'romanization',
                  'class', 'canonical', 'transliteration', 'error-unknown-tag'}
MAX_EXAMPLE = 200
MAX_HEAD = 160
MAX_FORM_GLOSS = 150
MAX_WORD_BYTES = 255

_REF = re.compile(r'\s*\^\(\[[^\]]*\]\)')        # de: "Tisch ^([1])"
_SPACE = re.compile(r'\s+')
_ELISION = re.compile(r"^\w{1,3}[’']")          # fr: "j’ouvrage", "qu’il"
_DEFINED = re.compile(r'\s:\s+\S')            # fr: "Pluriel de X : définition"
_TAIL = re.compile(r'(\s*\([^()]*\))*[\s.:;,!?»“”"’)]*$')  # "X (“gloss”)."


def _clean(text: str) -> str:
    return _SPACE.sub(' ', _REF.sub('', text)).strip()


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0]
    return cut.rstrip(',;:') + '…'


def _e(text: str) -> str:
    return html.escape(text, quote=False)


@dataclass
class Sense:
    html: str                       # one <li>…</li>
    targets: list[str] | None = None  # lemmas when a pure "form of" sense


@dataclass
class Entry:
    word: str
    header: str
    senses: list[Sense] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)

    @property
    def form_only(self) -> bool:
        return all(s.targets for s in self.senses)

    def html(self, keep_forms: bool = True) -> str:
        items = ''.join(s.html for s in self.senses
                        if keep_forms or not s.targets)
        return f'{self.header}<ol>{items}</ol>'


def _valid_word(word: str) -> bool:
    return (bool(word) and len(word.encode('utf-8')) <= MAX_WORD_BYTES
            and not any(ord(c) < 32 for c in word))


def _header(e: dict, edition: str, lang: str) -> str:
    head = ''
    for t in e.get('head_templates') or []:
        exp = _clean(t.get('expansion') or '')
        if exp:
            head = exp
            break
    if edition == 'en':
        label = POS_EN.get(e.get('pos', ''), e.get('pos', ''))
        parts = [f'<b>{_e(label)}</b>']
        if head and head != e.get('word'):
            parts.append(f'<i>{_e(_cut(head, MAX_HEAD))}</i>')
    else:
        label = e.get('pos_title') or e.get('pos', '')
        parts = [f'<b>{_e(label)}</b>']
        # svwiktionary.py writes its own short head lines ("ett hus",
        # "gå (gick, gått)"); kaikki's native extracts' aren't used.
        if edition == 'svwikt' and head and head != e.get('word'):
            parts.append(f'<i>{_e(_cut(head, MAX_HEAD))}</i>')
        genders = [GENDER.get(lang, {}).get(t) for t in e.get('tags') or []]
        genders = [g for g in genders if g]
        if genders and not any(g.lower() in label.lower() for g in genders):
            parts.append(f'<i>{_e(", ".join(genders))}</i>')
    for s in e.get('sounds') or []:
        ipa = (s.get('ipa') or '').strip()
        if ipa:
            parts.append(_e(ipa))
            break
    return f'<p>{" ".join(parts)}</p>'


def _example(sense: dict, edition: str) -> str:
    for ex in sense.get('examples') or []:
        text = _clean(ex.get('text') or '')
        if not text:
            continue
        out = f'<br><i>{_e(_cut(text, MAX_EXAMPLE))}</i>'
        tr = _clean(ex.get('english') or ex.get('translation') or '')
        if tr and edition == 'en':
            out += f' – {_e(_cut(tr, MAX_EXAMPLE))}'
        return out
    return ''


def _form_targets(sense: dict, entry_tags: list, edition: str,
                  gloss: str) -> list[str] | None:
    refs = (sense.get('form_of') or []) + (sense.get('alt_of') or [])
    if not refs or len(gloss) > MAX_FORM_GLOSS or _DEFINED.search(gloss):
        return None
    tags = set(sense.get('tags') or [])
    if edition != 'en':
        tags |= set(entry_tags)
    if not tags & {'form-of', 'alt-of'}:
        return None
    # Only lemmas the gloss ends with ("plural of X", "… de X."): the
    # French extract also links words from inside real definitions.
    tail = _TAIL.sub('', gloss)
    words = [r.get('word', '').strip() for r in refs]
    words = [w for w in words if _valid_word(w) and tail.endswith(w)
             and (len(tail) == len(w) or not tail[-len(w) - 1].isalnum())]
    return words or None


def entry_from(e: dict, edition: str, lang: str) -> Entry | None:
    """One wiktextract entry (a word's part of speech) → Entry, or None
    when it has nothing to show."""
    word = (e.get('word') or '').strip()
    if not _valid_word(word) or e.get('pos') in SKIP_POS:
        return None
    if e.get('lang_code') not in (None, lang):
        return None
    entry_tags = e.get('tags') or []
    top: list[dict] = []  # {'key', 'html', 'children', 'targets'}
    for s in e.get('senses') or []:
        glosses = [g for g in (s.get('glosses') or []) if g and g.strip()]
        if not glosses or 'no-gloss' in (s.get('tags') or []):
            continue
        if edition == 'en':
            raw = s.get('raw_glosses') or glosses
            gloss = _clean(raw[-1])
            qual = ''
        else:
            gloss = _clean(glosses[-1])
            raw_tags = [_clean(t) for t in s.get('raw_tags') or [] if t]
            qual = (f'<i>({_e(", ".join(raw_tags))})</i> '
                    if raw_tags else '')
        if not gloss:
            continue
        targets = _form_targets(s, entry_tags, edition, gloss)
        body = qual + _e(gloss)
        if not targets:
            body += _example(s, edition)
        parent = _clean(glosses[0]) if len(glosses) > 1 else None
        if parent:
            if top and top[-1]['key'] == parent:
                top[-1]['children'].append(body)
            else:
                top.append({'key': parent, 'html': _e(parent),
                            'children': [body], 'targets': None})
        else:
            top.append({'key': _clean(glosses[0]), 'html': body,
                        'children': [], 'targets': targets})
    if not top:
        return None
    senses = []
    for t in top:
        inner = t['html']
        if t['children']:
            inner += '<ol>' + ''.join(f'<li>{c}</li>'
                                      for c in t['children']) + '</ol>'
        senses.append(Sense(f'<li>{inner}</li>',
                            t['targets'] if not t['children'] else None))
    forms = []
    for f in e.get('forms') or []:
        if set(f.get('tags') or []) & SKIP_FORM_TAGS:
            continue
        form = (f.get('form') or '').strip().rstrip('!').strip()
        if (form and form != word and _valid_word(form)
                and not any(c.isspace() for c in form)
                and any(c.isalpha() for c in form)
                and not _ELISION.match(form)):
            forms.append(form)
    return Entry(word, _header(e, edition, lang), senses, forms)


def convert_lines(lines: list[bytes], edition: str, lang: str) -> list[Entry]:
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        entry = entry_from(json.loads(line), edition, lang)
        if entry:
            out.append(entry)
    return out


@dataclass
class Built:
    articles: list[tuple[str, str]]
    synonyms: list[tuple[str, str]]
    entries: int
    dropped_forms: int


def assemble(entries) -> Built:
    """Entries (in dump order) → one article per headword plus .syn rows."""
    entries = list(entries)
    lemmas = {e.word for e in entries if not e.form_only}
    by_word: dict[str, list[str]] = {}
    syn: set[tuple[str, str]] = set()
    dropped = 0
    for e in entries:
        targets = [t for s in e.senses if s.targets for t in s.targets]
        if e.form_only and targets and all(
                any(t in lemmas for t in s.targets) for s in e.senses):
            dropped += 1
        else:
            parts = by_word.setdefault(e.word, [])
            h = e.html()
            if h not in parts:
                parts.append(h)
        for t in targets:
            if t in lemmas and t != e.word:
                syn.add((e.word, t))
        if not e.form_only:
            for f in e.forms:
                syn.add((f, e.word))
    articles = [(w, ''.join(p)) for w, p in by_word.items()]
    synonyms = sorted((f, h) for f, h in syn if h in by_word and f != h)
    return Built(articles, synonyms, len(entries), dropped)
