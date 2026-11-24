from app.catalog import SPEC
from app.domain.calculate import calculate_rows
from app.domain.decision import decide_rows
from app.domain.prepare import prepare_rows
from app.intake.service import load

CLEAN = [{'building_id': 'B1',
  'meter_id': 'M1',
  'room_id': 'R1',
  'area_m2': '100',
  'start_reading': '1000',
  'end_reading': '1100',
  'main_kwh': '500'},
 {'building_id': 'B1',
  'meter_id': 'M2',
  'room_id': 'R2',
  'area_m2': '100',
  'start_reading': '500',
  'end_reading': '600',
  'main_kwh': '500'},
 {'building_id': 'B1',
  'meter_id': 'M3',
  'room_id': 'R3',
  'area_m2': '200',
  'start_reading': '800',
  'end_reading': '1000',
  'main_kwh': '500'},
 {'building_id': 'B2',
  'meter_id': 'M4',
  'room_id': 'R4',
  'area_m2': '50',
  'start_reading': '0',
  'end_reading': '50',
  'main_kwh': '250'},
 {'building_id': 'B2',
  'meter_id': 'M5',
  'room_id': 'R5',
  'area_m2': '150',
  'start_reading': '0',
  'end_reading': '150',
  'main_kwh': '250'}]


def row(**changes):
    item = dict(CLEAN[0])
    item.update(changes)
    return item


def calc(rows):
    items, issues = prepare_rows(rows)
    return calculate_rows(items), issues


def run(rows):
    items, issues = prepare_rows(rows)
    return decide_rows(calculate_rows(items)), issues


def run_profile(profile):
    return run(load(profile)["rows"])
