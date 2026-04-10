def compute_oee(run_time, planned_production_time, ideal_cycle_time,
                total_count, good_count):
    """
    Availability = run_time / planned_production_time
    Performance  = (ideal_cycle_time * total_count) / run_time
    Quality      = good_count / total_count
    OEE          = A * P * Q
    All values clamped to [0, 1].
    """
    availability = 0.0
    performance  = 0.0
    quality      = 0.0

    if planned_production_time > 0:
        availability = min(run_time / planned_production_time, 1.0)

    if run_time > 0 and total_count > 0:
        performance = min((ideal_cycle_time * total_count) / run_time, 1.0)

    if total_count > 0:
        quality = good_count / total_count

    oee = availability * performance * quality

    return {
        "availability": availability,
        "performance":  performance,
        "quality":      quality,
        "oee":          oee,
    }
