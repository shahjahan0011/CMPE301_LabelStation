from flask import Flask, render_template, request, redirect, session, jsonify
import threading
import time

from config import POLL_INTERVAL, STATE_MAP
from opcua_client import OPCUAClient
from repository import (
    init_db,
    create_order,
    get_active_order,
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

live_data = {
    "connected":        False,
    "station_state":    "UNKNOWN",
    "run_time":         0.0,
    "last_cycle_time":  0.0,
    "total_count":      0,
    "good_count":       0,
    "print_status":     False,
    "label_text":       "",
    "message":          "",
    # OEE
    "availability":     0.0,
    "performance":      0.0,
    "quality":          0.0,
    "oee":              0.0,
}

_last_label_request = False
_last_cycle_done    = False


def background_loop():
    global _last_label_request, _last_cycle_done

    while True:
        try:
            snapshot = opc.read_all()
            live_data["connected"] = True

            station_state_raw = int(snapshot["station_state"])
            run_time          = float(snapshot["run_time"])
            last_cycle_time   = float(snapshot["last_cycle_time"])
            total_count       = int(snapshot["total_count"])
            good_count        = int(snapshot["good_count"])
            label_request     = bool(snapshot["label_request"])
            label_text_plc    = str(snapshot["label_text"])
            print_status      = bool(snapshot["print_status"])
            cycle_done        = bool(snapshot["cycle_done"])

            live_data["station_state"]   = STATE_MAP.get(station_state_raw, "UNKNOWN")
            live_data["run_time"]        = round(run_time, 2)
            live_data["last_cycle_time"] = round(last_cycle_time, 2)
            live_data["total_count"]     = total_count
            live_data["good_count"]      = good_count
            live_data["print_status"]    = print_status
            live_data["label_text"]      = label_text_plc

            active_order = get_active_order()

            # ── OEE: recalculate on every cycle_done rising edge ──────────────
            if cycle_done and not _last_cycle_done and active_order:
                ppt = float(active_order["planned_production_time"])
                ict = float(active_order["ideal_cycle_time"])

                oee_data = compute_oee(
                    run_time=run_time,
                    planned_production_time=ppt,
                    ideal_cycle_time=ict,
                    total_count=total_count,
                    good_count=good_count,
                )

                live_data["availability"] = round(oee_data["availability"] * 100, 2)
                live_data["performance"]  = round(oee_data["performance"]  * 100, 2)
                live_data["quality"]      = round(oee_data["quality"]      * 100, 2)
                live_data["oee"]          = round(oee_data["oee"]          * 100, 2)

                insert_oee_record(
                    order_id=active_order["order_id"],
                    run_time=run_time,
                    last_cycle_time=last_cycle_time,
                    total_count=total_count,
                    good_count=good_count,
                    station_state=live_data["station_state"],
                    availability=oee_data["availability"],
                    performance=oee_data["performance"],
                    quality=oee_data["quality"],
                    oee_value=oee_data["oee"],
                )

            _last_cycle_done = cycle_done

            # ── Auto print: rising edge on label_request ──────────────────────
            if label_request and not _last_label_request:
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
                            live_data["message"] = f"Order #{active_order['order_id']} completed."
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
    return render_template("dashboard.html",
                           data=live_data,
                           role=session["role"],
                           active_order=active_order_dict)


@app.route("/api/live")
def api_live():
    if "role" not in session:
        return jsonify({"error": "unauthorized"}), 401
    active_order = get_active_order()
    return jsonify({
        **live_data,
        "active_order": dict(active_order) if active_order else None
    })


# ── Orders ────────────────────────────────────────────────────────────────────

@app.route("/orders")
def orders():
    if "role" not in session:
        return redirect("/login")
    all_orders = [dict(o) for o in get_all_orders()]
    return render_template("orders.html",
                           orders=all_orders,
                           role=session["role"])


@app.route("/orders/<int:order_id>")
def order_detail(order_id):
    if "role" not in session:
        return redirect("/login")
    from repository import get_order
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
    if session.get("role") != "operator":
        return redirect("/")

    product_name            = request.form.get("product_name", "").strip()
    planned_quantity        = int(request.form.get("planned_quantity", 1))
    planned_production_time = float(request.form.get("planned_production_time", 3600.0))
    ideal_cycle_time        = float(request.form.get("ideal_cycle_time", 60.0))
    label_text              = request.form.get("label_text", "").strip()
    mode                    = request.form.get("mode", "manual")

    if not product_name:
        live_data["message"] = "Product name is required."
        return redirect("/")
    if mode == "auto" and not label_text:
        live_data["message"] = "Label text is required for auto mode."
        return redirect("/")

    active = get_active_order()
    if active:
        cancel_order(active["order_id"])

    order_id = create_order(product_name, planned_quantity,
                            planned_production_time, ideal_cycle_time,
                            label_text, mode)
    live_data["message"] = f"Order #{order_id} created ({mode} mode)."
    # Reset OEE on new order
    live_data["availability"] = 0.0
    live_data["performance"]  = 0.0
    live_data["quality"]      = 0.0
    live_data["oee"]          = 0.0
    return redirect("/")


@app.route("/orders/cancel", methods=["POST"])
def orders_cancel():
    if session.get("role") != "operator":
        return redirect("/")
    active = get_active_order()
    if active:
        cancel_order(active["order_id"])
        live_data["message"] = f"Order #{active['order_id']} cancelled."
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
            increment_printed_count(active["order_id"])
            log_print(active["order_id"], label_text, success)

    except Exception as exc:
        live_data["message"] = f"Print error: {exc}"

    return redirect("/")


if __name__ == "__main__":
    init_db()
    opc.connect()
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()
    app.run(debug=True)
