import socket

PRINTER_IP   = "172.21.9.70"
PRINTER_PORT = 9100


def print_label(user_text: str) -> bool:
    try:
        zpl = (
            "^XA\n"
            "^FO50,50\n"
            "^A0N,50,50\n"
            f"^FD{user_text}^FS\n"
            "^XZ\n"
        )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((PRINTER_IP, PRINTER_PORT))
            s.sendall(zpl.encode("utf-8"))
        return True
    except Exception as exc:
        print(f"Printer error: {exc}")
        return False
