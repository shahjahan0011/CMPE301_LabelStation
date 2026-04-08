def compute_availability(runtime, planned_production_time):
    if planned_production_time <= 0:
        return 0.0
    return runtime / planned_production_time


def compute_performance(ideal_cycle_time, total_count, runtime):
    if runtime <= 0:
        return 0.0
    return (ideal_cycle_time * total_count) / runtime


def compute_quality(good_count, total_count):
    if total_count <= 0:
        return 0.0
    return good_count / total_count


def compute_oee(runtime, planned_production_time, ideal_cycle_time, total_count, good_count):
    availability = compute_availability(runtime, planned_production_time)
    performance = compute_performance(ideal_cycle_time, total_count, runtime)
    quality = compute_quality(good_count, total_count)
    oee = availability * performance * quality

    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": oee,
    }