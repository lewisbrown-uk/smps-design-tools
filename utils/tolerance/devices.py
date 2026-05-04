"""Curated active-device parameter spreads.

Each entry maps a part-number key to ``{param_name: Sampler}``. The
parts here are the four used in ``ngspice_examples/`` — adding more
is mechanical: pull min/typical/max from the datasheet and pick the
appropriate ``Sampler``.

**Convention.** σ for ``AbsoluteGaussian`` is derived from the
datasheet's *max* spec with a 3σ guard band (``sigmas`` matches the
``tolerance_sigma`` default for passives). Datasheet "typical" values
have no industry-standard statistical meaning — different vendors use
"typical" to mean median, mean, modal value, or 1σ inconsistently — so
they're documented in comments but not used to set σ. ``LogUniform``
is preferred when the datasheet quotes min/max bounds spanning a
decade or more (Avol, β); the manufacturer guarantees the bound but
not the shape between, and uniform-on-log avoids assuming clustering
the datasheet doesn't actually claim.

For studies that need a different convention (typical-as-σ, heavy-
tailed distributions fitting both typical and max), the user can
build per-parameter samplers manually and pass them via
``analyze(distribution={...})``.
"""
from .samplers import (
    AbsoluteGaussian, RelativeGaussian, LogUniform, Uniform,
)
from .tempco import Additive, Exponential


DEVICES = {
    "NE5532": {
        # Bipolar audio op-amp. Datasheet (TI):
        #   Vos:  typ 0.5 mV,  max ±3 mV at 25°C
        #   Ib:   typ 200 nA,  max 800 nA
        #   Avol: min 50k,     typ 100k        (no max stated)
        #   GBW:  typ 10 MHz   (process spread ~±20%)
        "Vos":  AbsoluteGaussian(mean=0.0, sigma=1e-3),     # 3σ = 3 mV
        "Ib":   AbsoluteGaussian(mean=200e-9, sigma=200e-9),  # 3σ = ±600 nA
        "Avol": LogUniform(lo=50e3, hi=1e6),                # min .. soft cap
        "GBW":  RelativeGaussian(nominal_value=10e6, tol=0.20),
    },
    "TLV9104": {
        # CMOS RRIO quad op-amp (TI). Datasheet:
        #   Vos:  typ 0.4 mV,  max ±2 mV
        #   Ib:   typ ±5 pA at 25°C (CMOS, sub-pA in practice)
        #   Avol: 130 dB typical (≈ 3.16 M); soft range 1M..10M
        #   GBW:  typ 1 MHz
        "Vos":  AbsoluteGaussian(mean=0.0, sigma=0.7e-3),   # 3σ ≈ 2 mV
        "Ib":   AbsoluteGaussian(mean=0.0, sigma=5e-12),
        "Avol": LogUniform(lo=1e6, hi=10e6),
        "GBW":  RelativeGaussian(nominal_value=1e6, tol=0.20),
    },
    "2N3904": {
        # Small-signal NPN BJT. Datasheet (Onsemi):
        #   BF (β):  min 100, typ 250, max 400 at Ic = 10 mA
        # Other params (IS, VAF, junction caps) have huge spreads but
        # don't usually bind regulator-class behaviour — leave the
        # SPICE model defaults in place by not parameterising them.
        "BF":   LogUniform(lo=100, hi=400),
    },
    "J201": {
        # N-channel JFET (Vishay/Linear Systems). Datasheet:
        #   Vto (Vgs(off)):  −0.4 V (max) to −2.3 V (min)
        # That's nearly an order of magnitude — Uniform on bounds is
        # the honest model when no distribution shape is given.
        "Vto":  Uniform(lo=-2.3, hi=-0.4),
    },
}


DEVICE_TEMPCOS = {
    # Op-amp tempcos. Datasheet typ values; users can override via
    # ``temperature_coefficients={"U1_Vos": ...}``.
    "NE5532": {
        # Vos drift typ ±5 µV/°C — Additive: nominal Vos is zero so the
        # multiplicative form is wrong; the per-part drift coefficient is
        # itself a random variable.
        "Vos":  Additive(sigma=5e-6),
        # Bipolar Ib doubles roughly every 10°C — Exponential model.
        "Ib":   Exponential(factor=2.0, per_K=10.0),
        # Avol drops with T (typ -2000 ppm/°C); GBW rolls off slightly.
        # Multiplicative scalars — these are well-behaved non-zero
        # nominal values where ratiometric drift is the right shape.
        "Avol": -2000e-6,
        "GBW":  -500e-6,
    },
    "TLV9104": {
        # CMOS — lower Vos drift, much smaller Ib but still doubles
        # with T. Typ Vos drift ~1 µV/°C, max ~5 µV/°C → σ ≈ 2 µV/°C.
        "Vos":  Additive(sigma=2e-6),
        "Ib":   Exponential(factor=2.0, per_K=10.0),
        "Avol": -1500e-6,
        "GBW":  -500e-6,
    },
    # 2N3904 BJT and J201 JFET: their temperature dependence (V_BE,
    # β, Vto, Idss) is handled natively by ngspice when ``.temp`` is
    # injected. Don't double-count by adding library tempcos here —
    # that would compound on top of what the device model already
    # does in the simulator. For the closed-form backend, BJT/JFET
    # tempcos would need adding manually if the metric uses them.
}


def expand_active_tempcos(active_devices, library=None):
    """Expand ``{instance_name: part_number}`` into per-parameter
    tempcos keyed by ``{instance}_{param}``, drawing from
    ``DEVICE_TEMPCOS``.

    Args:
        active_devices: same ``{instance: part}`` mapping passed to
            ``expand_active_devices``.
        library: Optional override for the tempco library. Defaults to
            the curated ``DEVICE_TEMPCOS`` dict.

    Returns:
        ``{f"{instance}_{param}": tempco}`` for every instance/param
        whose part has an entry in the library. Parts with no library
        entry (e.g. ``2N3904``) contribute nothing — the user can still
        supply tempcos for them via ``temperature_coefficients`` if
        the metric needs them outside ngspice.
    """
    library = library if library is not None else DEVICE_TEMPCOS
    tcs = {}
    for instance, part in active_devices.items():
        if part not in library:
            continue
        for param, tc in library[part].items():
            tcs[f"{instance}_{param}"] = tc
    return tcs


def expand_active_devices(active_devices, library=None):
    """Expand ``{instance_name: part_number}`` into per-parameter
    samplers keyed by ``{instance}_{param}``.

    Args:
        active_devices: ``{instance: part}`` mapping. ``instance``
            becomes the prefix in the generated sampler keys; ``part``
            must match a key in ``library``.
        library: Optional override for the device library. Defaults to
            the curated ``DEVICES`` dict.

    Returns:
        ``{f"{instance}_{param}": Sampler}`` ready to merge into the
        per-component sampler map. ``f"{instance}_{param}"`` is the
        name the metrics callable receives — the user's netlist
        template references ``{U1_Vos}``, ``{Q1_BF}``, etc.

    Raises:
        ValueError: ``part`` not in the library, or two instances
            generate colliding parameter names.
    """
    library = library if library is not None else DEVICES
    samplers = {}
    for instance, part in active_devices.items():
        if part not in library:
            raise ValueError(
                f"active_devices[{instance!r}] = {part!r}: not in "
                f"device library; known parts: {sorted(library)}"
            )
        for param, sampler in library[part].items():
            key = f"{instance}_{param}"
            if key in samplers:
                raise ValueError(
                    f"active_devices generated duplicate sampler "
                    f"key {key!r} — two instances expand to the same "
                    f"parameter name"
                )
            samplers[key] = sampler
    return samplers
