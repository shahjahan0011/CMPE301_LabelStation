from flask import Flask, render_template, request, redirect, session, url_for
import threading
import time
from functools import wraps

from config import POLL_INTERVAL, STATE_MAP
from opcua_client import OPCUAClient
from repository import (
    init_db,
    get_order,
    complete_order,
    insert_oee_record,
    insert_order_summary,
    get_all_order_summaries,
    get_aggregate_totals,
    get_queued_orders,
    add_order_to_queue,
    pop_next_order,
    get_active_order,
    USERS,
)
from oee import compute_oee
from printer_service import print_label

app = Flask(__name__)
app.secret_key = "labelpro_secret_key_change_in_prod"

opc = OPCUAClient()

live_data = {
    "connected": False,
    "current_order_id": None,
    "station_state": "UNKNOWN",
    "run_time": 0.0,
    "run_time_min": 0.0,
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
_last_plc_runtime = 0.0
_accumulated_runtime = 0.0
_frozen_oee = None
_last_station_state_raw = -1
_last_total_count = 0
_last_good_count = 0
_order_total_count = 0
_order_good_count = 0


def restore_active_order():
    """On startup, check if there's already an active order in the DB
    (e.g. app restarted mid-run) and restore it into live_data so we
    don't lose the current order on restart."""
    global _last_station_state_raw
    active = get_active_order()
    if active:
        live_data["current_order_id"] = active["order_id"]
        # Set last state to ACTIVE (1) so the IDLE->ACTIVE transition
        # doesn't fire again and double-pop the queue
        _last_station_state_raw = 1
        live_data["message"] = f"Restored active order {active['order_id']} after restart."


def background_loop():
    global completion_latched
    global _last_plc_runtime, _accumulated_runtime, _frozen_oee
    global _last_station_state_raw
    global _last_total_count, _last_good_count
    global _order_total_count, _order_good_count

    while True:
        try:
            snapshot = opc.read_all()
            live_data["connected"] = True

            station_state_raw = int(snapshot["station_state"])
            plc_runtime = float(snapshot["run_time"])
            plc_total_count = int(snapshot["total_count"])
            plc_good_count = int(snapshot["good_count"])
            completion_status = bool(snapshot["completion_status"])
            print_status = bool(snapshot["print_status"])
            label_text = str(snapshot["label_text"])

            # ----------------------------------------------------------------
            # Detect IDLE -> ACTIVE transition: pop next queued order
            # ----------------------------------------------------------------
            if _last_station_state_raw != 1 and station_state_raw == 1:
                next_order = pop_next_order()
                if next_order:
                    live_data["current_order_id"] = next_order["order_id"]
                    _accumulated_runtime = 0.0
                    _last_plc_runtime = plc_runtime
                    _frozen_oee = None
                    _last_total_count = plc_total_count
                    _last_good_count = plc_good_count
                    _order_total_count = 0
                    _order_good_count = 0
                    completion_latched = False

            _last_station_state_raw = station_state_raw

            # ----------------------------------------------------------------
            # Accumulate runtime — bank value when PLC counter resets
            # ----------------------------------------------------------------
            if plc_runtime < _last_plc_runtime:
                _accumulated_runtime += _last_plc_runtime
            _last_plc_runtime = plc_runtime
            total_runtime = _accumulated_runtime + plc_runtime

            # ----------------------------------------------------------------
            # Accumulate counts — track deltas so PLC resets don't zero out
            # ----------------------------------------------------------------
            if plc_total_count >= _last_total_count:
                _order_total_count += plc_total_count - _last_total_count
            if plc_good_count >= _last_good_count:
                _order_good_count += plc_good_count - _last_good_count

            _last_total_count = plc_total_count
            _last_good_count = plc_good_count

            # ----------------------------------------------------------------
            # Update live_data
            # ----------------------------------------------------------------
            live_data["station_state"] = STATE_MAP.get(station_state_raw, "UNKNOWN")
            live_data["run_time"] = round(total_runtime, 2)
            live_data["run_time_min"] = round(total_runtime / 60.0, 2)
            live_data["total_count"] = _order_total_count
            live_data["good_count"] = _order_good_count
            live_data["completion_status"] = completion_status
            live_data["print_status"] = print_status
            live_data["label_text"] = label_text

            # ----------------------------------------------------------------
            # OEE calculation
            # ----------------------------------------------------------------
            current_order_id = live_data["current_order_id"]

            if current_order_id:
                order = get_order(current_order_id)

                if order:
                    planned_production_time = float(order["planned_production_time"])
                    ideal_cycle_time = float(order["ideal_cycle_time"])

                    # Always compute oee_data so it's available for the
                    # completion block below regardless of latch state
                    oee_data = compute_oee(
                        runtime=total_runtime,
                        planned_production_time=planned_production_time,
                        ideal_cycle_time=ideal_cycle_time,
                        total_count=_order_total_count,
                        good_count=_order_good_count,
                    )

                    if not completion_latched:
                        live_data["availability"] = round(oee_data["availability"] * 100, 2)
                        live_data["performance"] = round(oee_data["performance"] * 100, 2)
                        live_data["quality"] = round(oee_data["quality"] * 100, 2)
                        live_data["oee"] = round(oee_data["oee"] * 100, 2)

                    # Completion latch — runs only once per order
                    if completion_status and not completion_latched:
                        complete_order(current_order_id)
                        completion_latched = True

                        _frozen_oee = {
                            "availability": live_data["availability"],
                            "performance": live_data["performance"],
                            "quality": live_data["quality"],
                            "oee": live_data["oee"],
                        }

                        # Write the final OEE record and summary once at completion
                        insert_oee_record(
                            order_id=current_order_id,
                            runtime=total_runtime,
                            total_count=_order_total_count,
                            good_count=_order_good_count,
                            state=live_data["station_state"],
                            availability=oee_data["availability"],
                            performance=oee_data["performance"],
                            quality=oee_data["quality"],
                            oee_value=oee_data["oee"],
                        )

                        insert_order_summary(
                            order_id=current_order_id,
                            total_runtime=total_runtime,
                            total_count=_order_total_count,
                            good_count=_order_good_count,
                            availability=oee_data["availability"],
                            performance=oee_data["performance"],
                            quality=oee_data["quality"],
                            oee_value=oee_data["oee"],
                        )

                    # Reset latch when completion signal clears
                    if not completion_status:
                        completion_latched = False
                        _frozen_oee = None

                    # Hold frozen OEE on screen after completion
                    if completion_latched and _frozen_oee:
                        live_data["availability"] = _frozen_oee["availability"]
                        live_data["performance"] = _frozen_oee["performance"]
                        live_data["quality"] = _frozen_oee["quality"]
                        live_data["oee"] = _frozen_oee["oee"]

        except Exception as exc:
            live_data["connected"] = False
            live_data["message"] = f"OPC UA error: {exc}"

        time.sleep(POLL_INTERVAL)


# ------------------------------------------------------------------
# Auth helpers
# ------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def operator_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        if session.get("role") != "operator":
            return redirect(url_for("viewer"))
        return f(*args, **kwargs)
    return decorated


# ------------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = USERS.get(username)
        if user and user["password"] == password:
            session["username"] = username
            session["role"] = user["role"]
            if user["role"] == "operator":
                return redirect(url_for("dashboard"))
            else:
                return redirect(url_for("viewer"))
        else:
            error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------
# Operator routes
# ------------------------------------------------------------------

@app.route("/")
@operator_required
def dashboard():
    queue = get_queued_orders()
    return render_template("dashboard.html", data=live_data, queue=queue)


@app.route("/add_order", methods=["POST"])
@operator_required
def add_order():
    try:
        product_name = request.form.get("product_name", "").strip()
        planned_quantity = int(request.form.get("planned_quantity", 1))
        ideal_cycle_time = float(request.form.get("ideal_cycle_time", 11.5))

        if not product_name:
            live_data["message"] = "Product name cannot be empty."
            return redirect("/")

        if planned_quantity < 1:
            live_data["message"] = "Planned quantity must be at least 1."
            return redirect("/")

        if ideal_cycle_time <= 0:
            live_data["message"] = "Ideal cycle time must be greater than 0."
            return redirect("/")

        order_id = add_order_to_queue(product_name, planned_quantity, ideal_cycle_time)
        planned_time = planned_quantity * ideal_cycle_time
        live_data["message"] = (
            f"Order #{order_id} for '{product_name}' added — "
            f"{planned_quantity} parts × {ideal_cycle_time}s = {planned_time:.0f}s planned."
        )
    except Exception as exc:
        live_data["message"] = f"Error adding order: {exc}"
    return redirect("/")


@app.route("/print_label", methods=["POST"])
@operator_required
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


# ------------------------------------------------------------------
# Shared routes (both roles)
# ------------------------------------------------------------------

@app.route("/viewer")
@login_required
def viewer():
    queue = get_queued_orders()
    return render_template("viewer.html", data=live_data, queue=queue)


@app.route("/history")
@login_required
def history():
    summaries = get_all_order_summaries()
    totals = get_aggregate_totals()
    return render_template("history.html", summaries=summaries, totals=totals,
                           role=session.get("role"))


if __name__ == "__main__":
    init_db()
    opc.connect()
    restore_active_order()

    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()

    app.run(debug=True)
