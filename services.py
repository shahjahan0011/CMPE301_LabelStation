from repository import insert_oee, complete_order, activate_next_order
from oee import *


def process(snapshot, active_order):
    if not active_order:
        return None

    order_id = active_order[0]
    planned_time = active_order[3]
    ideal_cycle = active_order[4]

    runtime = snapshot["run_time"]
    total = snapshot["total_count"]
    good = snapshot["good_count"]

    a = compute_availability(runtime, planned_time)
    p = compute_performance(ideal_cycle, total, runtime)
    q = compute_quality(good, total)
    oee = compute_oee(a, p, q)

    if snapshot["completion_status"]:
        record = type("OEE", (), {})()
        record.order_id = order_id
        record.runtime = runtime
        record.total_count = total
        record.good_count = good
        record.availability = a
        record.performance = p
        record.quality = q
        record.oee = oee

        insert_oee(record)
        complete_order(order_id)
        activate_next_order()

    return {
        "availability": round(a, 2),
        "performance": round(p, 2),
        "quality": round(q, 2),
        "oee": round(oee, 2)
    }