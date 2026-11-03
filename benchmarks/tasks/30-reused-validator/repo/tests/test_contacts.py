from app.contacts import Contact


def test_both_phones_normalized():
    c = Contact(name="Ada", mobile="(555) 010-1234", office="555.010.9999")
    assert (c.mobile, c.office) == ("+5550101234", "+5550109999")
