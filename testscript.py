from datetime import datetime
from notion_helper import create_notion_event, parse_time_range

def run_tests():
    date_str = "2026-07-16"  # arbitrary fixed date for testing
    passed = 0
    failed = 0

    test_cases = [
        # (input_str, expected_start "HH:MM", expected_end "HH:MM")
        ("7-9pm",        "19:00", "21:00"),
        ("11:30am-1pm",  "11:30", "13:00"),
        ("8pm-9pm",      "20:00", "21:00"),
        ("11:30-1pm",    "11:30", "13:00"),  # lunch-time edge case
        ("12-1pm",       "12:00", "13:00"),  # noon edge case
        ("12-1am",       "00:00", "01:00"),  # midnight edge case
        ("9-11am",       "09:00", "11:00"),
        ("10:15am-12pm", "10:15", "12:00"),
    ]

    for time_str, expected_start, expected_end in test_cases:
        start_dt, end_dt = parse_time_range(time_str, date_str)
        actual_start = start_dt.strftime("%H:%M")
        actual_end = end_dt.strftime("%H:%M")

        if actual_start == expected_start and actual_end == expected_end:
            print(f"✅ PASS: '{time_str}' -> {actual_start}-{actual_end}")
            passed += 1
        else:
            print(f"❌ FAIL: '{time_str}' -> got {actual_start}-{actual_end}, expected {expected_start}-{expected_end}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")


def run_split_tests():
    """Tests the covered/remainder splitting logic without touching Notion."""
    date_str = "2026-07-16"

    split_cases = [
        # (full_shift, covered_time, expected_remainders as list of "HH:MM-HH:MM")
        ("7-9pm", "7-8pm", ["20:00-21:00"]),          # covered at start -> one remainder after
        ("7-9pm", "8-9pm", ["19:00-20:00"]),          # covered at end -> one remainder before
        ("7-9pm", "7:30-8:30pm", ["19:00-19:30", "20:30-21:00"]),  # covered in middle -> two remainders
        ("7-9pm", "7-9pm", []),                       # fully covered -> no remainders
    ]

    for full_time, covered_time, expected in split_cases:
        full_start, full_end = parse_time_range(full_time, date_str)
        covered_start, covered_end = parse_time_range(covered_time, date_str)

        remainders = []
        if covered_start > full_start:
            remainders.append(f"{full_start.strftime('%H:%M')}-{covered_start.strftime('%H:%M')}")
        if covered_end < full_end:
            remainders.append(f"{covered_end.strftime('%H:%M')}-{full_end.strftime('%H:%M')}")

        status = "✅ PASS" if remainders == expected else "❌ FAIL"
        print(f"{status}: shift={full_time}, covered={covered_time} -> remainders={remainders} (expected {expected})")


if __name__ == "__main__":
    print("=== Testing parse_time_range ===")
    run_tests()
    print("\n=== Testing shift splitting logic ===")
    run_split_tests()