"""Turn downloaded bytes into plain text. Downloads are untrusted data: parsed, never executed."""
import codecs
import logging
import re
import warnings
from bisect import bisect_left
from html.parser import HTMLParser
from io import BytesIO

_SKIPPED = {"script", "style", "noscript", "template", "svg"}
# Elements that run on within a line emit nothing; every other element, including unknown and
# custom ones, is a block and gets a line break at its start and at its end.
_INLINE = {"a", "abbr", "acronym", "b", "bdi", "bdo", "big", "cite", "code", "data", "del", "dfn",
           "em", "font", "i", "ins", "kbd", "label", "mark", "nobr", "q", "s", "samp", "small",
           "span", "strike", "strong", "sub", "sup", "time", "tt", "u", "var", "wbr"}
_MIN_CHARS_PER_PAGE = 20

# --- text a page hides from its readers (rulings HG9, HG15) -------------------------------------------------------
# The copy's text follows what a browser without scripts shows. An element hides itself by plain markup when it has the
# `hidden` attribute, an inline style with `display:none` or `visibility:hidden`, or is a `<dialog>` without `open`.
# `aria-hidden="true"` hides nothing from a sighted reader (it only keeps text from a screen reader), so it is not one. Its text is left out until the element ends, and it ends where a browser ends it: the
# open elements are followed as the HTML standard's tree construction follows them (an element whose end tag may be
# left out ends where the standard ends it; an end tag closes what it closes in a browser; an unclosed element ends with
# its parent). Where the rules below do not reach, more text is left out, never less.
_VOID = frozenset({"area", "base", "basefont", "bgsound", "br", "col", "embed", "frame", "hr", "image", "img", "input",
                   "keygen", "link", "meta", "param", "source", "track", "wbr"})
_FORMATTING = frozenset({"a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike", "strong", "tt",
                         "u"})
_SPECIAL = frozenset({"address", "applet", "area", "article", "aside", "base", "basefont", "bgsound", "blockquote",
                      "body", "br", "button", "caption", "center", "col", "colgroup", "dd", "details", "dialog", "dir",
                      "div", "dl", "dt", "embed", "fieldset", "figcaption", "figure", "footer", "form", "frame",
                      "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr", "html",
                      "iframe", "img", "input", "keygen", "li", "link", "listing", "main", "marquee", "menu", "meta",
                      "nav", "noembed", "noframes", "object", "ol", "p", "param", "plaintext", "pre", "search",
                      "section", "select", "source", "summary", "table", "tbody", "td", "textarea", "tfoot", "th",
                      "thead", "title", "tr", "track", "ul", "wbr", "xmp", "mi", "mo", "mn", "ms", "mtext",
                      "annotation-xml"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# The start tags that close an open <p>, by the standard's "in body" rules (and <table> outside quirks mode).
_CLOSES_P = frozenset({"address", "article", "aside", "blockquote", "center", "details", "dialog", "dir", "div", "dl",
                       "fieldset", "figcaption", "figure", "footer", "header", "hgroup", "main", "menu", "nav", "ol",
                       "p", "search", "section", "summary", "ul", "pre", "listing", "form", "li", "dd", "dt",
                       "plaintext", "hr", "xmp"}) | _HEADINGS
# End tags that close the nearest open element of their name and everything open inside it, when it is in scope.
_SCOPED_END = frozenset({"address", "article", "aside", "blockquote", "button", "center", "details", "dialog", "dir",
                         "div", "dl", "fieldset", "figcaption", "figure", "footer", "header", "hgroup", "listing",
                         "main", "menu", "nav", "ol", "pre", "search", "section", "summary", "ul", "applet", "marquee",
                         "object", "dd", "dt"})
_TABLE_PARTS = frozenset({"caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr"})
_TABLE_SECTIONS = frozenset({"tbody", "thead", "tfoot"})
# What a browser's end tag does not reach past. A select is added: inside it a browser ignores most end tags.
_LIMITS = frozenset({"applet", "caption", "html", "table", "td", "th", "marquee", "object", "template", "select",
                     "mi", "mo", "mn", "ms", "mtext", "annotation-xml"})
_TABLE_LIMITS = frozenset({"html", "table", "template"})
# Elements whose content a browser reads as plain text, so a tag inside them is no tag: shown, or (the second set) not
# shown at all. <plaintext> never ends.
_RAW_SHOWN = frozenset({"textarea", "title", "xmp", "plaintext"})
_RAW_HIDDEN = frozenset({"iframe", "noembed", "noframes"})
# Groups of open elements that a rule asks about as one: any special element; a special element that stops the search
# for an open list item; anything in a select that is not an option.
_ANY_SPECIAL, _ITEM_STOP, _NOT_OPTION = "#special", "#item-stop", "#not-option"
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _style_hides(style: str) -> bool:
    """Whether an inline style holds `display:none` or `visibility:hidden`, in any case, with any spaces or comments."""
    text = "".join(_CSS_COMMENT.sub("", style).split()).lower()
    return any(declaration.removesuffix("!important") in ("display:none", "visibility:hidden")
               for declaration in text.split(";"))


def _hides(tag: str, attrs) -> bool:
    """Whether a start tag hides its element from a reader of the page."""
    if tag == "dialog" and not any(name == "open" for name, _ in attrs):   # a closed dialog is not shown
        return True
    for name, value in attrs:
        if name == "hidden":
            return True
        if name == "style" and _style_hides(value or ""):
            return True
    return False


class NoTextLayer(Exception):
    """The PDF opens but holds (almost) no text, for example a scan."""


class PdfAddOnMissing(Exception):
    """The PDF library (pypdf) is not installed in the Python that runs, so no PDF can be read."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        # The open elements, outermost first, each [name, whether it hides, its number]. Elements are numbered as they
        # open, so the numbers rise from the outermost to the innermost.
        self._open: list[list] = []
        self._opened = 0                 # how many elements were opened so far
        # For each name, and for each group of names, the numbers of the open elements that carry it, innermost last.
        # Every question "is one open, and does something stand above it" is answered from the last numbers alone, so
        # the time to read a page does not grow with how deeply its elements are nested.
        self._where: dict[str, list[int]] = {}
        self._hiding = 0                 # how many of the open elements hide
        self._again: dict[str, int] = {}   # hidden formatting elements a browser opens again until their end tag
        self._again_count = 0
        self._raw: tuple[str, bool] | None = None   # inside plain text: (the element's name, whether it is shown)
        self._standards_mode = False     # <!DOCTYPE html>: a <table> closes an open <p>
        self.page_hidden = False         # a hidden <html> or <body>: nothing of the page counts

    def _quiet(self) -> bool:
        return (bool(self._skip_depth or self._hiding or self._again_count)
                or (self._raw is not None and not self._raw[1]))

    # --- the open elements ---------------------------------------------------------------------------------------

    @staticmethod
    def _keys(tag: str) -> tuple[str, ...]:
        """The name of an element and the groups it belongs to."""
        keys = [tag]
        if tag in _SPECIAL:
            keys.append(_ANY_SPECIAL)
            if tag not in ("address", "div", "p"):
                keys.append(_ITEM_STOP)
        if tag not in ("option", "optgroup"):
            keys.append(_NOT_OPTION)
        return tuple(keys)

    def _nearest(self, names) -> int:
        """The number of the innermost open element named in `names` (a name or a group), or 0 when none is open."""
        return max((numbers[-1] for numbers in map(self._where.get, names) if numbers), default=0)

    def _is_open(self, name: str) -> bool:
        return bool(self._where.get(name))

    def _index(self, number: int) -> int:
        """The position among the open elements of the element with this number."""
        return bisect_left(self._open, number, key=lambda entry: entry[2])

    def _push(self, tag: str, hides: bool) -> None:
        self._opened += 1
        self._open.append([tag, hides, self._opened])
        for key in self._keys(tag):
            self._where.setdefault(key, []).append(self._opened)
        self._hiding += hides

    def _forget(self, entry: list) -> None:
        """Take the innermost open element out of the numbers kept by name and by group."""
        for key in self._keys(entry[0]):
            self._where[key].pop()
        self._hiding -= entry[1]

    def _take_out(self, index: int) -> tuple[str, bool]:
        """Take the one element at `index` out of the open elements; what is open inside it stays open."""
        entry = self._open.pop(index)
        for key in self._keys(entry[0]):   # others of its name or group may stand above it
            numbers = self._where[key]
            del numbers[bisect_left(numbers, entry[2])]
        self._hiding -= entry[1]
        return entry[0], entry[1]

    def _find(self, names, limits, group: str | None = None) -> int | None:
        """The position of the nearest open element named in `names`, unless an element named in `limits`, or one of
        the `group`, stands above it."""
        number = self._nearest(names)
        if not number or self._nearest(limits) > number or (group and self._nearest((group,)) > number):
            return None
        return self._index(number)

    def _add_again(self, name: str) -> None:
        self._again[name] = self._again.get(name, 0) + 1
        self._again_count += 1

    def _pop(self, index: int, own: bool = False) -> None:
        """Close the element at `index` and everything open inside it. A hidden formatting element closed from outside
        (not by its own end tag) is opened again by a browser, so it keeps hiding until its own end tag."""
        for position in range(len(self._open) - 1, index - 1, -1):   # innermost first
            entry = self._open[position]
            self._forget(entry)
            if entry[1] and entry[0] in _FORMATTING and not (own and position == index):
                self._add_again(entry[0])
        del self._open[index:]

    def _close_p(self) -> None:
        index = self._find({"p"}, _LIMITS | {"button"})
        if index is not None:
            self._pop(index)

    def _close_cell(self) -> None:
        index = self._find({"td", "th"}, _TABLE_LIMITS)
        if index is not None:
            self._pop(index)

    def _in_table(self) -> bool:
        return self._is_open("table")

    def _start_closes(self, tag: str) -> None:
        """Close what this start tag closes in a browser before the new element opens."""
        current = self._open[-1][0] if self._open else None
        if tag in _CLOSES_P or (tag == "table" and self._standards_mode):
            if tag in ("li", "dd", "dt"):   # the standard's loop: close an open item of the same list
                index = self._find(("li",) if tag == "li" else ("dd", "dt"), (), _ITEM_STOP)
                if index is not None:
                    self._pop(index)
            self._close_p()
            if tag in _HEADINGS and self._open and self._open[-1][0] in _HEADINGS:
                self._pop(len(self._open) - 1)
        elif tag == "button":
            index = self._find({"button"}, _LIMITS)
            if index is not None:
                self._pop(index)
        elif tag in ("option", "optgroup"):
            if current == "option":
                self._pop(len(self._open) - 1)
            if tag == "optgroup" and self._open and self._open[-1][0] == "optgroup":
                self._pop(len(self._open) - 1)
        elif tag in ("select", "input", "keygen", "textarea") and self._find({"select"}, _TABLE_LIMITS) is not None:
            self._pop(self._find({"select"}, _TABLE_LIMITS))
        if tag in ("td", "th"):
            self._close_cell()
        elif tag == "tr":
            self._close_cell()
            index = self._find({"tr"}, _TABLE_LIMITS)
            if index is not None:
                self._pop(index)
        elif tag in _TABLE_SECTIONS or tag in ("caption", "colgroup", "col"):
            self._close_cell()
            table = self._find({"table"}, {"html", "template"})
            if table is not None and len(self._open) > table + 1:   # back to the table itself
                self._pop(table + 1)
        elif tag == "table" and current in ("table", "tbody", "thead", "tfoot", "tr"):
            self._pop(self._find({"table"}, {"html", "template"}))   # a table directly in a table closes the first

    def _end_closes(self, tag: str) -> int | None:
        """The position of the open element this end tag closes in a browser, or None when a browser ignores it."""
        if tag == "p":
            return self._find({"p"}, _LIMITS | {"button"})
        if tag == "li":
            return self._find({"li"}, _LIMITS | {"ol", "ul"})
        if tag in _HEADINGS:
            return self._find(_HEADINGS, _LIMITS)
        if tag in _SCOPED_END:
            return self._find({tag}, _LIMITS)
        if tag in _TABLE_PARTS or tag == "table":
            return self._find({tag}, _TABLE_LIMITS)
        if tag in ("option", "optgroup"):
            return len(self._open) - 1 if self._open and self._open[-1][0] == tag else None
        if tag == "select":   # only with nothing but options open inside it
            return self._find({"select"}, {"html", "template"}, _NOT_OPTION)
        if tag in _FORMATTING:
            return self._find({tag}, _LIMITS)
        return self._find((tag,), (), _ANY_SPECIAL)   # any other element: as far as no special element stands

    # --- the parser's events -------------------------------------------------------------------------------------

    def handle_decl(self, decl):
        self._standards_mode = " ".join(decl.split()).lower() == "doctype html"

    def handle_starttag(self, tag, attrs):
        if self._raw is not None:   # inside plain text a tag is no tag
            return
        if tag in _SKIPPED:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        hides = _hides(tag, attrs)
        if tag in ("html", "body", "head"):   # a browser puts these attributes on the page itself, wherever they stand
            self.page_hidden = self.page_hidden or (hides and tag != "head")
            if not self._quiet():
                self.parts.append("\n")
            return
        if tag == "form" and self._is_open("form"):
            return                         # a form inside a form is ignored by a browser
        if tag in _TABLE_PARTS and not self._in_table():   # a browser ignores a table part outside a table
            if not self._quiet() and tag not in _INLINE:
                self.parts.append("\n")
            return
        self._start_closes(tag)
        if tag not in _VOID:
            self._push(tag, hides)
            if tag in _RAW_SHOWN or tag in _RAW_HIDDEN:
                self._raw = (tag, tag in _RAW_SHOWN)
        if not hides and not self._quiet() and tag not in _INLINE:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        # A browser ignores the closing slash of an HTML element: <div hidden/> opens a div, <br/> is a <br>. A
        # self-closed <script/> hides nothing.
        if tag not in _SKIPPED:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self._raw is not None:
            if tag == self._raw[0] and tag != "plaintext":   # the end of the plain text; <plaintext> never ends
                self._raw = None
                own_hiding = self._open[-1][1]
                self._pop(len(self._open) - 1, own=True)
                if not own_hiding and not self._quiet() and tag not in _INLINE:
                    self.parts.append("\n")
            return
        if tag in _SKIPPED:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        own_hiding = False
        if tag in _FORMATTING and self._again.get(tag) and self._find({tag}, _LIMITS) is None:
            self._again[tag] -= 1     # the end tag of a formatting element a browser was opening again
            self._again_count -= 1
        elif tag == "form":
            index = self._find({"form"}, _LIMITS)
            if index is not None:      # a browser takes only the form out; what is open inside it stays inside it
                name, hides = self._take_out(index)
                if hides:
                    for entry in self._open[index:]:
                        self._hiding += not entry[1]
                        entry[1] = True
                own_hiding = hides
        elif tag not in ("html", "body", "head", "br"):
            index = self._end_closes(tag)
            if index is not None:
                own_hiding = self._open[index][1]
                if tag in _FORMATTING and self._nearest((_ANY_SPECIAL,)) > self._open[index][2]:
                    # a browser moves what follows into a copy of it (the standard's adoption of a formatting element)
                    name, hides = self._take_out(index)
                    if hides:
                        self._add_again(name)
                else:
                    self._pop(index, own=True)
        if not own_hiding and not self._quiet() and tag not in _INLINE:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._quiet():
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # broken markup: keep whatever was read so far
        pass
    if parser.page_hidden:   # a hidden <html> or <body> hides the whole page, whatever came before the tag
        return ""
    lines = [line.strip() for line in "".join(parser.parts).split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines) + "\n" if lines else ""


def pdf_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # imported here so `radar doctor` can report a missing install
    except ImportError as exc:
        raise PdfAddOnMissing("pypdf is not installed") from exc

    pypdf_log = logging.getLogger("pypdf")
    previous_level = pypdf_log.level
    pypdf_log.setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                reader = PdfReader(BytesIO(data))
                if reader.is_encrypted and not reader.decrypt(""):
                    raise ValueError("encrypted")
                pages = [page.extract_text() or "" for page in reader.pages]
            except Exception as exc:
                raise ValueError("not a readable PDF") from exc
    finally:
        pypdf_log.setLevel(previous_level)
    chars = sum(len(re.sub(r"\s", "", page)) for page in pages)
    if not pages or chars / len(pages) < _MIN_CHARS_PER_PAGE:
        raise NoTextLayer("the PDF has no usable text layer")
    return "\n\n".join(pages)


def _media_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def sniff_kind(data: bytes, content_type: str | None) -> str:
    head = data[:1024]
    if b"%PDF-" in head:
        return "pdf"
    lowered = head.lower()
    media = _media_type(content_type)
    if b"<!doctype html" in lowered or b"<html" in lowered or media in ("text/html", "application/xhtml+xml"):
        return "html"
    if media == "text/plain":
        return "text"
    return "unknown"


# The only character sets a page or a header may choose, as canonical Python codec names: plain text encodings that
# browsers accept and that leave ASCII bytes as they are. A list and not "whatever Python knows", because Python also
# decodes utf-7, escape sequences, EBCDIC, UTF-16 and UTF-32, which turn the ASCII bytes of a page into other text, so
# the quote check would see words that a reader of the page never sees.
TEXT_ENCODINGS = frozenset(
    {"utf-8", "utf-8-sig", "ascii", "iso8859-1", "koi8-r", "koi8-u", "shift_jis", "cp932", "euc_jp", "euc_kr",
     "cp949", "gbk", "gb2312", "gb18030", "big5"}
    | {f"cp{number}" for number in range(1250, 1259)}
    | {f"iso8859-{number}" for number in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16)})
_AS_WINDOWS_1252 = {"ascii", "iso8859-1"}   # browsers read both as Windows-1252


def _decode_cp1252(data: bytes) -> str:
    # Pages that say Latin-1 usually mean Windows-1252: its 0x80-0x9F bytes are the typographic
    # quotes and dashes, not control characters. latin-1 maps every byte, so this never raises.
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


_SNIFF_BYTES = 2048   # how far into the page a character set declaration is looked for
_TAG_NAME = re.compile(r"<([A-Za-z][^\s/>]*)")
_ATTRIBUTE = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""")


def _meta_attributes(head: str):
    """The attribute text of every `<meta>` tag in `head`, in order, read as a browser's first look at a page reads
    the tags: a comment is skipped whole (an unclosed one hides the rest), so it never joins the text around it into a
    tag; every other tag is read to its end, and a `>` or a `<meta` inside a quoted attribute value is part of that
    value. Text between the tags is passed over."""
    position = 0
    while True:
        start = head.find("<", position)
        if start < 0:
            return
        if head.startswith("<!--", start):
            end = head.find("-->", start + 4)
            if end < 0:
                return
            position = end + 3
            continue
        name = _TAG_NAME.match(head, start)
        if name is None:
            position = start + 1
            continue
        index, quote, after_equals = name.end(), None, False
        while index < len(head):
            char = head[index]
            if quote is not None:
                if char == quote:
                    quote = None
            elif char in "\"'" and after_equals:   # a quote opens a value only right after = (and spaces)
                quote = char
            elif char == ">":
                break
            if quote is None and not char.isspace():
                after_equals = char == "="
            index += 1
        else:
            return   # a tag that does not end within the bytes looked at
        if name.group(1).lower() == "meta":
            yield head[name.end():index]
        position = index + 1
_CHARSET_NAME = re.compile(r"[\w.:-]+")
_CHARSET_IN_CONTENT = re.compile(r"charset\s*=\s*[\"']?\s*([\w.:-]+)", re.IGNORECASE)


def _declared_charset(data: bytes) -> str | None:
    """The character set the page names in a `<meta>` tag within its first 2048 bytes, or None.

    Either `<meta charset=...>` or `<meta http-equiv="Content-Type" content="...charset=...">`, in any case and with
    double quotes, single quotes or none. The first tag that declares one wins, as in a browser.
    """
    head = data[:_SNIFF_BYTES].decode("latin-1")   # the tags are ASCII; every byte maps to a character
    for tag in _meta_attributes(head):              # a declaration inside a comment or a quoted value is none
        attributes: dict[str, str] = {}
        for name, double, single, bare in _ATTRIBUTE.findall(tag):
            attributes.setdefault(name.lower(), double or single or bare)
        if "charset" in attributes:
            found = _CHARSET_NAME.match(attributes["charset"].strip())
        elif attributes.get("http-equiv", "").strip().lower() == "content-type":
            found = _CHARSET_IN_CONTENT.search(attributes.get("content", ""))
            found = found and re.match(r"[\w.:-]+", found.group(1))
        else:
            continue
        if found:
            return found.group(0).lower()
    return None


def _decode_as(data: bytes, charset: str) -> str | None:
    """The text of `data` in the named character set, or None. None means: treat it as if nothing was declared.

    The one place the header and the page both go through. A name counts only when it, after Python's own
    normalisation of case, `-` and `_` and of aliases, is on the list `TEXT_ENCODINGS`.
    """
    try:
        name = codecs.lookup(charset).name
    except (LookupError, ValueError):   # a name Python does not know
        return None
    if name not in TEXT_ENCODINGS:
        return None
    if name in _AS_WINDOWS_1252:
        return _decode_cp1252(data)
    try:
        return data.decode(name)
    except (LookupError, ValueError):   # bytes that do not fit the set
        return None


def decode_bytes(data: bytes, content_type: str | None) -> str:
    """Text from downloaded bytes. The header's character set is believed first; when the header names none, the
    page's own `<meta>` declaration is used. Either counts only when it names one of `TEXT_ENCODINGS`; anything else
    is read as if nothing had been declared. Then UTF-8, then Windows-1252. Never raises."""
    match = re.search(r"charset\s*=\s*[\"']?([\w.:-]+)", content_type or "", re.IGNORECASE)
    if match:
        text = _decode_as(data, match.group(1).lower())
    else:
        charset = _declared_charset(data)
        text = _decode_as(data, charset) if charset else None
    if text is not None:
        return text
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return _decode_cp1252(data)
