# Autoscaler Project

This repository contains an **Autoscaler** implementation along with unit tests written using **pytest**.

## 📦 Prerequisites

Make sure you have:

- Python 3.8+ installed
- `pip` package manager
- (Optional) A virtual environment for isolating dependencies

---

## ⚙️ Installation


1. **Create and activate a virtual environment** (recommended):

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows
```

2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

---

## 📄 Configuration

The autoscaler requires a `config.yaml` file in the project root.  
Example `config.yaml`:

```yaml
base_url: "http://localhost:8123"
scale_up_threshold: 80
scale_down_threshold: 20
min_instances: 1
max_instances: 10
```

You can also pass a custom config file path:

```bash
python3 app/auto_scaler.py --config path/to/config.yaml
```

---

## ▶️ Running the Autoscaler

```bash
python3 app/auto_scaler.py --config config.yaml
```

If `--config` is not provided, it will exit().

---

## 🧪 Running Tests

Tests are written using **pytest** and located in the `tests/` folder.

To run **all tests**:

```bash
pytest -v
```

To run **tests with coverage**:

```bash
pytest --cov=app --cov-report=term-missing
```

---

## 📂 Project Structure

```
autoscaler/
│
├── app/
│   ├── auto_scaler.py      # Main autoscaler script
│   ├── util/
│   │   └── logger.py       # Logger setup utility
│   └── ...
│
├── tests/
│   ├── test_auto_scaler.py # Unit tests
│   └── ...
│
├── config.yaml             # Sample config file
├── requirements.txt        # Python dependencies
└── README.md               # Project documentation
```

---

## 🛠 Notes

- Do **not** edit the main code when running tests. The test suite uses **fixtures** and **monkeypatching** to mock dependencies.
- For production usage, update logging configuration in `app/util/logger.py`.

---

## 📜 License

This project is licensed under the Manvinder Singh.