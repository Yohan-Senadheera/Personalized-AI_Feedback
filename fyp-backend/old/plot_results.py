import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("evaluation_asag_multi.csv")

teacher = pd.to_numeric(df["teacher_grade"], errors="coerce")
ai = pd.to_numeric(df["ai_grade_multi"], errors="coerce")

plt.scatter(teacher, ai)

plt.xlabel("Teacher Grade")
plt.ylabel("AI Grade")
plt.title("AI vs Teacher Grading")

plt.plot([0,100],[0,100],'r--')

plt.show()