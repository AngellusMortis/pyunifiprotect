from pyunifiprotect.utils import dict_diff


def test_dict_diff_equal():
    assert dict_diff({}, {}) == {}

    obj = {"a": 1, "b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}
    assert dict_diff(obj, obj) == {}

    obj = {"a": 1, "b": {"b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}}
    assert dict_diff(obj, obj) == {}

    obj = {"a": 1, "b": {"b": 2, "c": {"c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}}}
    assert dict_diff(obj, obj) == {}


def test_dict_diff_new_keys():
    obj = {"a": 1, "b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}
    assert dict_diff({}, obj) == obj
    assert dict_diff({"a": 1, "b": {}}, {"a": 1, "b": obj}) == {"b": obj}

    obj = {"a": 1, "b": {"b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}}
    assert dict_diff({}, obj) == obj
    assert dict_diff({"a": 1, "b": {}}, {"a": 1, "b": obj}) == {"b": obj}

    obj = {"a": 1, "b": {"b": 2, "c": {"c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}}}
    assert dict_diff({}, obj) == obj
    assert dict_diff({"a": 1, "b": {}}, {"a": 1, "b": obj}) == {"b": obj}


def test_dict_diff_new_changed():
    assert (
        dict_diff(
            {"a": 1, "b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]},
            {"a": 3, "b": 2, "c": "test", "d": "test", "e": "test6", "f": [1], "g": [1, 2, 3]},
        )
        == {"a": 3, "c": "test", "d": "test", "e": "test6", "f": [1]}
    )

    assert (
        dict_diff(
            {"a": 1, "b": {"b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}},
            {"a": 3, "b": {"b": 2, "c": "test", "d": "test", "e": "test6", "f": [1], "g": [1, 2, 3]}},
        )
        == {"a": 3, "b": {"c": "test", "d": "test", "e": "test6", "f": [1]}}
    )

    assert (
        dict_diff(
            {"a": 1, "b": {"b": 2, "c": {"c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}}},
            {"a": 3, "b": {"b": 2, "c": {"c": "test", "d": "test", "e": "test6", "f": [1], "g": [1, 2, 3]}}},
        )
        == {"a": 3, "b": {"c": {"c": "test", "d": "test", "e": "test6", "f": [1]}}}
    )
