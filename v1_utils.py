import math


def userAccurate(number: int | float) -> str:
    """
    Displays a number in a human-readable and accurate way

    Tries to use scale symbols to represent thousands, millions, and etc.
    Uses scale symbols up to 'T' (trillion).

    Tries not to round for accurate representation.
    However if a fraction is too long, it will still be rounded.
    A fraction's leading zeros are ignored for accuracy.

    Reference:
    https://en.wikipedia.org/wiki/Long_and_short_scales
    """
    SCALE_NAMES = ['', 'k', 'M', 'G', 'T']
    SCALE_BASES = [1, 1e3, 1e6, 1e9, 1e12]
    FRACTION_PRECISION = 3
    LENGTH_THRESHOLD = 4

    scale_name = ''
    scaled_number = number
    for scale, base in zip(reversed(SCALE_NAMES), reversed(SCALE_BASES)):
        res_div = number / base
        if res_div < 1:
            continue

        scale_name = scale
        scaled_number = res_div
        break

    if type(scaled_number) is float:
        if scaled_number.is_integer():
            scaled_number = int(scaled_number)

    formatted = f'{scaled_number:,}{scale_name}'
    # if the scaled number is too long,
    # a) if it is an integer:
    #    falls back to simply formatting with thousands separators
    # b) if it is a float: round it
    if len(str(scaled_number)) > LENGTH_THRESHOLD and scale_name != 'T':
        if isinstance(number, int) or (isinstance(number, float) and number.is_integer()):
            return f'{number:,}'
        elif abs(number) >= 1:
            return f'{round(number, FRACTION_PRECISION):,}'
        else:
            exponent = int(math.log(abs(number), 10))
            rounded = round(number, -exponent + FRACTION_PRECISION)
            return str(rounded)

    return formatted