def compute_availability(runtime, planned_time):
    if planned_time == 0:
        return 0
    return runtime / planned_time


def compute_performance(ideal_cycle, total_count, runtime):
    if runtime == 0:
        return 0
    return (ideal_cycle * total_count) / runtime


def compute_quality(good, total):
    if total == 0:
        return 0
    return good / total


def compute_oee(a, p, q):
    return a * p * q