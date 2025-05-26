import math
from math import floor, log10


def sig_figs(x: float, precision: int):
    """
    Rounds a number to number of significant figures
    Parameters:
    - x - the number to be rounded
    - precision (integer) - the number of significant figures
    Returns:
    - float
    """

    x = float(x)
    precision = int(precision)

    if x == 0:
        return 0
    else:
        return round(x, -int(floor(log10(abs(x)))) + (precision - 1))
    
def sign(x, value=1):
    """Mathematical signum function.

    :param x: Object of investigation
    :param value: The size of the signum (defaults to 1)
    :returns: Plus or minus value
    """
    return -value if x < 0 else value

def prefix(x, dimension=1):
    """Give the number an appropriate SI prefix.

    :param x: Too big or too small number.
    :returns: String containing a number between 1 and 1000 and SI prefix.
    """
    if x == 0:
        return "0"

    l = math.floor(math.log10(abs(x)))
    if abs(l) > 24:
        l = sign(l, value=24)

    div, mod = divmod(l, 3*dimension)
    if div != 0:
        return "%g%s" % (x * 10**(-l + mod), " kMGTPEZYyzafpnµm"[div])
    else:
        return "%g" % (x * 10**(-l + mod))

e3 = [1, 2.2, 4.7]
e6 = [1, 1.5, 2.2, 3.3, 4.7, 6.8]
e12 = [1, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
e24 = [1, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2, 2.2, 2.4, 2.7, 3, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]
e48 = [1, 1.05, 1.1, 1.15, 1.21, 1.27, 1.33, 1.4, 1.47, 1.54, 1.62, 1.69, 1.78, 1.87, 1.96, 2.05, 2.15, 2.26, 2.37, 2.49, 2.61, 2.74, 2.87, 3.01, 3.16, 3.32, 3.48, 3.65, 3.83, 4.02, 4.22, 4.42, 4.64, 4.87, 5.11, 5.36, 5.62, 5.90, 6.19, 6.49, 6.81, 7.15, 7.50, 7.87, 8.25, 8.66, 9.09, 9.53]
e96 = [1, 1.02, 1.05, 1.07, 1.1, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.3, 1.33, 1.37, 1.4, 1.43, 1.47, 1.5, 1.54, 1.58, 1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2, 2.05, 2.1, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55, 2.61, 2.67, 2.74, 2.8, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.4, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49, 5.62, 5.76, 5.9, 6.04, 6.19, 6.34, 6.49, 6.65, 6.81, 6.98, 7.15, 7.32, 7.5, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76]

def closest_E_series_value(input_value, e_series=96, method='eq'):
    if e_series == 1:
        values = set([1])
    elif e_series == 3:
        values = set(e3)
    elif e_series == 6:
        values = set(e6)
    elif e_series == 12:
        values = set(e12)
    elif e_series == 24:
        values = set(e24)
    elif e_series == 48:
        values = set(e48+e24)
    elif e_series == 96:
        values = set(e96+e24)
    else:
        values = set(e24)

    p = math.floor(math.log10(input_value))
    x = input_value / (10**p)

    best_y_pos = 0
    best_diff_pos = 100
    best_y_neg = 0
    best_diff_neg = 100
    for y in values:
        if y>x and abs(y-x) < best_diff_pos:
            best_y_pos = y
            best_diff_pos = abs(y-x)
        if y<=x and abs(y-x) < best_diff_neg:
            best_y_neg = y
            best_diff_neg = abs(y-x)


    if method == 'lt':
        best_y = best_y_neg
    elif method == 'gt':
        best_y = best_y_pos
    else:
        if abs(best_diff_pos) < abs(best_diff_neg):
            best_y = best_y_pos
        else:
            best_y = best_y_neg

    return best_y * (10**p)

def resistor_divider(V_in, V_out, I_min, I_max, e_series=12, num_results=10, implied_V_in=False):
    if e_series == 1:
        R_values = set([1])
    elif e_series == 3:
        R_values = set(e3)
    elif e_series == 6:
        R_values = set(e6)
    elif e_series == 12:
        R_values = set(e12)
    elif e_series == 24:
        R_values = set(e24)
    elif e_series == 48:
        R_values = set(e48+e24)
    elif e_series == 96:
        R_values = set(e96+e24)
    else:
        R_values = set(e24)
    pairs = {}
    for Rt in R_values:
        for Rb in R_values:
            pairs[(Rt,Rb)] = 0

    output = []
    for (R1,R2) in pairs.keys():
        pair_output = []
        for exp_t in range(0, 8):
            for exp_b in range(0, 8):
                Rt = R1 * 10**exp_t
                Rb = R2 * 10**exp_b
                V = V_in * Rb/(Rt+Rb)
                I = V_in/(Rt+Rb)
                if implied_V_in:
                    V_to_report = V_out * (Rt+Rb)/Rb
                else:
                    V_to_report = V
                if I_min <= I and I <= I_max:
                    pair_output.append((Rt, Rb, V_to_report, abs(V_out-V), (V_out-V)/V_out, I))
        if len(pair_output)>0:
            pair_result = sorted(pair_output, key=lambda t: t[3], reverse=False)[0]
            output.append(pair_result)

    result = sorted(output, key=lambda t: t[3], reverse=False)[:num_results]
    return result
