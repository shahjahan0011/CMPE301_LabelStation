from flask import Flask, render_template
import time
import threading

from config import USE_MOCK, POLL_INTERVAL
from repository import init_db, get_active_order, get_all_orders
from services import process

from opcua_client import OPCUAClient
from mock_plc import get_mock_data

app = Flask(__name__)

snapshot_data = {}
oee_data = {}


def background_loop():
    global snapshot_data, oee_data

    opc = None
    if not USE_MOCK:
        opc = OPCUAClient()
        opc.connect()

    while True:
        if USE_MOCK:
            snapshot = get_mock_data()
        else:
            snapshot = opc.read() if opc else {}

        STATE_MAP = {
                        0: "IDLE",
                        1: "WAITING",
                        2: "BUSY",
                        3: "ERROR"
                    }

        snapshot["state_label"] = STATE_MAP.get(snapshot["station_state"], "UNKNOWN")
                                        
        active_order = get_active_order()
        oee = process(snapshot, active_order)

        snapshot_data = snapshot
        oee_data = oee if oee else {
         "availability": 0,
         "performance": 0,
         "quality": 0,
         "oee": 0
}

        time.sleep(POLL_INTERVAL)


@app.route("/")
def dashboard():
    orders = get_all_orders()
    return render_template(
        "dashboard.html",
        snapshot=snapshot_data,
        oee=oee_data,
        orders=orders
    )


if __name__ == "__main__":
    init_db()

    thread = threading.Thread(target=background_loop)
    thread.daemon = True
    thread.start()

    app.run(debug=True)