from radar.report.numbers import shown


def test_the_whole_number_part_gets_separators():
    assert shown("14900", ",") == "14,900"
    assert shown("1234567.5", ",") == "1,234,567.5"
    assert shown("-1234", ",") == "-1,234"
    assert shown("950", ",") == "950"
    assert shown("0.12345", ",") == "0.12345"


def test_anything_that_is_not_a_plain_number_is_left_alone():
    assert shown("about", ",") == "about"
    assert shown("12 ft²", ",") == "12 ft²"
    assert shown(None, ",") is None
    assert shown("160000", "") == "160000"
