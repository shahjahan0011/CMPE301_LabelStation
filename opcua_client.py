from opcua import Client
from config import OPCUA_URL


NODE_IDS = {
    "current_order_id": 'ns=3;s="OPCUA_data"."current_order_id"',
    "station_state": 'ns=3;s="OPCUA_data"."station_state"',
    "run_time": 'ns=3;s="OPCUA_data"."run_time"',
    "total_count": 'ns=3;s="OPCUA_data"."total_count"',
    "good_count": 'ns=3;s="OPCUA_data"."good_count"',
    "completion_status": 'ns=3;s="OPCUA_data"."completion_status"',
}


class OPCUAClient:
    def __init__(self):
        self.client = Client(OPCUA_URL)
        self.nodes = {}

    def connect(self):
        self.client.connect()
        self.nodes = {
            name: self.client.get_node(node_id)
            for name, node_id in NODE_IDS.items()
        }

    def read(self):
        return {name: node.get_value() for name, node in self.nodes.items()}

    def disconnect(self):
        self.client.disconnect()