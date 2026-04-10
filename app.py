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
from printer_service import print_label

app = Flask(__name__)
app.secret_key = "labelpro_secret_key_change_in_prod"

opc = OPCUAClient()

live_data = {
    "connected": False,
    "current_order_id": None,
    "station_state": "UNKNOWN",
    "total_count": 0,
    "good_count": 0,
    "completion_status": False,
    "print_status": False,
    "label_text": "",
    "message": "",
    # Set True when PLC fires label_request in MANUAL mode — alerts operator
    "print_pending": False,
}

# -- Print mode settings --
# auto_print: True  = MES auto-responds to label_request with the order's label_text
# auto_print: False = MES sets print_pending and waits for operator to submit
print_settings = {
    "auto_print": False,
}

# -- Background state --
completion_latched      = False
_last_station_state_raw = -1
_last_total_count       = 0
_last_good_count        = 0
_order_total_count      = 0
_order_good_count       = 0


def restore_active_order():
    """On startup, restore any order that was active when the app last stopped."""
    global _last_station_state_raw
    active = get_active_order()
    if active:
        live_data["current_order_id"] = active["order_id"]
        _last_station_state_raw = 1
        live_data["message"] = (
            f"Restored active order #{active['order_id']} "
            f"'{active['product_name']}' after restart."
        )


def background_loop():
    global completion_latched
    global _last_station_state_raw
    global _last_total_count, _last_good_count
    global _order_total_count, _order_good_count

    while True:
        try:
            snapshot = opc.read_all()
            live_data["connected"] = True

            station_state_raw = int(snapshot["station_state"])
            plc_total_count   = int(snapshot["total_count"])
            plc_good_count    = int(snapshot["good_count"])
            completion_status = bool(snapshot["completion_status"])
            label_request     = bool(snapshot["label_request"])
            label_text        = str(snapshot["label_text"])
            print_status      = bool(snapshot["print_status"])

            # ----------------------------------------------------------------
            # Detect IDLE -> ACTIVE: pop next queued order
            # ----------------------------------------------------------------
            if _last_station_state_raw != 1 and station_state_raw == 1:
                next_order = pop_next_order()
                if next_order:
                    live_data["current_order_id"] = next_order["order_id"]
                    live_data["print_pending"]     = False
                    _last_total_count  = plc_total_count
                    _last_good_count   = plc_good_count
                    _order_total_count = 0
                    _order_good_count  = 0
                    completion_latched = False
                    live_data["message"] = (
                        f"Order #{next_order['order_id']} "
                        f"'{next_order['product_name']}' started."
                    )
                else:
                    live_data["message"] = (
                        "Station went ACTIVE but no order is queued. "
                        "Add an order to the queue."
                    )

            _last_station_state_raw = station_state_raw

            # ----------------------------------------------------------------
            # Accumulate counts (delta from PLC counters per order)
            # ----------------------------------------------------------------
            if plc_total_count >= _last_total_count:
                _order_total_count += plc_total_count - _last_total_count
            if plc_good_count >= _last_good_count:
                _order_good_count += plc_good_count - _last_good_count

            _last_total_count = plc_total_count
            _last_good_count  = plc_good_count

            # ----------------------------------------------------------------
            # Print handshake
            # PLC sets label_request=TRUE when it needs a label printed.
            # MES prints and writes print_status=TRUE to release the PLC.
            # ----------------------------------------------------------------
            if label_request and not print_status:
                current_order_id = live_data["current_order_id"]
                order = get_order(current_order_id) if current_order_id else None
                order_label = order["label_text"] if order else ""

                if print_settings["auto_print"]:
                    # AUTO — print the order's preset label immediately
                    success = print_label(order_label)
                    opc.write_string("label_text", order_label)
                    opc.write_bool("print_status", success)
                    live_data["print_status"]  = success
                    live_data["label_text"]    = order_label
                    live_data["print_pending"] = False
                    live_data["message"] = (
                        f"Auto-print: '{order_label}' — "
                        + ("OK" if success else "FAILED — check printer.")
                    )
                else:
                    # MANUAL — alert dashboard; operator must submit label text
                    live_data["print_pending"] = True
                    live_data["message"] = (
                        "⚠ Print requested by PLC — enter label text and submit."
                    )

            # Clear pending flag once PLC drops its request
            if not label_request:
                live_data["print_pending"] = False

            # ----------------------------------------------------------------
            # Update live_data
            # ----------------------------------------------------------------
            live_data["station_state"]     = STATE_MAP.get(station_state_raw, "UNKNOWN")
            live_data["total_count"]       = _order_total_count
            live_data["good_count"]        = _order_good_count
            live_data["completion_status"] = completion_status

            # Mirror PLC print_status only when not mid auto-handshake
            if not (label_request and print_settings["auto_print"]):
                live_data["print_status"] = print_status
                live_data["label_text"]   = label_text

            # ----------------------------------------------------------------
            # Order completion
            # ----------------------------------------------------------------
            current_order_id = live_data["current_order_id"]

            if current_order_id and completion_status and not completion_latched:
                complete_order(current_order_id)
                completion_latched = True
                live_data["message"] = f"Order #{current_order_id} completed."

            if not completion_status:
                completion_latched = False

        except Exception as exc:
            live_data["connected"] = False
            live_data["message"]   = f"OPC UA error: {exc}"

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
            session["role"]     = user["role"]
            return redirect(url_for(
                "dashboard" if user["role"] == "operator" else "viewer"
            ))
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
    queue        = get_queued_orders()
    active_order = get_order(live_data["current_order_id"]) if live_data["current_order_id"] else None
    return render_template("dashboard.html",
                           data=live_data,
                           queue=queue,
                           active_order=active_order,
                           print_settings=print_settings)


@app.route("/add_order", methods=["POST"])
@operator_required
def add_order():
    try:
        product_name = request.form.get("product_name", "").strip()
        label_text   = request.form.get("label_text", "").strip()
        planned_qty  = int(request.form.get("planned_quantity", 1))
        ideal_cycle  = float(request.form.get("ideal_cycle_time", 11.5))

        if not product_name:
            live_data["message"] = "Product name cannot be empty."
            return redirect("/")
        if not label_text:
            live_data["message"] = "Label text cannot be empty."
            return redirect("/")
        if planned_qty < 1:
            live_data["message"] = "Planned quantity must be at least 1."
            return redirect("/")
        if ideal_cycle <= 0:
            live_data["message"] = "Ideal cycle time must be greater than 0."
            return redirect("/")

        order_id     = add_order_to_queue(product_name, label_text, planned_qty, ideal_cycle)
        planned_time = planned_qty * ideal_cycle
        live_data["message"] = (
            f"Order #{order_id} '{product_name}' added — "
            f"{planned_qty} parts × {ideal_cycle}s = {planned_time:.0f}s planned. "
            f"Label: '{label_text}'."
        )
    except Exception as exc:
        live_data["message"] = f"Error adding order: {exc}"
    return redirect("/")


@app.route("/set_print_mode", methods=["POST"])
@operator_required
def set_print_mode():
    mode = request.form.get("print_mode", "manual")
    print_settings["auto_print"] = (mode == "auto")
    live_data["message"] = (
        f"Print mode set to {'AUTO' if print_settings['auto_print'] else 'MANUAL'}."
    )
    return redirect("/")


@app.route("/print_label", methods=["POST"])
@operator_required
def handle_print():
    """Manual print — operator enters label text and submits.
    Writes print_status TRUE back to PLC so the labelling sequence continues."""
    try:
        label_text = request.form.get("label_text", "").strip()
        if not label_text:
            live_data["message"] = "Label text cannot be empty."
            return redirect("/")

        success = print_label(label_text)
        opc.write_string("label_text", label_text)
        opc.write_bool("print_status", success)

        live_data["label_text"]    = label_text
        live_data["print_status"]  = success
        live_data["print_pending"] = False
        live_data["message"] = (
            "Label sent successfully." if success else "Printing failed — check printer."
        )
    except Exception as exc:
        live_data["message"] = f"Printer/MES error: {exc}"
    return redirect("/")


# ------------------------------------------------------------------
# Shared routes (both roles)
# ------------------------------------------------------------------

@app.route("/viewer")
@login_required
def viewer():
    queue        = get_queued_orders()
    active_order = get_order(live_data["current_order_id"]) if live_data["current_order_id"] else None
    return render_template("viewer.html", data=live_data, queue=queue, active_order=active_order)


@app.route("/history")
@login_required
def history():
    summaries = get_all_order_summaries()
    totals    = get_aggregate_totals()
    return render_template("history.html", summaries=summaries,
                           totals=totals, role=session.get("role"))


# ------------------------------------------------------------------
# Startup
# ------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    opc.connect()
    restore_active_order()

    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()

    app.run(debug=True)
