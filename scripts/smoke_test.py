"""Quick sanity test for all metrics — run before pushing the dashboard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iron_trail import ingest, metrics

df = ingest.load_and_clean()
print(f"Loaded {len(df)} rows, {df['workout_id'].nunique()} workouts")

print("\n=== Strength ===")
ex = "Bench Press (Barbell)"
e1rm = metrics.per_session_top_e1rm(df, ex)
print(f"{ex}: {len(e1rm)} sessions, max e1RM = {e1rm['e1rm_kg'].max():.1f}kg, "
      f"PRs = {e1rm['is_pr'].sum()}")

print("\n=== Volume by muscle (last 15 rows) ===")
vol = metrics.weekly_volume_by_muscle(df)
print(vol.tail(15).to_string(index=False))

print("\n=== Push:Pull (last 8 weeks) ===")
pp = metrics.weekly_push_pull(df)
cols = [c for c in ['week', 'push', 'pull', 'push_pull_ratio'] if c in pp.columns]
print(pp[cols].tail(8).to_string(index=False))

print("\n=== Session volumes (head) ===")
sv = metrics.session_volume_per_workout(df)
print(sv.head(5).to_string(index=False))
print(f"total workouts: {len(sv)}")

print("\n=== Time of day ===")
tod = metrics.time_of_day_distribution(df)
print(tod.to_string(index=False))

print("\n=== Unmapped exercises ===")
unmapped = df[df['primary_muscle'] == 'unmapped']['exercise_title'].unique()
print(list(unmapped) or "(none)")

print("\n=== Overview stats ===")
print(metrics.overview_stats(df))
