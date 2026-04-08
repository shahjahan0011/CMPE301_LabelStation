OPCUA_URL = "opc.tcp://172.21.9.1:4840"

DB_PATH = "mes.db"

POLL_INTERVAL = 1.0

NODE_IDS = {
    "current_order_id": 'ns=3;s="DB_MES_Comms"."current_order_id"',
    "station_state": 'ns=3;s="DB_MES_Comms"."station_state"',
    "run_time": 'ns=3;s="DB_MES_Comms"."run_time"',
    "total_count": 'ns=3;s="DB_MES_Comms"."total_count"',
    "good_count": 'ns=3;s="DB_MES_Comms"."good_count"',
    "completion_status": 'ns=3;s="DB_MES_Comms"."completion_status"',
    "label_request": 'ns=3;s="DB_MES_Comms"."label_request"',
    "label_text": 'ns=3;s="DB_MES_Comms"."label_text"',
    "print_status": 'ns=3;s="DB_MES_Comms"."print_status"',
}

STATE_MAP = {
    0: "IDLE",
    1: "WAITING",
    2: "BUSY",
    3: "ERROR",
}