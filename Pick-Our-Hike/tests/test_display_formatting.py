from pick_our_hike.display_formatting import DisplayFormat


def test_format_uses_structured_preferences_and_exact_conversion():
    display = DisplayFormat.from_trip({'distance_unit': 'miles', 'elevation_unit': 'm', 'clock_format': '12h'})
    assert display.distance(6.437376) == '4 miles'
    assert display.elevation(200) == '200 m'
    assert display.clock('13:00') == '1 PM'
    assert display.clock('18:15') == '6:15 PM'
    assert display.pace(20) == '32.19 min/mile'
    assert display.text('Sam: 6 -> 7 km') == 'Sam: 3.73 miles -> 4.35 miles'


def test_metric_and_feet_preferences():
    display = DisplayFormat.from_trip({'distance_unit': 'km', 'elevation_unit': 'ft', 'clock_format': '24h'})
    assert display.distance(5) == '5 km'
    assert display.elevation(274.32) == '900 ft'
    assert display.clock('14:30') == '14:30'
    assert DisplayFormat().clock('08:00') == '8 AM'


def test_durations_use_hours_and_minutes_without_changing_pace():
    display = DisplayFormat()
    assert display.duration(287) == '4 hr 47 min'
    assert display.duration(60) == '1 hr'
    assert display.duration(49) == '49 min'
    assert display.text('Outing 287.0 min; 540 min available; drive 120 minutes') == 'Outing 4 hr 47 min; 9 hr available; drive 2 hr'
    assert display.text('Pace 90 min/mile') == 'Pace 90 min/mile'
