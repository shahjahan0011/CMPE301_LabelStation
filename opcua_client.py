from opcua import Client, ua
from config import OPCUA_URL, NODE_IDS


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

    def read_all(self):
        return {
            name: node.get_value()
            for name, node in self.nodes.items()
        }

    def write_bool(self, node_name: str, value: bool):
        node = self.nodes[node_name]
        node.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.Boolean)))

    def write_string(self, node_name: str, value: str):
        node = self.nodes[node_name]
        node.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.String)))

    def disconnect(self):
        self.client.disconnect()
