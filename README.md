# LabelProMax MES System

## Overview

LabelProMax is a Manufacturing Execution System (MES) built for the CMPE 301 lab.  
It connects a Siemens PLC with a Python-based dashboard using OPC UA to monitor and control a labeling station.

The system supports:
- RFID-based order detection  
- Real-time production monitoring  
- Runtime and count tracking  
- Label printing integration  

---

## Repository Structure

- `TIAPortalFiles/` → Pre-configured PLC + HMI project (TIA Portal)
- `app.py` → Main MES dashboard (Flask)
- `opcua_client.py` → PLC communication
- `requirements.txt` → Python dependencies
- Other files → Supporting services (printer, database, etc.)

---

## Demo Video

https://youtu.be/1DudySTJBBM?si=CWFdSNBikq7E300y

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/shahjahan0011/CMPE301_LabelStation
```

---

### 2. Run PLC (TIA Portal)

1. Open TIA Portal  
2. Retrieve project from `TIAPortalFiles/` (.zap file)  
3. Compile PLC + HMI  
4. Download to the label station  
5. Set PLC to **RUN** and go **Online**

---

### 3. Run MES (Python)

In the project directory:

```bash
pip install -r requirements.txt
python app.py
```

---

### 4. Open Dashboard

http://127.0.0.1:5000

---

## How It Works

1. RFID detects a pallet → Order ID is read  
2. MES dashboard updates in real time  
3. User enters label text and prints  
4. PLC executes labeling sequence  
5. Runtime and counts are tracked automatically  

---

## Notes

- Ensure PLC and PC are on the same network  
- PLC must be in **RUN mode**  
- Printer must be powered ON  
- If MES fails to start, delete the database:

```bash
del mes.db
```

---

## Authors

- Jahan Shah  
- Karol Skrzekowski  

University of British Columbia – Okanagan  
CMPE 301
