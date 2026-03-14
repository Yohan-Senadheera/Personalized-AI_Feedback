import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error

FILE = "evaluation_asag_multi.csv"

df = pd.read_csv(FILE)

# convert to numeric
teacher = pd.to_numeric(df["teacher_grade"], errors="coerce")
ai = pd.to_numeric(df["ai_grade_multi"], errors="coerce")

# remove rows with missing
mask = teacher.notna() & ai.notna()
teacher = teacher[mask]
ai = ai[mask]

# MAE
mae = mean_absolute_error(teacher, ai)

# RMSE
rmse = np.sqrt(mean_squared_error(teacher, ai))

# within ±5 marks
within5 = np.mean(np.abs(teacher - ai) <= 5) * 100

# correlation
corr = teacher.corr(ai)

print("===== AI GRADING EVALUATION =====")
print(f"Samples: {len(teacher)}")
print(f"MAE: {mae:.2f}")
print(f"RMSE: {rmse:.2f}")
print(f"Within ±5 marks: {within5:.2f}%")
print(f"Correlation: {corr:.3f}")