import folium
import numpy as np
import pandas as pd
import pytz
import streamlit as st
from folium.plugins import HeatMap
from streamlit_folium import folium_static


# Define the Haversine formula for calculating distance between two points
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # Radius of the Earth in kilometers
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
    )
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    distance = R * c * 1000  # Convert distance to meters
    return distance


# Parse GPS data from uploaded files
def parse_gps_data(uploaded_files):
    data_list = []

    for uploaded_file in uploaded_files:
        # Read file content as string
        content = uploaded_file.getvalue().decode("utf-8")

        for line in content.split("\n"):
            if line.startswith("$GPRMC"):
                fields = line.strip().split(",")
                if len(fields) < 10:
                    continue

                time = fields[1]
                latitude_str = fields[3]
                lat_dir = fields[4]
                longitude_str = fields[5]
                lon_dir = fields[6]
                speed_knots = fields[7] if fields[7] else "0.0"
                course = fields[8] if fields[8] else "0.0"
                date = fields[9]

                try:
                    # Parse latitude
                    latitude_degrees = float(latitude_str[:2])
                    latitude_minutes = float(latitude_str[2:])
                    latitude = latitude_degrees + latitude_minutes / 60
                    if lat_dir == "S":
                        latitude *= -1

                    # Parse longitude
                    longitude_degrees = float(longitude_str[:3])
                    longitude_minutes = float(longitude_str[3:])
                    longitude = longitude_degrees + longitude_minutes / 60
                    if lon_dir == "W":
                        longitude *= -1

                    speed_kmh = float(speed_knots) * 1.852
                    course = float(course)

                    data_list.append(
                        [time, latitude, longitude, speed_kmh, course, date]
                    )
                except Exception as e:
                    st.warning(f"Error parsing line: {line}\nError: {str(e)}")
                    continue

    df = pd.DataFrame(
        data_list,
        columns=[
            "Time",
            "Latitude (°)",
            "Longitude (°)",
            "Speed (km/h)",
            "Course (°)",
            "Date",
        ],
    )

    if not df.empty:
        # Convert time and date to datetime
        df["Time"] = pd.to_datetime(
            df["Date"] + df["Time"], format="%d%m%y%H%M%S.%f", errors="coerce"
        )
        df["Date"] = pd.to_datetime(df["Date"], format="%d%m%y", errors="coerce")

        # Convert to Eastern Time
        eastern = pytz.timezone("America/Toronto")
        df["Time (ET)"] = df["Time"].dt.tz_localize("UTC").dt.tz_convert(eastern)

        # Calculate time delta
        df["TimeDelta (s)"] = df["Time"].diff().dt.total_seconds()

        # Calculate acceleration
        df["SpeedDelta (km/h)"] = df["Speed (km/h)"].diff()
        df["Acceleration (m/s²)"] = (df["SpeedDelta (km/h)"] * 1000) / (
            df["TimeDelta (s)"] * 3600
        )

        # Calculate distance
        df["Distance (m)"] = df.apply(
            lambda row: haversine(
                row["Latitude (°)"],
                row["Longitude (°)"],
                df.loc[row.name - 1, "Latitude (°)"],
                df.loc[row.name - 1, "Longitude (°)"],
            )
            if row.name > 0
            else np.nan,
            axis=1,
        )

    return df


# Calculate statistics from the DataFrame
def calculate_statistics(df):
    stats = {}
    try:
        stats["Total Distance (km)"] = df["Distance (m)"].sum() / 1000
        stats["Total Time (hours)"] = df["TimeDelta (s)"].sum() / 3600
        stats["Average Speed (km/h)"] = df["Speed (km/h)"].mean()
        stats["Max Speed (km/h)"] = df["Speed (km/h)"].max()
        stats["Max Acceleration (m/s²)"] = df["Acceleration (m/s²)"].max()
        stats["Min Acceleration (m/s²)"] = df["Acceleration (m/s²)"].min()

        # Calculate number of sprints (contiguous periods above 15.1 km/h)
        if not df.empty and "Speed (km/h)" in df:
            sprint_mask = df["Speed (km/h)"] > 15.1
            # Count contiguous sprint periods
            sprint_starts = sprint_mask & ~sprint_mask.shift(1, fill_value=False)
            stats["Number of Sprints"] = sprint_starts.sum()
        else:
            stats["Number of Sprints"] = 0

    except Exception as e:
        st.error(f"Error calculating statistics: {e}")
    return pd.DataFrame.from_dict(stats, orient="index", columns=["Value"])


# Create a folium map with heatmap and satellite imagery
def create_speed_heatmap(df):
    df_filtered = df.dropna(subset=["Latitude (°)", "Longitude (°)", "Speed (km/h)"])
    if df_filtered.empty:
        return None

    # Create base map
    m = folium.Map(
        location=[
            df_filtered["Latitude (°)"].mean(),
            df_filtered["Longitude (°)"].mean(),
        ],
        zoom_start=13,
        tiles=None,
    )  # Start with no base tiles

    # Add Esri World Imagery as base layer
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite Imagery",
        overlay=False,
    ).add_to(m)

    # Add heatmap layer
    HeatMap(
        df_filtered[["Latitude (°)", "Longitude (°)", "Speed (km/h)"]].values.tolist(),
        radius=10,
        blur=15,
        max_zoom=13,
        min_opacity=0.5,
    ).add_to(m)

    # Add layer control
    folium.LayerControl().add_to(m)

    return m


# Main function to run the Streamlit app
def main():
    st.title("GPS Data Analysis")

    # File upload
    uploaded_files = st.file_uploader(
        "Upload GPS data files", type=["txt", "log"], accept_multiple_files=True
    )

    if uploaded_files:
        df = parse_gps_data(uploaded_files)

        if not df.empty:
            st.subheader("Key Performance Indicators")
            stats = calculate_statistics(df)
            st.dataframe(stats)

            st.subheader("Speed Heatmap")
            speed_map = create_speed_heatmap(df)
            if speed_map:
                folium_static(speed_map)
            else:
                st.warning("Not enough data to generate heatmap")

            st.subheader("Raw Data Preview")
            st.dataframe(df.head())
        else:
            st.error("No valid GPS data found in uploaded files")


if __name__ == "__main__":
    main()
