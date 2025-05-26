# smps-design-tools

Design tools for switched-mode power supplies.  The repository contains a set of
Jupyter notebooks for common converter topologies and a small utility module
used by those notebooks.

I maintain these for my own use and make no guarantees as to their quality or
suitability for any purpose.  I may change the signatures of the libraries 
and their functional specifications to suit my needs with no notice.

## Repository Layout

- **boost-converter/** – example notebooks for boost converters (e.g. `LM3478MM_design.ipynb`).
- **flyback-converter/** – notebooks for flyback converters (e.g. `LT8300_design.ipynb`).
- **utils/** – general utilities such as `rounding.py` and supporting notebooks.

## Installing Requirements

The notebooks rely on a few Python packages.  Create a virtual environment and
install the dependencies with `pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install jupyter sympy matplotlib
```

## Running the Notebooks

Start Jupyter and open the notebook of interest:

```bash
jupyter notebook
```

The notebooks can be found under `boost-converter/`, `flyback-converter/` and
`utils/`.

## Using the Utility Module

The `utils` package exposes helper functions for electronic design.  Import it
in your own scripts or notebooks as follows:

```python
from utils.rounding import resistor_divider, closest_E_series_value
```

## Testing

Install the dependencies listed in `requirements.txt` and run `pytest`:

```bash
pip install -r requirements.txt
pytest
```

## License

This project is released to the public domain under [The Unlicense](LICENSE).
