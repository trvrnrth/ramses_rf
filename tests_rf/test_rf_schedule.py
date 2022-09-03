#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
"""RAMSES RF - a RAMSES-II protocol decoder & analyser.

Test CH/DHW schedules with a mocked controller.
"""

from copy import deepcopy

from ramses_rf.const import SZ_SCHEDULE, SZ_TOTAL_FRAGS, SZ_ZONE_IDX, Code
from ramses_rf.protocol import Message
from ramses_rf.system.schedule import (
    DAY_OF_WEEK,
    ENABLED,
    HEAT_SETPOINT,
    SCH_SCHEDULE_DHW,
    SCH_SCHEDULE_ZON,
    SWITCHPOINTS,
    TIME_OF_DAY,
)
from tests_rf.common import (
    TEST_DIR,
    abort_if_rf_test_fails,
    find_test_tcs,
    load_test_gwy,
    test_ports,
)
from tests_rf.mock import MOCKED_PORT

WORK_DIR = f"{TEST_DIR}/rf_engine"
CONFIG_FILE = "config_heat.json"


def pytest_generate_tests(metafunc):
    metafunc.parametrize("test_port", test_ports.items(), ids=test_ports.keys())


def assert_schedule_dict(schedule_full):

    if schedule_full[SZ_ZONE_IDX] == "HW":
        SCH_SCHEDULE_DHW(schedule_full)
    else:
        SCH_SCHEDULE_ZON(schedule_full)

    schedule = schedule_full[SZ_SCHEDULE]
    # assert isinstance(schedule, list)
    assert len(schedule) == 7

    for idx, day_of_week in enumerate(schedule):
        # assert isinstance(day_of_week, dict)
        assert day_of_week[DAY_OF_WEEK] == idx

        # assert isinstance(day_of_week[SWITCHPOINTS], dict)
        for switchpoint in day_of_week[SWITCHPOINTS]:
            assert isinstance(switchpoint[TIME_OF_DAY], str)
            if HEAT_SETPOINT in switchpoint:
                assert isinstance(switchpoint[HEAT_SETPOINT], float)
            else:
                assert isinstance(switchpoint[ENABLED], bool)
    return schedule


async def write_schedule(zone) -> None:

    # zone._gwy.config.disable_sending = False

    ver_old, _ = await zone.tcs._schedule_version(force_io=True)
    sch_old = await zone.get_schedule()

    sch_new = deepcopy(sch_old)

    if zone.idx == "HW":
        sch_new[0][SWITCHPOINTS][0][ENABLED] = not (
            sch_new[0][SWITCHPOINTS][0][ENABLED]
        )
    else:
        sch_new[0][SWITCHPOINTS][0][HEAT_SETPOINT] = (
            sch_new[0][SWITCHPOINTS][0][HEAT_SETPOINT] + 1
        ) % 5 + 6

    _ = await zone.set_schedule(sch_new)  # check zone._schedule._schedule

    ver_tst, _ = await zone.tcs._schedule_version(force_io=True)
    sch_tst = await zone.get_schedule()

    assert ver_old < ver_tst

    assert sch_tst != sch_old
    assert sch_tst == sch_new

    sch_end = await zone.set_schedule(sch_old)  # put things back

    assert zone._gwy.pkt_transport.serial.port == MOCKED_PORT or (sch_end == sch_old)


async def read_schedule(zone) -> dict:

    # zone._gwy.config.disable_sending = False

    schedule = await zone.get_schedule()  # RQ|0404, may: TimeoutError

    if schedule is None:
        assert zone._msgs[Code._0404].payload[SZ_TOTAL_FRAGS] is None
        return None  # TODO

    schedule = assert_schedule_dict(zone._schedule._schedule)

    assert zone._schedule._schedule[SZ_ZONE_IDX] == zone.idx
    assert zone._schedule._schedule[SZ_SCHEDULE] == zone.schedule == schedule

    zone._gwy.config.disable_sending = True
    assert schedule == await zone.get_schedule(force_io=False)

    try:
        await zone.get_schedule(force_io=True)
    except RuntimeError:  # sending is disabled
        assert True
    else:
        assert False

    return schedule


flow_marker = None


@abort_if_rf_test_fails
async def test_rq_0006(test_port):
    global flow_marker

    def assert_packet_flow(msg: Message, *args, **kwargs):
        global flow_marker

        # get the schedule version number
        if msg._pkt._hdr == f"0006|RQ|{tcs.id}":
            assert flow_marker % 10 == 0
            flow_marker += 1
        elif msg._pkt._hdr == f"0006|RP|{tcs.id}":
            assert flow_marker % 10 == 1
            flow_marker += 1

        elif msg.code == Code._0006:
            assert False, msg

    gwy = await load_test_gwy(*test_port, f"{WORK_DIR}/{CONFIG_FILE}")
    gwy.create_client(assert_packet_flow)

    tcs = find_test_tcs(gwy)

    flow_marker = 0
    version = (await tcs._schedule_version(force_io=False))[
        0
    ]  # RQ|0006, may: TimeoutError
    assert flow_marker == 2

    assert isinstance(version, int)
    assert version == tcs._msgs[Code._0006].payload["change_counter"]

    assert version == (await tcs._schedule_version(force_io=False))[0]
    assert flow_marker == 2

    flow_marker = 10
    version = (await tcs._schedule_version(force_io=True))[
        0
    ]  # RQ|0006, may: TimeoutError
    assert flow_marker == 12

    gwy.config.disable_sending = True

    version = (await tcs._schedule_version())[0]  # RQ|0006, may: TimeoutError
    assert flow_marker == 12

    try:
        await tcs._schedule_version(force_io=True)
    except RuntimeError:  # sending is disabled
        assert True
    else:
        assert False

    assert flow_marker == 12

    await gwy.stop()


@abort_if_rf_test_fails
async def test_rq_0404_dhw(test_port):  # TODO: Needs mocking

    if test_port[0] == MOCKED_PORT:  # HACK/FIXME
        return

    global flow_marker

    def assert_packet_flow(msg: Message, *args, **kwargs):
        global flow_marker

        # get the schedule version number
        if msg._pkt._hdr == f"0006|RQ|{tcs.id}":
            assert flow_marker % 10 == 0
            flow_marker += 1
        elif msg._pkt._hdr == f"0006|RP|{tcs.id}":
            assert flow_marker % 10 == 1
            flow_marker += 1

        # get the first schedule fragment, is possibly the last fragment too
        elif msg._pkt._hdr == f"0404|RQ|{tcs.id}|{tcs.zones[0].idx}01":
            assert flow_marker % 10 == 2
            flow_marker += 1
        elif msg._pkt._hdr == f"0404|RP|{tcs.id}|{tcs.zones[0].idx}01":
            assert flow_marker % 10 == 3
            if msg.payload["frag_number"] < msg.payload["total_frags"]:
                flow_marker += 1
            else:
                flow_marker += 2

        # get the subsequent schedule fragments, until the last fragment
        elif msg._pkt._hdr[:20] == f"0404|RQ|{tcs.id}|{tcs.zones[0].idx}":
            assert flow_marker % 10 == 4
            flow_marker += 1
        elif msg._pkt._hdr[:20] == f"0404|RP|{tcs.id}|{tcs.zones[0].idx}":
            assert flow_marker % 10 == 5
            if msg.payload["frag_number"] < msg.payload["total_frags"]:
                flow_marker -= 1
            else:
                flow_marker += 1

        elif msg.code in (Code._0006, Code._0404):
            assert False, msg

    gwy = await load_test_gwy(*test_port, f"{WORK_DIR}/{CONFIG_FILE}")
    gwy.create_client(assert_packet_flow)

    tcs = find_test_tcs(gwy)

    flow_marker = 0
    if tcs.dhw:  # issue here
        await read_schedule(tcs.dhw)
    assert flow_marker == 6

    await gwy.stop()


@abort_if_rf_test_fails
async def test_rq_0404_zone(test_port):
    global flow_marker

    def assert_packet_flow(msg: Message, *args, **kwargs):
        global flow_marker

        # get the schedule version number
        if msg._pkt._hdr == f"0006|RQ|{tcs.id}":
            assert flow_marker % 10 == 0
            flow_marker += 1
        elif msg._pkt._hdr == f"0006|RP|{tcs.id}":
            assert flow_marker % 10 == 1
            flow_marker += 1

        # get the first schedule fragment, is possibly the last fragment too
        elif msg._pkt._hdr == f"0404|RQ|{tcs.id}|{tcs.zones[0].idx}01":
            assert flow_marker % 10 == 2
            flow_marker += 1
        elif msg._pkt._hdr == f"0404|RP|{tcs.id}|{tcs.zones[0].idx}01":
            assert flow_marker % 10 == 3
            if msg.payload["frag_number"] < msg.payload["total_frags"]:
                flow_marker += 1
            else:
                flow_marker += 2

        # get the subsequent schedule fragments, until the last fragment
        elif msg._pkt._hdr[:20] == f"0404|RQ|{tcs.id}|{tcs.zones[0].idx}":
            assert flow_marker % 10 == 4
            flow_marker += 1
        elif msg._pkt._hdr[:20] == f"0404|RP|{tcs.id}|{tcs.zones[0].idx}":
            assert flow_marker % 10 == 5
            if msg.payload["frag_number"] < msg.payload["total_frags"]:
                flow_marker -= 1
            else:
                flow_marker += 1

        elif msg.code in (Code._0006, Code._0404):
            assert False, msg

    gwy = await load_test_gwy(*test_port, f"{WORK_DIR}/{CONFIG_FILE}")
    gwy.create_client(assert_packet_flow)

    tcs = find_test_tcs(gwy)

    flow_marker = 0
    # if tcs.zones:
    await read_schedule(tcs.zones[0])
    assert flow_marker == 6

    await gwy.stop()


@abort_if_rf_test_fails
async def _test_ww_0404_dhw(test_port):
    global flow_marker

    def assert_packet_flow(msg: Message, *args, **kwargs):
        global flow_marker

    gwy = await load_test_gwy(*test_port, f"{WORK_DIR}/{CONFIG_FILE}")
    gwy.create_client(assert_packet_flow)

    tcs = find_test_tcs(gwy)

    if tcs.dhw:
        await write_schedule(tcs.dhw)

    await gwy.stop()


@abort_if_rf_test_fails
async def _test_ww_0404_zone(test_port):

    gwy = await load_test_gwy(*test_port, f"{WORK_DIR}/{CONFIG_FILE}")
    tcs = find_test_tcs(gwy)

    if tcs.zones:
        await write_schedule(tcs.zones[0])

    await gwy.stop()
