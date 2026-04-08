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
)
from oee import compute_oee
from printer_service import print_label

app = Flask(__name__)

opc = OPCUAClient()

live_data = {
    "connected": False,
    "current_order_id": 0,
    "station_state": "UNKNOWN",
    "run_time": 0.0,
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


def background_loop():
    global completion_latched

    while True:
        try:
            snapshot = opc.read_all()
            live_data["connected"] = True

            current_order_id = int(snapshot["current_order_id"])
            station_state_raw = int(snapshot["station_state"])
            run_time = float(snapshot["run_time"])
            total_count = int(snapshot["total_count"])
            good_count = int(snapshot["good_count"])
            completion_status = bool(snapshot["completion_status"])
            print_status = bool(snapshot["print_status"])
            label_text = str(snapshot["label_text"])

            live_data["current_order_id"] = current_order_id
            live_data["station_state"] = STATE_MAP.get(station_state_raw, "UNKNOWN")
            live_data["run_time"] = round(run_time, 2)
            live_data["total_count"] = total_count
            live_data["good_count"] = good_count
            live_data["completion_status"] = completion_status
            live_data["print_status"] = print_status
            live_data["label_text"] = label_text

            if current_order_id > 0:
                ensure_order_exists(current_order_id)
                order = get_order(current_order_id)

                if order:
                    planned_production_time = float(order["planned_production_time"])
                    ideal_cycle_time = float(order["ideal_cycle_time"])

                    oee_data = compute_oee(
                        runtime=run_time,
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
                        runtime=run_time,
                        total_count=total_count,
                        good_count=good_count,
                        state=live_data["station_state"],
                        availability=oee_data["availability"],
                        performance=oee_data["performance"],
                        quality=oee_data["quality"],
                        oee_value=oee_data["oee"],
                    )

                    if completion_status and not completion_latched:
                        complete_order(current_order_id)
                        completion_latched = True

                    if not completion_status:
                        completion_latched = False

        except Exception as exc:
            live_data["connected"] = False
            live_data["message"] = f"OPC UA error: {exc}"

        time.sleep(POLL_INTERVAL)


@app.route("/")
def dashboard():
    return render_template("dashboard.html", data=live_data)


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