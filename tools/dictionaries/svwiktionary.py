"""Swedish Wiktionary dump (svwiktionary-…-pages-articles.xml.bz2) →
wiktextract-like dicts for convert.entry_from (edition `svwikt`).

kaikki.org publishes no extract of sv.wiktionary, and wiktextract's sv
extractor is a stub, so this reads the dump's wikitext itself (standard
library only). It takes the `==Svenska==` section of every main-namespace
page and, per part-of-speech heading (`===Substantiv===`, …), the head
template, the pronunciation and the definition lines:

- `#` lines are senses (`##` sub-senses), the first simple `#:''…''` line
  under one its example; quotations (`{{citat}}`), synonyms, phrases and
  the like (`#:{{…}}`), translations and etymology are left out.
- `{{böjning|sv|<pos>|<lemma>}}` ("böjningsform av …") and
  `{{gammalstavning|sv|…|<modern>}}` ("äldre stavning av …") are "form of"
  senses: convert.assemble turns pages made only of them into .syn rows
  when their lemma is in the dictionary.
- `{{tagg|…|text=…}}` at a sense's start gives its labels; `kat=` only
  categorises and is dropped. `{{avledning|sv|<base>|<pos>}}` renders as
  "avledning av …"; a few others as text (see _render_template); unknown
  templates are dropped.
- The head template's name gives the noun's gender (`sv-subst-n-…` en,
  `sv-subst-t-…` ett) and its `pret=`/`sup=` (verbs) or `komp=`/`sup=`
  (adjectives) a short head line: `gå (gick, gått)`.
"""
from __future__ import annotations

import bz2
import html
import re
import xml.etree.ElementTree as ET

# Part-of-speech headings → wiktextract's pos codes (convert shows the
# heading itself, pos_title). Headings not listed (Källor, Externa länkar)
# aren't parts of speech and are skipped.
POS = {
    'Substantiv': 'noun', 'Verb': 'verb', 'Adjektiv': 'adj',
    'Adverb': 'adv', 'Förkortning': 'abbrev', 'Interjektion': 'intj',
    'Affix': 'affix', 'Pronomen': 'pron', 'Fras': 'phrase',
    'Räkneord': 'num', 'Preposition': 'prep', 'Förled': 'prefix',
    'Ordspråk': 'proverb', 'Efterled': 'suffix', 'Konjunktion': 'conj',
    'Verbpartikel': 'particle', 'Talesätt': 'phrase',
    'Subjunktion': 'conj', 'Artikel': 'article', 'Postposition': 'postp',
    'Cirkumposition': 'postp', 'Infinitivmärke': 'particle',
    'Partikel': 'particle', 'Prepositionsfras': 'prep_phrase',
    'Pronomen / Adjektiv': 'pron', 'Tecken': 'character',
}

# Templates that are whole "form of" senses: (gloss prefix, tag).
_FORM_TEMPLATES = {'böjning': ('böjningsform av', 'form-of'),
                   'gammalstavning': ('äldre stavning av', 'alt-of')}
_AVLEDNING_POS = {'adj': 'adjektivet', 'subst': 'substantivet',
                  'verb': 'verbet', 'adv': 'adverbet'}
_ORDFORM = {'perfpart': 'perfektparticip av', 'prespart':
            'presensparticip av'}
_LABEL_TEMPLATES = {'dödform': 'föråldrat', 'oböjl': 'oböjligt',
                    'oräkn': 'oräknebart'}

_SECTION = re.compile(r'^==\s*Svenska\s*==\s*$', re.M)
_LEVEL2 = re.compile(r'^==[^=].*$', re.M)
_HEADING = re.compile(r'^(={3,})\s*([^=].*?)\s*\1\s*$')
_COMMENT = re.compile(r'<!--.*?-->', re.S)
_REF = re.compile(r'<ref\b[^>/]*/>|<ref\b[^>]*>.*?</ref>', re.S | re.I)
_NOWIKI = re.compile(r'<nowiki>(.*?)</nowiki>', re.S | re.I)
_MATH = re.compile(r'<math\b[^>]*>(.*?)</math>', re.S | re.I)
_TAG = re.compile(r'</?[a-zA-Z][^>]*>')
_EXT_LINK = re.compile(r'\[(?:https?:)?//[^\s\]]+\s+([^\]]*)\]|'
                       r'\[(?:https?:)?//[^\s\]]+\]')
_QUOTES = re.compile(r"'{2,}")
_SPACE = re.compile(r'\s+')
_HAND_LABEL = re.compile(r"^\(''([^'()]+)''\)\s*")


# --- dump ------------------------------------------------------------------

def iter_pages(path):
    """(title, Swedish section) for every main-namespace page of the dump
    at [path] (.xml.bz2 or .xml) that has one."""
    opener = bz2.open if str(path).endswith('.bz2') else open
    with opener(path, 'rb') as f:
        ns = None
        for _, el in ET.iterparse(f):
            if not el.tag.endswith('}page') and el.tag != 'page':
                continue
            if ns is None:
                ns = el.tag[:-len('page')]
            if el.findtext(ns + 'ns') == '0':
                text = el.findtext(f'{ns}revision/{ns}text') or ''
                section = swedish_section(text)
                if section is not None:
                    yield el.findtext(ns + 'title') or '', section
            el.clear()


def swedish_section(text: str) -> str | None:
    m = _SECTION.search(text)
    if not m:
        return None
    rest = text[m.end():]
    end = _LEVEL2.search(rest)
    return rest[:end.start()] if end else rest


# --- wikitext --------------------------------------------------------------

def _find_close(s: str, start: int) -> int:
    """Index just past the `}}` closing the `{{` at [start], or -1."""
    depth, i = 0, start
    while i < len(s) - 1:
        two = s[i:i + 2]
        if two == '{{':
            depth += 1
            i += 2
        elif two == '}}':
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return -1


def _split_params(inner: str) -> list[str]:
    """`name|a|b=c` split at top-level pipes (not inside [[…]] or {{…}})."""
    parts, depth_t, depth_l, cur, i = [], 0, 0, [], 0
    while i < len(inner):
        two = inner[i:i + 2]
        if two in ('{{', '}}', '[[', ']]'):
            depth_t += (two == '{{') - (two == '}}')
            depth_l += (two == '[[') - (two == ']]')
            cur.append(two)
            i += 2
            continue
        c = inner[i]
        if c == '|' and depth_t == 0 and depth_l == 0:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append(''.join(cur))
    return parts


class Template:
    def __init__(self, raw: str):
        parts = _split_params(raw[2:-2])
        self.name = parts[0].strip()
        self.args: list[str] = []
        self.kw: dict[str, str] = {}
        for p in parts[1:]:
            k, eq, v = p.partition('=')
            if eq and re.fullmatch(r'[\w\- ]+', k.strip()):
                self.kw[k.strip()] = v.strip()
            else:
                self.args.append(p.strip())

    def arg(self, i: int) -> str:
        return self.args[i] if i < len(self.args) else ''


def templates(s: str) -> list[tuple[int, int, Template]]:
    """Top-level templates in [s]: (start, end, template)."""
    out, i = [], 0
    while True:
        i = s.find('{{', i)
        if i < 0:
            return out
        end = _find_close(s, i)
        if end < 0:
            return out
        out.append((i, end, Template(s[i:end])))
        i = end


def _link(m: re.Match) -> str:
    target, _, label = m.group(1).partition('|')
    t = target.strip().lower()
    if t.startswith(('fil:', 'file:', 'bild:', 'kategori:', 'category:',
                     'image:')):
        return ''
    if label:
        return label
    return target.split('#', 1)[0] if not target.startswith('#') \
        else target.rsplit('#', 1)[-1]


_LINK = re.compile(r'\[\[([^\[\]]*)\]\]')


def plain(s: str) -> str:
    """Wikitext → plain text: templates rendered (_render_template), links
    to their text, markup and tags dropped, entities decoded."""
    s = _COMMENT.sub('', s)
    s = _REF.sub('', s)
    # nowiki and TeX (<math>) are literal: no templates or links inside.
    for literal in (_NOWIKI, _MATH):
        s = literal.sub(lambda m: m.group(1).replace('{', '&#123;')
                        .replace('}', '&#125;').replace('[', '&#91;')
                        .replace(']', '&#93;').replace('|', '&#124;'), s)
    out, pos = [], 0
    for start, end, t in templates(s):
        out.append(s[pos:start])
        out.append(_render_template(t))
        pos = end
    out.append(s[pos:])
    s = ''.join(out)
    s = _LINK.sub(_link, s)
    s = _EXT_LINK.sub(lambda m: m.group(1) or '', s)
    s = _QUOTES.sub('', s)
    s = _TAG.sub('', s)
    s = html.unescape(s)
    return _SPACE.sub(' ', s).strip()


def _labels(t: Template) -> list[str]:
    labels = [plain(a) for a in t.args if a]
    if t.kw.get('text'):
        labels.append(plain(t.kw['text']))
    return [l for l in labels if l]


def _render_template(t: Template) -> str:
    name = t.name
    if name in _FORM_TEMPLATES:
        return f'{_FORM_TEMPLATES[name][0]} {plain(t.args[-1])}' \
            if t.args else ''
    if name == 'avledning':
        base = plain(t.arg(1))
        if t.kw.get('ordform') in _ORDFORM:
            return f'{_ORDFORM[t.kw["ordform"]]} {base}'
        pos = _AVLEDNING_POS.get(t.arg(2))
        return f'avledning av {pos} {base}' if pos else f'avledning av {base}'
    if name == 'tagg':
        labels = _labels(t)
        return f'({", ".join(labels)})' if labels else ''
    if name in _LABEL_TEMPLATES:
        return f'({_LABEL_TEMPLATES[name]})'
    if name == 'led':
        kind = {'f': 'förled', 'e': 'efterled'}.get(t.arg(1), 'led')
        return f'{kind} till {plain(t.arg(2))}'
    if name in ('länka', 'inget uppslag', 'l', 'länk'):
        return plain(t.args[-1]) if t.args else ''
    if name == 'övrigatecken':
        return plain(t.args[-1]) if t.args else ''
    return ''  # ?, färg, källa-*, konstr, jämför and the rest


# --- a page's Swedish section ---------------------------------------------

def _head_line(t: Template, word: str) -> tuple[str, list[str], list[str]]:
    """(head line, tags, forms) from a `{{sv-…}}` head template."""
    parts = t.name.split('-')
    kind = parts[1] if len(parts) > 1 else ''
    tags, forms, extra = [], [], []

    def first(value: str) -> str:
        return plain(value).split(',')[0].strip(' ()')

    if kind == 'subst' and len(parts) > 2 and parts[2] in ('n', 't'):
        tags.append('common' if parts[2] == 'n' else 'neuter')
        if 'namn' in parts:
            return '', tags, forms
        article = 'en' if parts[2] == 'n' else 'ett'
        return f'{article} {word}', tags, forms
    if kind == 'verb':
        pret, sup = first(t.kw.get('pret', '')), first(t.kw.get('sup', ''))
        if (not pret and not sup and t.name.startswith('sv-verb-ar')
                and word.endswith('a') and ' ' not in word
                and not set(t.kw) & {'rot', 'grundform', 'partikel', 'inf'}):
            pret, sup = word + 'de', word + 't'
        extra = [f for f in (pret, sup) if f]
    elif kind == 'adj':
        extra = [f for f in (first(t.kw.get('komp', '')),
                             first(t.kw.get('sup', ''))) if f]
    forms = [f for f in extra if ' ' not in f]
    if extra:
        return f'{word} ({", ".join(extra)})', tags, forms
    return '', tags, forms


def _ipa(line: str) -> str:
    for _, _, t in templates(line):
        if t.name == 'uttal' and t.kw.get('ipa'):
            return plain(t.kw['ipa'])
    return ''


def _form_refs(text: str) -> list[tuple[str, str, str]] | None:
    """A definition that is only form templates (`{{böjning|…}}`, maybe
    `; `-separated, as on `war`) → (gloss, tag, lemma) per template."""
    found = templates(text)
    if not found:
        return None
    rest, pos, out = [], 0, []
    for start, end, t in found:
        rest.append(text[pos:start])
        pos = end
        if t.name not in _FORM_TEMPLATES or not t.args:
            return None
        lemma = plain(t.args[-1])
        prefix, tag = _FORM_TEMPLATES[t.name]
        out.append((f'{prefix} {lemma}', tag, lemma))
    rest.append(text[pos:])
    if re.sub(r'[\s;,.]', '', ''.join(rest)):
        return None
    return out


def _sense(text: str) -> list[dict]:
    """One `#` line's text → senses (several when it is only form
    templates)."""
    refs = _form_refs(text)
    if refs:
        return [{'glosses': [g], 'tags': [tag],
                 ('form_of' if tag == 'form-of' else 'alt_of'):
                     [{'word': lemma}]}
                for g, tag, lemma in refs]
    labels = []
    body = text.lstrip()
    # Leading {{tagg}}/{{dödform}}/… are the sense's labels.
    while body.startswith('{{'):
        end = _find_close(body, 0)
        if end < 0:
            break
        t = Template(body[:end])
        if t.name == 'tagg':
            labels += _labels(t)
        elif t.name in _LABEL_TEMPLATES:
            labels.append(_LABEL_TEMPLATES[t.name])
        else:
            break
        body = body[end:].lstrip()
    # A leading "(''äldre lagspråk'')" is a label written by hand.
    m = _HAND_LABEL.match(body)
    if m:
        labels.append(plain(m.group(1)))
        body = body[m.end():]
    gloss = plain(body).lstrip(';,: ').strip()
    if not gloss:
        return []
    sense = {'glosses': [gloss]}
    if labels:
        sense['raw_tags'] = labels
    return [sense]


def _example(text: str) -> str | None:
    """A `#:` line's text as an example, when it is a plain italic
    sentence (no templates)."""
    text = text.strip()
    if not text.startswith("''") or '{{' in text:
        return None
    ex = plain(text)
    return ex or None


def parse_section(title: str, section: str) -> list[dict]:
    """A page's Swedish section → one dict per part of speech (and per head
    block: `hus` [1] and [2] are two)."""
    entries: list[dict] = []
    pos_title = None
    cur: dict | None = None
    in_defs = False  # inside a POS heading, before its level-4 sections

    def new_entry():
        nonlocal cur
        cur = {'word': title, 'lang_code': 'sv', 'pos': POS[pos_title],
               'pos_title': pos_title, 'senses': [], 'forms': [],
               'tags': [], 'sounds': [], 'head_templates': []}
        entries.append(cur)

    last_top: dict | None = None
    last_sense: dict | None = None
    for line in section.split('\n'):
        h = _HEADING.match(line.strip())
        if h:
            level, name = len(h.group(1)), h.group(2)
            if level == 3:
                pos_title = name if name in POS else None
                in_defs = pos_title is not None
                cur = last_top = last_sense = None
                if in_defs:
                    new_entry()
            else:
                in_defs = False
            continue
        if not in_defs:
            continue
        if line.startswith('{{sv-'):
            end = _find_close(line, 0)
            if end > 0:
                if cur['senses']:
                    new_entry()
                    last_top = last_sense = None
                head, tags, forms = _head_line(Template(line[:end]), title)
                # Head templates in a row are one block whose senses they
                # share (vad: ett vad 1–3, en vad 4–5): one head line.
                heads = cur['head_templates']
                if head and not heads:
                    heads.append({'expansion': head})
                elif head and head not in heads[0]['expansion'].split('; '):
                    heads[0]['expansion'] += '; ' + head
                cur['tags'] += [t for t in tags if t not in cur['tags']]
                cur['forms'] += [{'form': f} for f in forms]
            continue
        if line.startswith('*') and '{{uttal' in line:
            ipa = _ipa(line)
            if ipa and not cur['sounds']:
                cur['sounds'].append({'ipa': f'/{ipa}/'})
            continue
        if line.startswith('##') and not line.startswith('##:'):
            if last_top is None:
                continue
            for s in _sense(line[2:]):
                s['glosses'] = last_top['glosses'][:1] + s['glosses']
                cur['senses'].append(s)
                last_sense = s
            continue
        if line.startswith('#') and line[1:2] not in (':', '*', '#', ';'):
            senses = _sense(line[1:])
            for s in senses:
                cur['senses'].append(s)
            if senses:
                last_top = last_sense = senses[-1]
            continue
        if line.startswith(('#:', '##:')) and last_sense is not None \
                and not last_sense.get('examples') \
                and not last_sense.get('form_of'):
            ex = _example(line.lstrip('#:'))
            if ex:
                last_sense['examples'] = [{'text': ex}]
    return [e for e in entries if e['senses']]


def parse_pages(pages) -> list[dict]:
    """[(title, section)] → dicts (a batch, for a worker pool)."""
    out = []
    for title, section in pages:
        out.extend(parse_section(title, section))
    return out
