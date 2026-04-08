import random

state = 1
runtime = 0
total = 0
good = 0


def get_mock_data():
    global runtime, total, good, state

    runtime += 1

    if runtime % 3 == 0:
        total += 1
        if random.random() > 0.2:
            good += 1

    if runtime > 15:
        completion = True
    else:
        completion = False

    return {
        "current_order_id": 101,
        "station_state": state,
        "run_time": runtime,
        "total_count": total,
        "good_count": good,
        "completion_status": completion
    }