#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
"""RAMSES RF - a RAMSES-II protocol decoder & analyser.

Test eavesdropping of a device class.
"""

import json
from pathlib import Path, PurePath

from ramses_rf import Gateway
from tests.helpers import TEST_DIR, assert_expected, shuffle_dict

WORK_DIR = f"{TEST_DIR}/eavesdrop_schema"


def id_fnc(param):
    return PurePath(param).name


def pytest_generate_tests(metafunc):
    folders = [f for f in Path(WORK_DIR).iterdir() if f.is_dir() and f.name[:1] != "_"]
    folders.sort()
    metafunc.parametrize("dir_name", folders, ids=id_fnc)


async def assert_schemas_equal(gwy: Gateway, expected_schema: dict):
    """Check the gwy schema, then shuffle and test again."""

    schema, packets = gwy._get_state(include_expired=True)
    assert_expected(schema, expected_schema)

    packets = shuffle_dict(packets)
    await gwy.set_state(packets, schema=schema)
    assert_expected(gwy.schema, expected_schema)


# duplicate in test_eavesdrop_dev_class
async def test_eavesdrop_off(dir_name):
    """Check discovery of schema and known_list *without* eavesdropping."""

    with open(f"{dir_name}/packet.log") as f:
        gwy = Gateway(None, input_file=f, config={"enable_eavesdrop": False})
        await gwy.start()

    with open(f"{dir_name}/schema_eavesdrop_off.json") as f:
        await assert_schemas_equal(gwy, json.load(f))

    try:
        with open(f"{dir_name}/known_list_eavesdrop_off.json") as f:
            assert_expected(gwy.known_list, json.load(f).get("known_list"))
    except FileNotFoundError:
        pass

    await gwy.stop()


# duplicate in test_eavesdrop_dev_class
async def test_eavesdrop_on_(dir_name):
    """Check discovery of schema and known_list *with* eavesdropping."""

    with open(f"{dir_name}/packet.log") as f:
        gwy = Gateway(None, input_file=f, config={"enable_eavesdrop": True})
        await gwy.start()

    with open(f"{dir_name}/schema_eavesdrop_on.json") as f:
        await assert_schemas_equal(gwy, json.load(f))

    try:
        with open(f"{dir_name}/known_list_eavesdrop_on.json") as f:
            assert_expected(gwy.known_list, json.load(f).get("known_list"))
    except FileNotFoundError:
        pass

    await gwy.stop()
