from flask import Flask, render_template, request, redirect, session, jsonify
import threading
import time

from config import POLL_INTERVAL, STATE_MAP
from opcua_client import OPCUAClient
from repository import (
    init_db,
    create_order,
    get_active_order,
    get_order,
    get_all_orders,
    cancel_order,
    increment_printed_count,
    insert_oee_record,
    get_oee_history,
    log_print,
)
from oee import compute_oee
from printer_service import print_label

app = Flask(__name__)
app.secret_key = "mes-secret-key-change-in-prod"

opc = OPCUAClient()

IDEAL_CYCLE_TIME = 11.5

live_data = {
    "connected":               False,
    "station_state":           "UNKNOWN",
    "run_time":                0.0,
    "last_cycle_time":         0.0,
    "total_count":             0,
    "good_count":              0,
    "print_status":            False,
    "label_text":              "",
    "message":                 "",
    "availability":            0.0,
    "performance":             0.0,
    "quality":                 0.0,
    "oee":                     0.0,
    "last_completed_order_id": None,
}

_last_label_request  = False
_accumulated_runtime = 0.0
_piece_start_time    = None   # MES wall-clock time when current piece started


def background_loop():
    global _last_label_request
    global _accumulated_runtime, _piece_start_time

    while True:
        try:
            snapshot = opc.read_all()
            live_data["connected"] = True

            station_state_raw = int(snapshot["station_state"])
            total_count       = int(snapshot["total_count"])
            good_count        = int(snapshot["good_count"])
            label_request     = bool(snapshot["label_request"])
            label_text_plc    = str(snapshot["label_text"])
            print_status      = bool(snapshot["print_status"])

            live_data["station_state"] = STATE_MAP.get(station_state_raw, "UNKNOWN")
            live_data["total_count"]   = total_count
            live_data["good_count"]    = good_count
            live_data["print_status"]  = print_status
            live_data["label_text"]    = label_text_plc

            active_order = get_active_order()

            # ── MES-side timing ───────────────────────────────────────────────
            # Start timing when station goes ACTIVE and we have an order
            if active_order:
                if live_data["station_state"] == "ACTIVE" and _piece_start_time is None:
                    _piece_start_time = time.time()

                # Rising edge of label_request = piece just finished, time it
                if label_request and not _last_label_request:
                    if _piece_start_time is not None:
                        cycle_time = round(time.time() - _piece_start_time, 2)
                        _accumulated_runtime        += cycle_time
                        live_data["last_cycle_time"] = cycle_time
                        live_data["run_time"]        = round(_accumulated_runtime, 2)
                        _piece_start_time            = None  # reset for next piece

            # ── OEE: compute on every poll ────────────────────────────────────
            if active_order and _accumulated_runtime > 0 and total_count > 0:
                ppt = float(active_order["planned_production_time"])

                oee_data = compute_oee(
                    run_time=_accumulated_runtime,
                    planned_production_time=ppt,
                    ideal_cycle_time=IDEAL_CYCLE_TIME,
                    total_count=total_count,
                    good_count=good_count,
                )

                live_data["availability"] = round(oee_data["availability"] * 100, 2)
                live_data["performance"]  = round(oee_data["performance"]  * 100, 2)
                live_data["quality"]      = round(oee_data["quality"]      * 100, 2)
                live_data["oee"]          = round(oee_data["oee"]          * 100, 2)

                # Save to DB on each piece completion (label_request rising edge)
                if label_request and not _last_label_request:
                    insert_oee_record(
                        order_id=active_order["order_id"],
                        run_time=_accumulated_runtime,
                        last_cycle_time=live_data["last_cycle_time"],
                        total_count=total_count,
                        good_count=good_count,
                        station_state=live_data["station_state"],
                        availability=oee_data["availability"],
                        performance=oee_data["performance"],
                        quality=oee_data["quality"],
                        oee_value=oee_data["oee"],
                    )

            # ── Auto print: rising edge on label_request ──────────────────────
            if label_request and not _last_label_request:
                active_order = get_active_order()
                if active_order and active_order["mode"] == "auto":
                    text_to_print = active_order["label_text"]
                    success = print_label(text_to_print)
                    opc.write_string("label_text", text_to_print)
                    opc.write_bool("print_status", success)
                    live_data["label_text"]   = text_to_print
                    live_data["print_status"] = success
                    if success:
                        order_done = increment_printed_count(active_order["order_id"])
                        log_print(active_order["order_id"], text_to_print, True)
                        if order_done:
                            live_data["last_completed_order_id"] = active_order["order_id"]
                            live_data["message"] = f"Order #{active_order['order_id']} completed!"
                            # Do NOT reset OEE here — keep numbers visible after completion
                    else:
                        log_print(active_order["order_id"], text_to_print, False)
                        live_data["message"] = "Auto-print failed."

            _last_label_request = label_request

        except Exception as exc:
            live_data["connected"] = False
            live_data["message"] = f"OPC UA error: {exc}"

        time.sleep(POLL_INTERVAL)


# ── Auth ──────────────────────────────────────────────────────────────────────

PINS = {
    "viewer":   "0",
    "operator": "0",
}

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        role = request.form.get("role", "")
        pin  = request.form.get("pin", "")
        if role in PINS and pin == PINS[role]:
            session["role"] = role
            return redirect("/")
        else:
            error = "Invalid PIN."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    if "role" not in session:
        return redirect("/login")

    active_order = get_active_order()
    active_order_dict = dict(active_order) if active_order else None

    completed_order = None
    if not active_order and live_data["last_completed_order_id"]:
        row = get_order(live_data["last_completed_order_id"])
        if row:
            completed_order = dict(row)

    return render_template("dashboard.html",
                           data=live_data,
                           role=session["role"],
                           active_order=active_order_dict,
                           completed_order=completed_order)


@app.route("/api/live")
def api_live():
    if "role" not in session:
        return jsonify({"error": "unauthorized"}), 401
    active_order = get_active_order()

    completed_order = None
    if not active_order and live_data["last_completed_order_id"]:
        row = get_order(live_data["last_completed_order_id"])
        if row:
            completed_order = dict(row)

    return jsonify({
        **live_data,
        "active_order":    dict(active_order) if active_order else None,
        "completed_order": completed_order,
    })


# ── Orders ────────────────────────────────────────────────────────────────────

@app.route("/orders")
def orders():
    if "role" not in session:
        return redirect("/login")
    all_orders = [dict(o) for o in get_all_orders()]
    return render_template("orders.html", orders=all_orders, role=session["role"])


@app.route("/orders/<int:order_id>")
def order_detail(order_id):
    if "role" not in session:
        return redirect("/login")
    order = get_order(order_id)
    if not order:
        return redirect("/orders")
    history = [dict(r) for r in get_oee_history(order_id)]
    return render_template("order_detail.html",
                           order=dict(order),
                           history=history,
                           role=session["role"])


@app.route("/orders/create", methods=["POST"])
def orders_create():
    global _accumulated_runtime, _piece_start_time
    if session.get("role") != "operator":
        return redirect("/")

    product_name     = request.form.get("product_name", "").strip()
    planned_quantity = int(request.form.get("planned_quantity", 1))
    label_text       = request.form.get("label_text", "").strip()
    mode             = request.form.get("mode", "manual")

    if not product_name:
        live_data["message"] = "Product name is required."
        return redirect("/")
    if mode == "auto" and not label_text:
        live_data["message"] = "Label text is required for auto mode."
        return redirect("/")

    planned_production_time = planned_quantity * IDEAL_CYCLE_TIME

    active = get_active_order()
    if active:
        cancel_order(active["order_id"])

    order_id = create_order(
        product_name=product_name,
        planned_quantity=planned_quantity,
        planned_production_time=planned_production_time,
        ideal_cycle_time=IDEAL_CYCLE_TIME,
        label_text=label_text,
        mode=mode,
    )

    _accumulated_runtime                 = 0.0
    _piece_start_time                    = None
    live_data["run_time"]                = 0.0
    live_data["last_cycle_time"]         = 0.0
    live_data["availability"]            = 0.0
    live_data["performance"]             = 0.0
    live_data["quality"]                 = 0.0
    live_data["oee"]                     = 0.0
    live_data["last_completed_order_id"] = None
    live_data["message"]                 = f"Order #{order_id} created ({mode} mode)."
    return redirect("/")


@app.route("/orders/cancel", methods=["POST"])
def orders_cancel():
    global _accumulated_runtime, _piece_start_time
    if session.get("role") != "operator":
        return redirect("/")
    active = get_active_order()
    if active:
        cancel_order(active["order_id"])
        _accumulated_runtime                 = 0.0
        _piece_start_time                    = None
        live_data["run_time"]                = 0.0
        live_data["last_cycle_time"]         = 0.0
        live_data["last_completed_order_id"] = None
        live_data["message"]                 = f"Order #{active['order_id']} cancelled."
    return redirect("/")


# ── Manual Print ──────────────────────────────────────────────────────────────

@app.route("/print_label", methods=["POST"])
def handle_print():
    if session.get("role") != "operator":
        return redirect("/")
    try:
        label_text = request.form.get("label_text", "").strip()
        if not label_text:
            live_data["message"] = "Label text cannot be empty."
            return redirect("/")

        success = print_label(label_text)
        opc.write_string("label_text", label_text)
        opc.write_bool("print_status", success)

        live_data["label_text"]   = label_text
        live_data["print_status"] = success
        live_data["message"]      = "Label sent." if success else "Print failed."

        active = get_active_order()
        if active:
            order_done = increment_printed_count(active["order_id"])
            log_print(active["order_id"], label_text, success)
            if order_done:
                live_data["last_completed_order_id"] = active["order_id"]
                live_data["message"] = f"Order #{active['order_id']} completed!"
                # Do NOT reset OEE here — keep numbers visible after completion

    except Exception as exc:
        live_data["message"] = f"Print error: {exc}"

    return redirect("/")


if __name__ == "__main__":
    init_db()
    opc.connect()
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()
    app.run(debug=True)
