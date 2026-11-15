import json
import sys
from io import BytesIO

import pytest
from pypdf import PdfWriter

from radar import cli
from radar.extract_text import html_to_text, pdf_to_text, sniff_kind, decode_bytes, NoTextLayer
from helpers import make_pdf

HTML = """<html><head><title>T</title><style>p{color:red}</style>
<script>var x = "secret";</script></head>
<body><h1>Press release</h1><p>The expansion adds two lines &amp; a warehouse.</p>
<p>Start is planned for 2028.</p><noscript>enable js</noscript></body></html>"""


def test_html_to_text_keeps_content_drops_code():
    text = html_to_text(HTML)
    assert "The expansion adds two lines & a warehouse." in text
    assert "secret" not in text and "color:red" not in text and "enable js" not in text
    assert text.index("Press release") < text.index("Start is planned")
    assert "warehouse.\n" in text  # block elements end with a line break


def test_html_to_text_tolerates_broken_markup():
    text = html_to_text("<div><p>Open paragraph<b>bold <i>never closed</div></span><<>& <p>Next")
    assert "Open paragraph" in text and "never closed" in text and "Next" in text
    assert html_to_text("") == ""
    assert "hidden" not in html_to_text("<script>hidden<p>still hidden</script><p>shown</p>")


def test_pdf_to_text_reads_text_layer():
    data = make_pdf(["The expansion adds two syringe lines.", "Operations begin in 2028."])
    text = pdf_to_text(data)
    assert "The expansion adds two syringe lines." in text and "Operations begin in 2028." in text


def test_pdf_without_text_layer_raises():
    writer = PdfWriter(); writer.add_blank_page(width=595, height=842)
    buf = BytesIO(); writer.write(buf)
    with pytest.raises(NoTextLayer):
        pdf_to_text(buf.getvalue())


def test_corrupt_pdf_raises_value_error():
    with pytest.raises(ValueError, match="not a readable PDF"):
        pdf_to_text(b"%PDF-1.7 this is not a real pdf at all")
    with pytest.raises(ValueError, match="not a readable PDF"):
        pdf_to_text(b"")


def test_sniff_kind():
    assert sniff_kind(b"%PDF-1.7 ...", "application/octet-stream") == "pdf"
    assert sniff_kind(b"  <!DOCTYPE html><html>", None) == "html"
    assert sniff_kind(b"plain words", "text/plain; charset=utf-8") == "text"
    assert sniff_kind(b"\x00\x01\x02", "application/zip") == "unknown"
    assert sniff_kind(b"<p>fragment</p>", "text/html; charset=utf-8") == "html"
    assert sniff_kind(b"<p>fragment</p>", "application/xhtml+xml") == "html"


def test_decode_bytes_uses_declared_charset_then_utf8():
    assert decode_bytes("Abfüllung".encode("latin-1"), "text/html; charset=ISO-8859-1") == "Abfüllung"
    assert decode_bytes("Abfüllung".encode("utf-8"), None) == "Abfüllung"
    assert decode_bytes("Abfüllung".encode("latin-1"), None) == "Abfüllung"  # not UTF-8: falls back to Latin-1
    assert decode_bytes("Abfüllung".encode("utf-8"), "text/html; charset=no-such-charset") == "Abfüllung"


def test_doctor_ok(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RADAR_HOME", str(tmp_path / "home"))
    assert cli.main(["doctor"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["python_ok"] is True and out["pypdf_ok"] is True and out["hint"] is None
    assert out["python"].count(".") == 2 and out["pypdf"]


def test_doctor_reports_missing_pypdf(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RADAR_HOME", str(tmp_path / "home"))
    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert cli.main(["doctor"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["pypdf"] is None and out["pypdf_ok"] is False
    assert out["hint"] == "Run: radar setup"


WIN1252_BYTES = b"\x84Abf\xfcllung\x93 \x96"
WIN1252_TEXT = chr(0x201E) + "Abfüllung" + chr(0x201C) + " " + chr(0x2013)


def test_decode_bytes_reads_latin1_declaration_as_windows_1252():
    for declared in ("ISO-8859-1", "iso-8859-1", "latin-1", "Latin1", "LATIN-1"):
        assert decode_bytes(WIN1252_BYTES, f"text/html; charset={declared}") == WIN1252_TEXT


def test_decode_bytes_without_charset_falls_back_to_windows_1252():
    assert decode_bytes(WIN1252_BYTES, None) == WIN1252_TEXT


def test_decode_bytes_never_raises_on_unmapped_cp1252_bytes():
    # 0x81 has no cp1252 mapping: that decode falls back to latin-1
    assert decode_bytes(b"a\x81b", None) == "a\x81b"
    assert decode_bytes(b"a\x81b", "text/plain; charset=latin-1") == "a\x81b"


def test_html_to_text_separates_elements_outside_the_old_block_list():
    text = html_to_text("<dt>Term</dt><dd>Definition</dd><header>Head</header><main>Body</main>")
    assert text.split() == ["Term", "Definition", "Head", "Body"]
    assert "TermDefinition" not in text and "HeadBody" not in text
    assert text.splitlines() == ["Term", "Definition", "Head", "Body"]


def test_html_to_text_does_not_split_inline_elements():
    assert "Abfüllung" in html_to_text("<p>Abf<b>üll</b>ung</p>")
    assert "fill-finish" in html_to_text("<p>fill<span>-</span>finish</p>")
    assert "a b c" in html_to_text("<p>a <em>b</em> <a href='x'>c</a></p>")


def test_html_to_text_treats_custom_elements_as_blocks():
    assert html_to_text("<my-card>One</my-card><my-card>Two</my-card>").splitlines() == ["One", "Two"]


# --- Task 9: the page names its own character set -------------------------------------------------------------

def _page(meta: str, body: str, charset: str, padding: int = 0) -> bytes:
    """A page whose head holds `meta` (after `padding` bytes of comment), written in `charset`."""
    filler = "<!--" + "x" * padding + "-->" if padding else ""
    return f"<html><head>{filler}{meta}<title>T</title></head><body>{body}</body></html>".encode(charset)


def test_the_page_names_its_own_character_set():
    data = '<html><head><meta charset="iso-8859-1"></head><body>Größe „A“</body></html>'.encode("cp1252")
    assert "Größe „A“" in decode_bytes(data, "text/html")


POLISH = "Nowa fabryka w " + chr(0x141) + chr(0xF3) + "dzi " + chr(0x15B) + "rodek"   # invented place and sentence
JAPANESE = "新工場の建設は二千二十八年に始まる"                                         # invented sentence


def test_a_page_in_another_character_set_is_read_as_the_page_says():
    # Under UTF-8 these bytes are invalid and the Windows-1252 fallback reads them as other letters.
    polish = _page('<meta charset="iso-8859-2">', POLISH, "iso-8859-2")
    assert POLISH.encode("iso-8859-2").decode("cp1252", errors="replace") != POLISH
    assert POLISH in decode_bytes(polish, "text/html")
    japanese = _page('<meta charset="shift_jis">', JAPANESE, "shift_jis")
    assert JAPANESE in decode_bytes(japanese, None)


@pytest.mark.parametrize("meta", [
    '<meta charset="ISO-8859-2">', "<META CHARSET='iso-8859-2'>", "<meta charset=iso-8859-2>",
    '<meta   charset = "iso-8859-2" />', '<Meta Charset="Iso-8859-2">',
    '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-2">',
    "<META HTTP-EQUIV='content-type' CONTENT='text/html;charset=ISO-8859-2'>",
    "<meta http-equiv=Content-Type content=text/html;charset=iso-8859-2>",
    '<meta content="text/html; charset=iso-8859-2" http-equiv="Content-Type">',
])
def test_the_declaration_is_found_in_any_case_and_with_any_quotes(meta):
    assert POLISH in decode_bytes(_page(meta, POLISH, "iso-8859-2"), "text/html")


def test_a_meta_that_is_not_a_character_set_declaration_is_ignored():
    for meta in ('<meta name="description" content="a page; charset=iso-8859-2">',
                 '<meta http-equiv="refresh" content="5; charset=iso-8859-2">'):
        data = _page(meta, POLISH, "iso-8859-2")
        assert decode_bytes(data, "text/html") == data.decode("cp1252")   # the fallback, as before


def test_the_header_wins_over_the_page():
    # the header says UTF-8, the page says otherwise: the header is believed
    data = _page('<meta charset="iso-8859-2">', "Größe „A“", "utf-8")
    assert "Größe „A“" in decode_bytes(data, "text/html; charset=utf-8")
    polish = _page('<meta charset="utf-8">', POLISH, "iso-8859-2")
    assert POLISH in decode_bytes(polish, "text/html; charset=iso-8859-2")


def test_an_http_equiv_meta_is_read_too():
    meta = '<meta http-equiv="Content-Type" content="text/html; charset=windows-1250">'
    text = "Zakład w " + chr(0x141) + chr(0xF3) + "dzi"
    assert text in decode_bytes(_page(meta, text, "cp1250"), "text/html")


def test_a_declaration_after_the_first_2048_bytes_is_ignored():
    meta = '<meta charset="iso-8859-2">'
    inside = _page(meta, POLISH, "iso-8859-2", padding=1900)
    assert inside.index(b"<meta") < 2048 and inside.index(b"<meta") + len(meta) <= 2048
    assert POLISH in decode_bytes(inside, None)
    outside = _page(meta, POLISH, "iso-8859-2", padding=2100)
    assert outside.index(b"<meta") > 2048
    assert decode_bytes(outside, None) == outside.decode("cp1252")        # the fallback, as before
    far_down = ("<html><head></head><body>" + "x" * 3000 + meta + POLISH + "</body></html>").encode("iso-8859-2")
    assert decode_bytes(far_down, None) == far_down.decode("cp1252")
    cut = ("<html><head>" + "x" * 2030 + meta + "</head>" + POLISH).encode("iso-8859-2")   # starts before, ends after
    assert decode_bytes(cut, None) == cut.decode("cp1252")


def test_a_character_set_python_does_not_know_falls_back_and_never_raises():
    page = _page('<meta charset="x-no-such-charset">', "Größe „A“", "utf-8")
    assert "Größe „A“" in decode_bytes(page, "text/html")
    old = _page('<meta charset="x-no-such-charset">', "Größe „A“", "cp1252")
    assert "Größe „A“" in decode_bytes(old, None)
    for declared in ("", "utf-", "rot13", "hex", "idna", "utf-16", "utf-7;x", "a" * 500):
        data = _page(f'<meta charset="{declared}">', "Größe", "cp1252")
        assert "Größe" in decode_bytes(data, None), declared


def test_a_page_that_names_utf8_but_is_not_falls_back():
    data = _page('<meta charset="utf-8">', "Größe „A“", "cp1252")
    assert "Größe „A“" in decode_bytes(data, "text/html")


def test_a_page_that_names_latin1_is_read_as_windows_1252_and_a_utf8_page_is_read_as_utf8():
    for declared in ("iso-8859-1", "latin1", "ISO-8859-1"):
        data = _page(f'<meta charset="{declared}">', "Größe „A“", "cp1252")
        assert "Größe „A“" in decode_bytes(data, None)
    utf8 = _page('<meta charset="utf-8">', "Größe „A“", "utf-8")
    assert "Größe „A“" in decode_bytes(utf8, None)


# --- Task 9, fix round 1: a declared character set is honoured only when it is a plain text encoding -----------------

def _fallback(data: bytes) -> str:
    """What the engine reads when nothing usable is declared: UTF-8, else Windows-1252."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252")


HOSTILE_BODY = "+AEE-bc +ACI-quoted+ACI- and \\u0041bc and Hallo"   # means other text under utf-7 and unicode_escape


def test_a_page_that_declares_utf7_is_not_read_as_utf7():
    data = f'<html><head><meta charset="utf-7"></head><body>{HOSTILE_BODY}</body></html>'.encode("ascii")
    text = decode_bytes(data, None)
    assert "+AEE-bc" in text and "Abc " not in text and text == data.decode("ascii")


def test_a_header_that_names_utf7_is_not_believed():
    data = HOSTILE_BODY.encode("ascii")
    text = decode_bytes(data, "text/html; charset=utf-7")
    assert "+AEE-bc" in text and "Abc " not in text and text == HOSTILE_BODY


@pytest.mark.parametrize("name", ["utf-7", "unicode_escape", "raw_unicode_escape", "cp037", "cp500", "utf-32",
                                  "utf-32le", "utf-32be", "utf-16", "utf-16le", "utf-16be", "rot13", "base64", "idna",
                                  "punycode", "hex", "zip", "bz2", "uu", "quopri", "mbcs", "palmos", "hz",
                                  "iso2022_jp", "x-no-such-charset"])
def test_a_set_that_is_no_browser_text_encoding_ends_in_the_fallback_through_the_page_and_the_header(name):
    for body in (HOSTILE_BODY, "Größe „A“"):
        for data, header in ((f'<html><head><meta charset="{name}"></head><body>{body}</body></html>'.encode("cp1252"),
                              None),
                             (body.encode("cp1252"), f"text/html; charset={name}"),
                             (f'<meta http-equiv="Content-Type" content="text/html; charset={name}">{body}'
                              .encode("cp1252"), None)):
            assert decode_bytes(data, header) == _fallback(data), (name, header)


@pytest.mark.parametrize("name", ["ISO-8859-2", "iso_8859-2", "latin2", "iso8859-2", "ISO_8859_2", "l2"])
def test_alias_spellings_of_an_allowed_set_still_work(name):
    assert POLISH in decode_bytes(_page(f'<meta charset="{name}">', POLISH, "iso-8859-2"), None)
    assert POLISH in decode_bytes(POLISH.encode("iso-8859-2"), f"text/html; charset={name}")


CYRILLIC = "Новый завод в Казани"          # invented sentence
CHINESE = "新工厂的建设于二零二八年开始"        # invented sentence, simplified
CHINESE_TRADITIONAL = "新工廠的建設於二零二八年開始"
KOREAN = "새 공장 건설은 이천이십팔 년에 시작된다"   # invented sentence


@pytest.mark.parametrize("name,encoding,text", [
    ("Shift-JIS", "shift_jis", JAPANESE), ("sjis", "shift_jis", JAPANESE), ("ms932", "cp932", JAPANESE),
    ("CP932", "cp932", JAPANESE), ("EUC-JP", "euc_jp", JAPANESE), ("euc-kr", "euc_kr", KOREAN),
    ("cp949", "cp949", KOREAN), ("GBK", "gbk", CHINESE), ("gb2312", "gb2312", CHINESE),
    ("GB18030", "gb18030", CHINESE), ("big5", "big5", CHINESE_TRADITIONAL), ("koi8-r", "koi8_r", CYRILLIC),
    ("koi8-u", "koi8_u", CYRILLIC), ("windows-1251", "cp1251", CYRILLIC), ("windows-1250", "cp1250", POLISH),
    ("CP1250", "cp1250", POLISH), ("UTF8", "utf-8", "Größe „A“"), ("UTF-8", "utf-8", "Größe „A“"),
    ("utf_8", "utf-8", "Größe „A“"), ("utf-8-sig", "utf-8", "Größe „A“")])
def test_other_allowed_sets_are_honoured(name, encoding, text):
    assert text in decode_bytes(_page(f'<meta charset="{name}">', text, encoding), None)
    assert text in decode_bytes(text.encode(encoding), f"text/html; charset={name}")


def test_ascii_and_latin1_are_read_as_windows_1252():
    for name in ("ascii", "us-ascii", "iso-8859-1", "latin1", "l1"):
        data = _page(f'<meta charset="{name}">', "Größe „A“", "cp1252")
        assert "Größe „A“" in decode_bytes(data, None), name
        assert decode_bytes("Größe „A“".encode("cp1252"), f"text/html; charset={name}") == "Größe „A“", name


def test_every_allowed_set_leaves_plain_ascii_bytes_as_they_are():
    import codecs
    from radar.extract_text import TEXT_ENCODINGS
    markup = "<meta charset=x> <p>Plant North, 2028: \"quoted\" + 1 \\ ~</p>"
    for name in sorted(TEXT_ENCODINGS):
        assert codecs.lookup(name).name == name, name                  # the list holds canonical names only
        encoded = markup.encode(name)
        if name == "utf-8-sig":
            encoded = encoded.removeprefix(codecs.BOM_UTF8)            # the one that writes a byte-order mark
        assert encoded == markup.encode("ascii"), name
        assert markup.encode("ascii").decode(name) == markup, name


def test_the_allowed_sets_are_the_ruled_list():
    from radar.extract_text import TEXT_ENCODINGS
    expected = {"utf-8", "utf-8-sig", "ascii", "iso8859-1", "koi8-r", "koi8-u", "shift_jis", "cp932", "euc_jp",
                "euc_kr", "cp949", "gbk", "gb2312", "gb18030", "big5"}
    expected |= {f"cp{number}" for number in range(1250, 1259)}
    expected |= {f"iso8859-{number}" for number in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16)}
    assert TEXT_ENCODINGS == expected


def test_a_real_utf16_file_without_a_declaration_is_read_as_before():
    data = "<p>Plant North</p>".encode("utf-16")                        # with a byte-order mark; no declaration
    assert decode_bytes(data, None) == data.decode("cp1252")


def test_a_declaration_inside_a_comment_is_ignored_and_one_after_a_closed_comment_is_found():
    commented = "<html><head><!-- <meta charset=\"iso-8859-2\"> --><title>T</title></head><body>" + POLISH
    data = (commented + "</body></html>").encode("iso-8859-2")
    assert decode_bytes(data, None) == data.decode("cp1252")
    unclosed = ("<html><head><!-- <meta charset=iso-8859-2> <title>T</title></head><body>" + POLISH).encode("iso-8859-2")
    assert decode_bytes(unclosed, None) == unclosed.decode("cp1252")
    after = ("<html><head><!-- a note --><meta charset=\"iso-8859-2\"><!-- another --><title>T</title></head><body>"
             + POLISH + "</body></html>").encode("iso-8859-2")
    assert POLISH in decode_bytes(after, None)
    both = ("<!-- <meta charset=utf-8> --><meta charset=iso-8859-2>" + POLISH).encode("iso-8859-2")
    assert POLISH in decode_bytes(both, None)


# --- Part A fix A2, item 7 (ruling HG9): text a page hides from its readers stays out of the saved copy's text ----

def words(html):
    return html_to_text(html).split()


@pytest.mark.parametrize("opening", [
    '<p hidden>', '<p hidden="">', '<p HIDDEN="hidden">', '<p hidden="until-found">',
    '<p style="display:none">', '<p style="DISPLAY : None">', '<p style="color: red;display:none;">',
    '<p style="display: none !important">', '<p style="visibility:hidden">', '<p style=" Visibility :  HIDDEN ; ">',
    '<p style="display:/* a note */none">',
])
def test_each_plain_way_of_hiding_an_element_keeps_its_text_out(opening):
    text = html_to_text(f"<p>Before it.</p>{opening}Secret words here.</p><p>After it.</p>")
    assert "Secret" not in text
    assert text.splitlines() == ["Before it.", "After it."]


@pytest.mark.parametrize("opening", ['<p aria-hidden="false">', '<p style="display:block">',
                                     '<p style="visibility:visible">', '<p style="display:inline-none">',
                                     '<p data-hidden="true">', '<p class="hidden">', '<p title="hidden">',
                                     # fix wave A22: a browser shows such text to a sighted reader, so it stays
                                     '<p aria-hidden="true">', '<p aria-hidden=" TRUE ">', '<p aria-hidden>'])
def test_markup_that_does_not_hide_keeps_its_text(opening):
    assert words(f"<p>Before it.</p>{opening}Shown words here.</p>") == ["Before", "it.", "Shown", "words", "here."]


def test_the_content_of_a_template_stays_out():
    text = html_to_text("<p>Before it.</p><template><p>Secret words here.</p></template><p>After it.</p>")
    assert text.splitlines() == ["Before it.", "After it."]


def test_everything_inside_a_hidden_element_stays_hidden_until_it_closes():
    page = ("<div hidden><p>one <span>two</span></p><div>three <b>four</b></div>"
            "<section aria-hidden='false'>five</section><ul><li>six</li></ul></div><p>seven</p>")
    assert words(page) == ["seven"]
    assert words("<div hidden><div>one</div>two<div>three</div></div>four") == ["four"]
    assert words("<span style='display:none'>one <span>two</span> three</span> four") == ["four"]


def test_a_visible_element_after_a_hidden_one_is_kept_whole():
    page = ("<article><p>First paragraph.</p><aside hidden>Decoration.</aside>"
            "<p>Second paragraph, <em>with</em> a link.</p></article>")
    assert html_to_text(page).splitlines() == ["First paragraph.", "Second paragraph, with a link."]


@pytest.mark.parametrize("void", ["<br hidden>", "<img hidden src='x.png' alt='a picture'>", "<hr hidden>",
                                  "<input hidden value='x'>", "<br hidden/>", "<img style='display:none'>",
                                  "<wbr aria-hidden='true'>"])
def test_a_hidden_element_that_holds_nothing_does_not_hide_what_follows(void):
    assert words(f"<p>Before {void} after it.</p><p>Next paragraph.</p>") == [
        "Before", "after", "it.", "Next", "paragraph."]


def test_a_hidden_element_written_as_self_closing_still_opens_as_a_browser_reads_it():
    assert words("<div><span hidden/>secret</span>shown</div>") == ["shown"]
    assert words("<p>shown</p><div hidden/>secret") == ["shown"]


# A2 fix round 1, IMPORTANT 3 (ruling HG15): the copy's text follows what a browser without scripts shows. An element
# whose end tag may be left out ends where the HTML standard ends it; any other unclosed hidden element hides to the end
# of its parent, or to the end of the page when that cannot be found either.

def test_an_optional_end_tag_left_out_ends_the_hidden_element_where_a_browser_ends_it():
    assert words("<p hidden>Notice<p>Real text") == ["Real", "text"]
    assert words("<ul><li hidden>x<li>Home</ul><article>Story text</article>") == ["Home", "Story", "text"]
    assert words("<table><tr><td hidden>x<td>Shown</table>") == ["Shown"]
    assert words("<table><tr><th hidden>x<th>Shown</tr><tr hidden><td>row<tr><td>Next row</table>") == [
        "Shown", "Next", "row"]
    assert words("<dl><dt hidden>term<dd>Meaning<dt>Other</dl>") == ["Meaning", "Other"]
    assert words("<dl><dd hidden>meaning<dt>Term</dl>") == ["Term"]
    assert words("<select><option hidden>x<option>Choice<optgroup label=g><option>Last</select>") == [
        "Choice", "Last"]


@pytest.mark.parametrize("closer", ["<div>", "<ul><li>", "<h2>", "<p>", "<section>", "<blockquote>", "<hr>",
                                    "<pre>", "<dl><dd>", "<form>", "<figure>"])
def test_a_hidden_p_ends_where_a_block_element_starts(closer):
    assert words(f"<div><p hidden>secret{closer}Shown text</div>") == ["Shown", "text"]


def test_a_hidden_p_ends_at_a_table_in_a_standards_mode_page_but_not_in_a_quirks_mode_page():
    # A browser closes an open p at <table> only when the page is not in quirks mode; a page without <!DOCTYPE html>
    # is in quirks mode, where the table stays inside the p, so the table's text stays hidden too.
    assert words("<!DOCTYPE html><p hidden>secret<table><tr><td>Shown</table>") == ["Shown"]
    assert words("<p hidden>secret<table><tr><td>inside</table></p><p>Shown</p>") == ["Shown"]


def test_a_hidden_p_also_ends_at_its_parents_end_and_at_its_own_end_tag():
    assert words("<div><p hidden>secret</div>Shown") == ["Shown"]
    assert words("<p hidden>secret</p>Shown") == ["Shown"]
    assert words("<p hidden>secret<span>still secret</span><b>and this</b>") == []


def test_a_hidden_li_in_a_nested_list_hides_the_inner_list_and_the_next_outer_item_shows():
    page = "<ul><li hidden>outer<ul><li>inner one<li>inner two</ul>more<li>Next item</ul><p>After</p>"
    assert words(page) == ["Next", "item", "After"]


def test_an_unclosed_hidden_element_of_another_kind_hides_to_the_end_of_its_parent():
    assert words("<section><div hidden>secret<p>more</section><p>Shown</p>") == ["Shown"]
    assert words("<div><span hidden>secret</div><p>Shown</p>") == ["Shown"]
    assert words("<article><aside hidden>secret<p>more<p>and more</article>After the article") == [
        "After", "the", "article"]


def test_an_unclosed_hidden_element_whose_parent_never_ends_hides_the_rest_of_the_page():
    assert words("<p>shown</p><div hidden>secret<p>more</p><p>and more") == ["shown"]


def test_a_hidden_block_closes_everything_left_open_inside_it_at_its_own_end_tag():
    assert words("<ul hidden><li>one<li>two</ul><p>shown</p>") == ["shown"]
    assert words("<div hidden><p>one<p>two<span>three</div>shown") == ["shown"]
    assert words("<table><tr><td hidden>one<span>two</td><td>shown</td></tr></table>") == ["shown"]


def test_an_end_tag_a_browser_ignores_does_not_end_a_hidden_element():
    # a span's end tag does not close it while a block element is open inside it, as in a browser
    assert words("<span hidden>a<div>b</span>c</div>d</span><p>shown</p>") == ["shown"]
    # an end tag inside text a browser reads as plain text is no end tag
    assert words("<div hidden><textarea></div></textarea>secret</div><p>shown</p>") == ["shown"]
    assert words("<div hidden><xmp></div></xmp>secret</div><p>shown</p>") == ["shown"]
    # inside a table cell, the end tag of a hidden element outside the table does not reach it
    assert words("<div hidden><table><tr><td></div>secret</td></tr></table></div><p>shown</p>") == ["shown"]


def test_a_table_part_outside_a_table_is_ignored_as_a_browser_ignores_it():
    assert words("<td hidden>x<td>Shown") == ["x", "Shown"]


def test_a_hidden_formatting_element_closed_from_outside_stays_hidden_until_its_own_end_tag():
    # a browser opens such an element again further on, so whatever follows is hidden until its end tag
    assert words("<p>shown</p><b hidden>secret<p>inside</b>left out</p><p>left out</p>") == ["shown"]
    assert words("<p>shown</p><div hidden><i hidden>secret</div><p>left out</p></i><p>Back</p>") == [
        "shown", "Back"]
    assert words("<p>shown</p><b hidden>secret <i>x</i></b><p>shown again</p>") == ["shown", "shown", "again"]


@pytest.mark.parametrize("page", ["<p>Before.</p><iframe>Fallback words.</iframe><p>After.</p>",
                                  "<p>Before.</p><noembed>Fallback words.</noembed><p>After.</p>",
                                  "<p>Before.</p><noframes>Fallback <p>words.</p></noframes><p>After.</p>",
                                  "<p>Before.</p><dialog>Fallback <p>words.</p></dialog><p>After.</p>"])
def test_text_inside_an_iframe_noembed_noframes_or_a_closed_dialog_stays_out(page):
    assert html_to_text(page).splitlines() == ["Before.", "After."]


def test_an_open_dialog_is_shown_and_an_iframe_with_markup_inside_does_not_swallow_the_page():
    assert words("<dialog open>Shown words</dialog>") == ["Shown", "words"]
    assert words("<iframe><script>x</iframe><p>After</p>") == ["After"]


def test_a_hidden_body_or_html_hides_the_whole_page():
    assert html_to_text("<p>early text</p><body hidden><p>late text</p>") == ""
    assert html_to_text("<html style='display:none'><body><p>text</p></body></html>") == ""
    assert html_to_text("<body style='visibility:hidden'><p>" + "text " * 100 + "</p></body>") == ""


def test_a_page_without_hidden_markup_reads_as_before():
    page = ("<html><head><title>T</title></head><body><div><p>One<br>two</p><ul><li>three<li>four</ul>"
            "<table><tr><td>five<td>six</table><p>seven <b>eight</p>nine</div></body></html>")
    assert html_to_text(page).splitlines() == ["T", "One", "two", "three", "four", "five", "six", "seven eight",
                                               "nine"]


def test_a_quote_that_exists_only_inside_a_hidden_element_is_not_found_by_check_quotes(tmp_path, capsys):
    from radar import fetch, store
    from helpers import add_fact, make_run
    run = make_run(tmp_path / "runs")
    page = tmp_path / "release.html"
    page.write_text("<html><body><p>Competitor A will add one filling line at Plant North in 2027.</p>"
                    "<div style='display: none'><p>Competitor A will add five filling lines at Plant North in "
                    "2027.</p></div><p>" + "The rest of this invented page is plain filler. " * 5 + "</p></body></html>",
                    encoding="utf-8")
    fetch.add_copy(run, page, "https://www.site-a.example/news",
                   {"publisher": "Competitor A", "title": "Lines", "date": "2026-05-14", "type": "company_release",
                    "speaker": "the company", "interest": "wants to look strong", "language": "en"}, data_class="public")
    add_fact(run, source_id="S1", quote="Competitor A will add five filling lines at Plant North in 2027.")
    add_fact(run, source_id="S1", quote="Competitor A will add one filling line at Plant North in 2027.")
    assert cli.main(["check-quotes", "--run", str(run)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["failed"] == ["F1"]
    assert (out["facts"]["F1"]["quote"]["passed"], out["facts"]["F1"]["quote"]["reason"]) == (False, "not_found")
    assert out["facts"]["F2"]["quote"]["passed"] is True
    assert "five" not in (run / "copies" / "S1.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("body", ["<body style='visibility:hidden'><p>{}</p></body>", "<p hidden>{}</p>",
                                  "<div style='display:none'>{}</div><p>Short.</p>"])
def test_add_copy_refuses_a_page_that_shows_too_little_text_and_saves_nothing(tmp_path, capsys, body):
    from radar import store
    from helpers import make_run
    run = make_run(tmp_path / "runs")
    page = tmp_path / "page.html"
    page.write_text(body.format("Competitor A will add one filling line at Plant North in 2027. " * 10),
                    encoding="utf-8")
    meta = ["--publisher", "Competitor A", "--title", "Lines", "--date", "2026-05-14", "--type", "company_release",
            "--speaker", "the company", "--interest", "wants to look strong", "--language", "en"]
    assert cli.main(["add-copy", "--data-class", "public", "--run", str(run), "--file", str(page), "--url", "https://www.site-a.example/x",
                     *meta]) == 2
    out = json.loads(capsys.readouterr().out)
    assert list(out) == ["error"] and "too_little_text" in out["error"]
    assert store.read_sources(run) == {} and sorted(p.name for p in (run / "copies").iterdir()) == [".gitignore"]
    assert sorted(p.name for p in (run / "sources").iterdir()) == []
    assert store.load_run(run)["sources_created"] == 0


def test_add_copy_still_saves_a_page_that_shows_enough_text(tmp_path):
    from radar import fetch, store
    from helpers import make_run
    run = make_run(tmp_path / "runs")
    page = tmp_path / "page.html"
    page.write_text("<p hidden>Notice<p>" + "Competitor A will add one filling line at Plant North. " * 6,
                    encoding="utf-8")
    record = fetch.add_copy(run, page, "https://www.site-a.example/x",
                            {"publisher": "Competitor A", "title": "Lines", "date": "2026-05-14",
                             "type": "company_release", "speaker": "the company", "interest": "wants to look strong",
                             "language": "en"}, data_class="public")
    assert record["access"] == "ok" and "Notice" not in (run / record["copy_file"]).read_text(encoding="utf-8")
    assert list(store.read_sources(run)) == ["S1"]


# --- A2 fix round 2, point 2: the time to read a page does not grow with how deep its elements are nested ---------

def _words(count: int) -> list[str]:
    return [f"word{number}" for number in range(count)]


def _nested_divs(count: int) -> str:
    return "".join(f"<div>{word}" for word in _words(count)) + "<div hidden>concealed</div><div>after"


def _unclosed_div_p_pairs(count: int) -> str:
    return "".join(f"<div><p>{word}" for word in _words(count)) + "<p hidden>concealed<div>after"


def _nested_lists(count: int) -> str:
    return "".join(f"<ul><li>{word}" for word in _words(count)) + "<li hidden>concealed</li><li>after"


DEEP_PAGES = [(_nested_divs, 50_000), (_unclosed_div_p_pairs, 50_000), (_nested_lists, 30_000)]


def _one_word_a_line(count: int) -> str:
    """What each deep page reads as: every word on a line of its own, the hidden one left out."""
    return "\n".join([*_words(count), "after"]) + "\n"


@pytest.mark.parametrize("page, count", DEEP_PAGES, ids=["nested divs", "unclosed div and p pairs", "nested lists"])
def test_a_deeply_nested_page_is_read_in_under_two_seconds_with_the_same_text(page, count):
    import time
    assert html_to_text(page(300)) == _one_word_a_line(300)   # the same property at a depth that was always quick
    started = time.perf_counter()
    text = html_to_text(page(count))
    seconds = time.perf_counter() - started
    assert text == _one_word_a_line(count)
    assert seconds < 2, f"{seconds:.1f} seconds"


def test_an_open_element_that_is_out_of_reach_does_not_slow_the_reading_either():
    """A <p> that stays open below an <object> is looked for at every <div> and never closed by one."""
    import time
    page = lambda count: "<p>first<object>" + "".join(f"<div>{word}" for word in _words(count))   # noqa: E731
    expected = lambda count: "\n".join(["first", *_words(count)]) + "\n"                          # noqa: E731
    assert html_to_text(page(300)) == expected(300)
    started = time.perf_counter()
    text = html_to_text(page(50_000))
    seconds = time.perf_counter() - started
    assert text == expected(50_000)
    assert seconds < 2, f"{seconds:.1f} seconds"


# --- fix wave A22: aria-hidden is no way of hiding text: a browser shows it to a sighted reader ----------------------

def test_a_quote_inside_an_aria_hidden_element_is_found_as_a_reader_sees_it(tmp_path):
    from radar import fetch, store, verify
    from helpers import add_fact, make_run
    run = make_run(tmp_path / "runs")
    page = tmp_path / "page.html"
    page.write_text("<html><body><p>" + "The company reported its results for the year. " * 5 + "</p>"
                    "<div aria-hidden='true'><p>Competitor A will add one filling line at Plant North in 2027.</p>"
                    "</div></body></html>", encoding="utf-8")
    fetch.add_copy(run, page, "https://www.site-a.example/news", {
        "publisher": "Competitor A", "title": "Lines", "date": "2026-05-14", "type": "company_release",
        "speaker": "the company", "interest": "wants to look strong", "language": "en"}, data_class="public")
    add_fact(run, source_id="S1", quote="Competitor A will add one filling line at Plant North in 2027.")
    assert verify.check_quotes(run)["F1"]["quote"]["passed"] is True
    assert "Plant North" in (run / store.read_sources(run)["S1"]["copy_file"]).read_text(encoding="utf-8")


# --- fix wave A23.13: a comment never joins two halves into a declaration, and a <meta> inside a quoted value is text --

from radar.extract_text import _declared_charset   # noqa: E402


@pytest.mark.parametrize("head", [
    "<me<!-- -->ta charset=iso-8859-2>",                                    # a comment between the halves
    "<me<!---->ta charset=iso-8859-2>",
    "<p title='<meta charset=iso-8859-2>'>A title.</p>",                    # inside a quoted attribute value
    '<p title="<meta charset=iso-8859-2>">A title.</p>',
    "<p data-x = '<meta charset=iso-8859-2>' class=y>A title.</p>",
    "<p title=<meta charset=iso-8859-2>A title.</p>",                       # an unquoted value: still inside <p>
])
def test_no_declaration_is_read_where_a_browser_reads_none(head):
    data = ("<html><head>" + head + "</head><body>" + POLISH + "</body></html>").encode("iso-8859-2")
    assert _declared_charset(data) is None
    assert decode_bytes(data, None) == data.decode("cp1252")


@pytest.mark.parametrize("head", [
    "<p title='a > b'>x</p><meta charset=iso-8859-2>",                     # a > inside a quoted value ends nothing
    "<!-- one --> <!-- two --><meta charset=\"iso-8859-2\">",
    "<p title=\"it's\">x</p><META CHARSET='iso-8859-2'>",
    "<meta http-equiv=\"Content-Type\" content=\"text/html; charset=iso-8859-2\">",
])
def test_a_declaration_after_such_markup_is_still_found(head):
    data = ("<html><head>" + head + "</head><body>" + POLISH + "</body></html>").encode("iso-8859-2")
    assert _declared_charset(data) == "iso-8859-2"
    assert POLISH in decode_bytes(data, None)
