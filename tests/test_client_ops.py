import json

from rational import js


def test_new_client_ops_serialize_target_first():
    assert js.show("#a").to_json() == ["show", "#a"]
    assert js.hide().to_json() == ["hide", None]
    assert js.set_text("x", "#a").to_json() == ["set_text", "#a", "x"]
    assert js.set_value("", "#f").to_json() == ["set_value", "#f", ""]
    assert js.copy("hello").to_json() == ["copy", None, "hello"]
    assert js.close_dialog().to_json() == ["close_dialog", "closest:dialog"]
    json.dumps(js.open_dialog("#d").to_json())
