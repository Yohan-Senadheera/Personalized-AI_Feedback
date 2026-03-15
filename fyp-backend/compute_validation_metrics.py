import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error

FILE = "evaluation_validation_openai.csv"

# validation dataset teacher score max
TEACHER_MAX = 3.5

df = pd.read_csv(FILE)

# keep only completed rows
df = df[df["ai_grade_multi"].notna()].copy()
df = df[df["ai_grade_multi"].astype(str).str.strip() != ""].copy()
df = df[~df["ai_grade_multi"].astype(str).str.startswith("ERROR:", na=False)].copy()

teacher_raw = pd.to_numeric(df["teacher_grade"], errors="coerce")
ai_raw = pd.to_numeric(df["ai_grade_multi"], errors="coerce")

mask = teacher_raw.notna() & ai_raw.notna()
teacher_raw = teacher_raw[mask]
ai_raw = ai_raw[mask]

# normalize teacher score to 0-100
teacher_pct = (teacher_raw / TEACHER_MAX) * 100.0
ai_pct = ai_raw  # already 0-100 in current pipeline

mae = mean_absolute_error(teacher_pct, ai_pct)
rmse = np.sqrt(mean_squared_error(teacher_pct, ai_pct))
within5 = np.mean(np.abs(teacher_pct - ai_pct) <= 5) * 100
corr = teacher_pct.corr(ai_pct)

print("===== VALIDATION OPENAI METRICS =====")
print(f"Samples: {len(teacher_pct)}")
print(f"Teacher scale max: {TEACHER_MAX}")
print(f"MAE: {mae:.2f}")
print(f"RMSE: {rmse:.2f}")
print(f"Within ±5: {within5:.2f}%")
print(f"Correlation: {corr:.3f}")
