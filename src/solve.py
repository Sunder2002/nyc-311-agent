import pandas as pd

print("Loading data...")
df = pd.read_csv("311_Service_Requests_from_2010_to_Present.csv", low_memory=False)
df['Created Date'] = pd.to_datetime(df['Created Date'], errors='coerce')
df['Closed Date'] = pd.to_datetime(df['Closed Date'], errors='coerce')

print("\n--- Q1: Top 10 complaint types ---")
top_10 = df['Complaint Type'].value_counts().head(10)
print(top_10)

print("\n--- Q2: For top 5 complaint types, percent closed within 3 days ---")
top_5_types = top_10.head(5).index
df_top_5 = df[df['Complaint Type'].isin(top_5_types)].copy()
df_top_5['Time to Close'] = df_top_5['Closed Date'] - df_top_5['Created Date']
df_top_5['Closed within 3 days'] = df_top_5['Time to Close'] <= pd.Timedelta(days=3)
percent_closed = df_top_5.groupby('Complaint Type')['Closed within 3 days'].mean() * 100
print(percent_closed)

print("\n--- Q3: Which ZIP code has the highest number of complaints? ---")
top_zip = df['Incident Zip'].value_counts().head(1)
print(top_zip)

print("\n--- Q4: Proportion with valid lat/lon ---")
has_lat_lon = df['Latitude'].notnull() & df['Longitude'].notnull()
prop = has_lat_lon.mean() * 100
print(f"{prop:.2f}%")
