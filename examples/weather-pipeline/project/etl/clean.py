from config import MIN_TEMP_C, MAX_TEMP_C


def to_celsius(df):
    """Some stations report Fahrenheit; convert them."""
    df = df.copy()
    f = df["unit"] == "F"
    df.loc[f, "temp"] = (df.loc[f, "temp"] - 32) * 5 / 9
    df["unit"] = "C"
    return df


def drop_invalid(df):
    """Remove missing values and physically impossible temperatures."""
    df = df.dropna(subset=["temp", "station_id"])
    return df[(df["temp"] >= MIN_TEMP_C) & (df["temp"] <= MAX_TEMP_C)]


def dedupe(df):
    """Sensors sometimes resend a reading; keep the first."""
    return df.drop_duplicates(subset=["station_id", "timestamp"], keep="first")


def clean(df):
    for step in (to_celsius, drop_invalid, dedupe):
        df = step(df)
    return df
