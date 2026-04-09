from flask import Flask, render_template, request, redirect
import threading
import time

from config import POLL_INTERVAL, STATE_MAP
from opcua_client import OPCUAClient
from repository import (
    init_db,
    ensure_order_exists,
    get_order,
    complete_order,
    insert_oee_record,
    insert_order_summary,
    get_all_order_summaries,
    get_aggregate_totals,
)
from oee import compute_oee
from printer_service import print_label

app = Flask(__name__)

opc = OPCUAClient()

live_data = {
    "connected": False,
    "current_order_id": 0,
    "station_state": "UNKNOWN",
    "run_time": 0.0,        # accumulated runtime in seconds (for OEE math)
    "run_time_min": 0.0,    # display value in minutes
    "total_count": 0,
    "good_count": 0,
    "completion_status": False,
    "availability": 0.0,
    "performance": 0.0,
    "quality": 0.0,
    "oee": 0.0,
    "print_status": False,
    "label_text": "",
    "message": "",
}

completion_latched = False

# Tracks the last raw PLC runtime value so we can detect resets
_last_plc_runtime = 0.0
# Accumulated runtime that survives PLC resets within the same order
_accumulated_runtime = 0.0
# The order_id we were accumulating for — reset accumulator on new order
_accumulating_for_order = None
# Frozen OEE snapshot held after completion so the dashboard doesn't blank out
_frozen_oee = None


def background_loop():
    global completion_latched
    global _last_plc_runtime, _accumulated_runtime, _accumulating_for_order
    global _frozen_oee

    while True:
        try:
            snapshot = opc.read_all()
            live_data["connected"] = True

            current_order_id = int(snapshot["current_order_id"])
            station_state_raw = int(snapshot["station_state"])
            plc_runtime = float(snapshot["run_time"])
            total_count = int(snapshot["total_count"])
            good_count = int(snapshot["good_count"])
            completion_status = bool(snapshot["completion_status"])
            print_status = bool(snapshot["print_status"])
            label_text = str(snapshot["label_text"])

            # ----------------------------------------------------------------
            # Accumulate runtime — handle PLC resets and new orders
            # ----------------------------------------------------------------
            if current_order_id != _accumulating_for_order:
                # New order started — reset accumulator
                _accumulated_runtime = 0.0
                _last_plc_runtime = plc_runtime
                _accumulating_for_order = current_order_id
                _frozen_oee = None

            if plc_runtime < _last_plc_runtime:
                # PLC counter reset (end of cycle) — bank whatever ran
                _accumulated_runtime += _last_plc_runtime

            _last_plc_runtime = plc_runtime
            total_runtime = _accumulated_runtime + plc_runtime  # seconds

            # ----------------------------------------------------------------
            # Update live_data with raw fields
            # ----------------------------------------------------------------
            live_data["current_order_id"] = current_order_id
            live_data["station_state"] = STATE_MAP.get(station_state_raw, "UNKNOWN")
            live_data["run_time"] = round(total_runtime, 2)
            live_data["run_time_min"] = round(total_runtime / 60.0, 2)
            live_data["total_count"] = total_count
            live_data["good_count"] = good_count
            live_data["completion_status"] = completion_status
            live_data["print_status"] = print_status
            live_data["label_text"] = label_text

            # ----------------------------------------------------------------
            # OEE calculation
            # ----------------------------------------------------------------
            if current_order_id > 0:
                ensure_order_exists(current_order_id)
                order = get_order(current_order_id)

                if order:
                    planned_production_time = float(order["planned_production_time"])
                    ideal_cycle_time = float(order["ideal_cycle_time"])

                    # Only recalculate OEE while the order is still running.
                    # Once completed, keep the frozen snapshot so numbers don't
                    # drop to zero when the PLC resets its counters.
                    if not completion_latched:
                        oee_data = compute_oee(
                            runtime=total_runtime,
                            planned_production_time=planned_production_time,
                            ideal_cycle_time=ideal_cycle_time,
                            total_count=total_count,
                            good_count=good_count,
                        )

                        live_data["availability"] = round(oee_data["availability"] * 100, 2)
                        live_data["performance"] = round(oee_data["performance"] * 100, 2)
                        live_data["quality"] = round(oee_data["quality"] * 100, 2)
                        live_data["oee"] = round(oee_data["oee"] * 100, 2)

                        insert_oee_record(
                            order_id=current_order_id,
                            runtime=total_runtime,
                            total_count=total_count,
                            good_count=good_count,
                            state=live_data["station_state"],
                            availability=oee_data["availability"],
                            performance=oee_data["performance"],
                            quality=oee_data["quality"],
                            oee_value=oee_data["oee"],
                        )

                    # Completion latch — mark order done, freeze OEE, save summary
                    if completion_status and not completion_latched:
                        complete_order(current_order_id)
                        completion_latched = True

                        # Freeze the last good OEE so the dashboard keeps it
                        _frozen_oee = {
                            "availability": live_data["availability"],
                            "performance": live_data["performance"],
                            "quality": live_data["quality"],
                            "oee": live_data["oee"],
                        }

                        # Save final summary record for this order
                        insert_order_summary(
                            order_id=current_order_id,
                            total_runtime=total_runtime,
                            total_count=total_count,
                            good_count=good_count,
                            availability=oee_data["availability"],
                            performance=oee_data["performance"],
                            quality=oee_data["quality"],
                            oee_value=oee_data["oee"],
                        )

                    if not completion_status:
                        completion_latched = False
                        _frozen_oee = None

                    # Restore frozen numbers if we're in the latched state
                    if completion_latched and _frozen_oee:
                        live_data["availability"] = _frozen_oee["availability"]
                        live_data["performance"] = _frozen_oee["performance"]
                        live_data["quality"] = _frozen_oee["quality"]
                        live_data["oee"] = _frozen_oee["oee"]

        except Exception as exc:
            live_data["connected"] = False
            live_data["message"] = f"OPC UA error: {exc}"

        time.sleep(POLL_INTERVAL)


@app.route("/")
def dashboard():
    return render_template("dashboard.html", data=live_data)


@app.route("/history")
def history():
    summaries = get_all_order_summaries()
    totals = get_aggregate_totals()
    return render_template("history.html", summaries=summaries, totals=totals)


@app.route("/print_label", methods=["POST"])
def handle_print():
    try:
        label_text = request.form.get("label_text", "").strip()

        if not label_text:
            live_data["message"] = "Label text cannot be empty."
            return redirect("/")

        success = print_label(label_text)

        opc.write_string("label_text", label_text)
        opc.write_bool("print_status", success)

        live_data["label_text"] = label_text
        live_data["print_status"] = success
        live_data["message"] = "Label sent successfully." if success else "Printing failed."

    except Exception as exc:
        live_data["message"] = f"Printer/MES error: {exc}"

    return redirect("/")


if __name__ == "__main__":
    init_db()
    opc.connect()

    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()

    app.run(debug=True)
